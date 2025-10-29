import os
import time
import email # Library for parsing email messages
from email.header import decode_header
import imaplib # Library for IMAP connection
import base64 # For decoding attachments

from dotenv import load_dotenv
import pytesseract
from PIL import Image
from openai import OpenAI
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import date
import logging

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
load_dotenv()

# --- Initialize Clients (Keep these) ---
# OpenAI
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
if not os.getenv("OPENAI_API_KEY"):
    logging.warning("OPENAI_API_KEY environment variable not set.")

# --- Helper Functions (Keep/Adapt These) ---
def extract_text_from_image(image_path):
    # (Keep your existing function)
    try:
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img)
        logging.info(f"OCR Success: Extracted text from {image_path}")
        return text
    except Exception as e:
        logging.error(f"Error during OCR on {image_path}: {e}")
        return ""

def parse_expense_with_ai(text_to_parse):
    # (Keep your existing function, but use openai_client)
    if not text_to_parse or len(text_to_parse.strip()) < 5:
        logging.info("Input text too short or empty, skipping AI.")
        return None
    # --- Make sure to update the client variable name if you changed it ---
    system_prompt = """
    You are an expert accountant's assistant...
    Return *only* a valid JSON object...
    The category *must* be one of: [Food, Transport, ...].
    ...
    If the email is *not* an expense, return {"amount": null, ...}.

    **Handling Minimal Input:**
    * If the vendor isn't clear, infer a generic one from the item (e.g., 'coffee' -> 'Coffee Shop', 'gas' -> 'Gas Station').
    * If the category isn't clear, use 'Other'.

    **Example 1 (Minimal):**
    *Input:* 'spent $15 on coffee'
    *Output:* `{ "amount": 15.00, "vendor": "Coffee Shop", "category": "Food" }`  # Note the inferred vendor

    **Example 2 (Minimal):**
    *Input:* '$50 gas'
    *Output:* `{ "amount": 50.00, "vendor": "Gas Station", "category": "Transport" }` # Inferred vendor & category

    **Example 3 (More Detail):**
    *Input:* 'spent $35 on a book about dragons'
    *Output:* `{ "amount": 35.00, "vendor": "Book", "category": "Shopping" }`

    **Example 4 (HTML Receipt):**
    *Input:* '...[messy HTML]... Total: $18.50 ... Uber Eats ...'
    *Output:* `{ "amount": 18.50, "vendor": "Uber Eats", "category": "Food" }`
    """
    try:
        logging.info("Sending text to AI for parsing...")
        response = openai_client.chat.completions.create( # Use initialized client
            model="gpt-3.5-turbo",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text_to_parse}
            ],
            temperature=0.2
        )
        result_json_string = response.choices[0].message.content
        logging.info(f"AI Response String: {result_json_string}")
        result_dict = json.loads(result_json_string)

        if result_dict.get("amount") is not None and isinstance(result_dict.get("amount"), (int, float)) \
           and result_dict.get("vendor") and result_dict.get("category"):
            logging.info(f"AI Parsing Success: {result_dict}")
            return result_dict
        else:
            logging.info("AI returned nulls or invalid data, likely not an expense.")
            return None
    except Exception as e:
        logging.error(f"Error calling OpenAI API or parsing JSON: {e}")
        return None


def log_to_google_sheet(expense_data):
    # (Keep your existing function)
    try:
        logging.info(f"Attempting to log to Google Sheet: {expense_data}")
        # ... (rest of your gspread logic) ...
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if not creds_path:
            logging.error("Error: GOOGLE_APPLICATION_CREDENTIALS environment variable not set.")
            return False
        credentials = Credentials.from_service_account_file(creds_path, scopes=scopes)
        gc = gspread.authorize(credentials)
        sheet_name = "My expenses" # Make sure this matches your sheet name
        worksheet = gc.open(sheet_name).sheet1
        amount = float(expense_data['amount'])
        new_row = [str(date.today()), amount, expense_data.get('vendor', 'Unknown'), expense_data.get('category', 'Other')]
        worksheet.append_row(new_row, value_input_option='USER_ENTERED')
        logging.info(f"Successfully appended row to Google Sheet: {new_row}")
        return True
    except gspread.exceptions.SpreadsheetNotFound:
        logging.error(f"Error: Spreadsheet '{sheet_name}' not found or not shared with service account.")
        return False
    except Exception as e:
        logging.error(f"Error logging to Google Sheet: {e}")
        return False

# --- New IMAP Processing Logic ---

def process_emails():
    """Connects to Gmail, processes unseen emails, logs expenses, marks as seen."""
    logging.info("Checking for new emails...")
    IMAP_SERVER = "imap.gmail.com"
    EMAIL_ACCOUNT = os.getenv("GMAIL_EMAIL")
    APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

    if not EMAIL_ACCOUNT or not APP_PASSWORD:
        logging.error("Gmail email or app password not set in environment variables.")
        return

    mail = None # Initialize mail variable
    try:
        # Connect to the server
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        # Login
        mail.login(EMAIL_ACCOUNT, APP_PASSWORD)
        # Select the inbox
        mail.select("inbox")

        # Search for all unseen emails
        status, messages = mail.search(None, "UNSEEN")
        if status != "OK":
            logging.error("Failed to search for emails.")
            return

        email_ids = messages[0].split()
        logging.info(f"Found {len(email_ids)} unseen email(s).")

        for email_id in email_ids:
            logging.info(f"Processing email ID: {email_id.decode()}")
            input_text = ""
            image_path = None
            cleanup_path = None

            try:
                # Fetch the email by ID
                status, msg_data = mail.fetch(email_id, "(RFC822)")
                if status != "OK":
                    logging.warning(f"Failed to fetch email ID: {email_id.decode()}")
                    continue # Skip to next email

                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        # Parse the email content
                        msg = email.message_from_bytes(response_part[1])

                        # Decode email subject
                        subject, encoding = decode_header(msg["Subject"])[0]
                        if isinstance(subject, bytes):
                            subject = subject.decode(encoding if encoding else "utf-8")
                        # Decode sender
                        from_ = msg.get("From")
                        logging.info(f"Processing email From: {from_} | Subject: {subject}")

                        # Initialize body variables
                        body_plain = ""
                        body_html = ""

                        # If the email is multipart
                        if msg.is_multipart():
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                content_disposition = str(part.get("Content-Disposition"))

                                # --- Handle Text/HTML Body Parts ---
                                if content_type == "text/plain" and "attachment" not in content_disposition:
                                    try:
                                        body_plain = part.get_payload(decode=True).decode()
                                    except:
                                        logging.warning("Could not decode plain text part.")
                                elif content_type == "text/html" and "attachment" not in content_disposition:
                                     try:
                                        body_html = part.get_payload(decode=True).decode()
                                     except:
                                         logging.warning("Could not decode html text part.")

                                # --- Handle Image Attachments ---
                                elif "attachment" in content_disposition and part.get_content_maintype() == 'image':
                                    filename = part.get_filename()
                                    if filename:
                                        # Decode filename
                                        filename, fn_encoding = decode_header(filename)[0]
                                        if isinstance(filename, bytes):
                                            filename = filename.decode(fn_encoding if fn_encoding else "utf-8")

                                        logging.info(f"Found image attachment: {filename}")
                                        # Ensure /tmp directory exists
                                        temp_dir = "/tmp"
                                        os.makedirs(temp_dir, exist_ok=True)
                                        image_path = os.path.join(temp_dir, filename)
                                        cleanup_path = image_path # Mark for cleanup

                                        # Save the attachment
                                        try:
                                            with open(image_path, "wb") as f:
                                                f.write(part.get_payload(decode=True))
                                            logging.info(f"Saved image to {image_path}")
                                            # Call OCR
                                            input_text = extract_text_from_image(image_path)
                                        except Exception as e:
                                            logging.error(f"Failed to save or OCR attachment {filename}: {e}")
                                            input_text = "" # Reset if save/OCR fails

                        # If email is not multipart (plain text or html only)
                        else:
                            content_type = msg.get_content_type()
                            try:
                                body = msg.get_payload(decode=True).decode()
                                if content_type == "text/plain":
                                    body_plain = body
                                elif content_type == "text/html":
                                    body_html = body
                            except:
                                logging.warning("Could not decode non-multipart body.")

                        # --- Determine input_text (after processing all parts) ---
                        if not input_text: # If OCR didn't provide text
                           input_text = body_plain if body_plain else body_html # Prefer plain text

                        # --- Process the extracted text ---
                        if input_text:
                            logging.info(f"Input text for AI (first 200 chars): {input_text[:200]}...")
                            parsed_data = parse_expense_with_ai(input_text)
                            if parsed_data:
                                log_to_google_sheet(parsed_data)
                        else:
                            logging.info("No usable text found in email body or attachments.")

                        # --- Mark email as SEEN (processed) ---
                        # Use email_id directly, ensure it's bytes
                        mail.store(email_id, '+FLAGS', '\\Seen')
                        logging.info(f"Marked email ID {email_id.decode()} as Seen.")

            finally: # Ensure cleanup happens per email
                 # Clean up the temporary image file if it exists
                if cleanup_path and os.path.exists(cleanup_path):
                    try:
                        os.remove(cleanup_path)
                        logging.info(f"Cleaned up temporary image: {cleanup_path}")
                    except Exception as e:
                        logging.error(f"Error cleaning up image {cleanup_path}: {e}")

    except imaplib.IMAP4.error as e:
        logging.error(f"IMAP Error: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
    finally:
        # Always try to logout and close connection
        if mail:
            try:
                mail.close()
                mail.logout()
                logging.info("Logged out and closed IMAP connection.")
            except Exception as e:
                logging.error(f"Error during IMAP logout/close: {e}")

# --- Main Loop ---
if __name__ == "__main__":
    POLLING_INTERVAL_SECONDS = 60 # Check every 60 seconds
    logging.info(f"Starting expense tracker. Polling interval: {POLLING_INTERVAL_SECONDS} seconds.")
    while True:
        process_emails()
        logging.info(f"Sleeping for {POLLING_INTERVAL_SECONDS} seconds...")
        time.sleep(POLLING_INTERVAL_SECONDS)