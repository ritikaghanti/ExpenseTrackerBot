import os
import json
from datetime import date
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import pytesseract
from PIL import Image # Pillow library for image handling
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials
import logging # Added for better logging

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables (API keys, etc.) from a .env file
load_dotenv()

# Initialize OpenAI Client (Make sure this is here!)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
if not os.getenv("OPENAI_API_KEY"):
    logging.warning("OPENAI_API_KEY environment variable not set.")

# Initialize the Flask app
app = Flask(__name__)

# --- Helper Functions ---

def extract_text_from_image(image_path):
    """Uses Tesseract OCR to extract text from an image file."""
    try:
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img)
        logging.info(f"OCR Success: Extracted text from {image_path}")
        return text
    except Exception as e:
        logging.error(f"Error during OCR on {image_path}: {e}")
        return ""

def parse_expense_with_ai(text_to_parse):
    """Sends text to OpenAI to extract expense details using JSON mode."""
    if not text_to_parse or len(text_to_parse.strip()) < 5:
        logging.info("Input text too short or empty, skipping AI.")
        return None

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
        response = client.chat.completions.create(
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

        # Validate AI response structure more carefully
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
    """Logs the parsed expense data to the Google Sheet."""
    try:
        logging.info(f"Attempting to log to Google Sheet: {expense_data}")
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

        # Make sure the sheet name matches exactly what you created
        sheet_name = "My expenses"
        worksheet = gc.open(sheet_name).sheet1

        amount = float(expense_data['amount']) # We already validated it's a number in parse_expense_with_ai
        new_row = [
            str(date.today()),
            amount,
            expense_data.get('vendor', 'Unknown'),
            expense_data.get('category', 'Other')
        ]

        worksheet.append_row(new_row, value_input_option='USER_ENTERED')
        logging.info(f"Successfully appended row to Google Sheet: {new_row}")
        return True
    except gspread.exceptions.SpreadsheetNotFound:
        logging.error(f"Error: Spreadsheet '{sheet_name}' not found or not shared with service account.")
        return False
    except Exception as e:
        logging.error(f"Error logging to Google Sheet: {e}")
        return False

# --- Webhook Endpoint ---

@app.route('/webhook', methods=['POST'])
def sendgrid_webhook():
    logging.info("Webhook received!")
    sender = request.form.get('from')
    subject = request.form.get('subject')
    body_plain = request.form.get('text', '') # Default to empty string
    body_html = request.form.get('html', '') # Default to empty string

    input_text = ""
    image_path = None
    cleanup_path = None # Store path for cleanup

    try:
        # Check for attachments
        num_attachments = int(request.form.get('attachments', 0))
        if num_attachments > 0:
            logging.info(f"Found {num_attachments} attachment(s).")
            for i in range(1, num_attachments + 1):
                attachment = request.files.get(f'attachment{i}')
                # Check if it's a valid file and looks like an image
                if attachment and attachment.filename and attachment.mimetype and attachment.mimetype.startswith('image/'):
                    logging.info(f"Processing image attachment: {attachment.filename}")
                    # Ensure /tmp directory exists
                    temp_dir = "/tmp"
                    os.makedirs(temp_dir, exist_ok=True)
                    # Use a safer filename or unique name if needed, but simple join is ok for /tmp
                    image_path = os.path.join(temp_dir, attachment.filename)
                    cleanup_path = image_path # Mark for cleanup
                    attachment.save(image_path)
                    logging.info(f"Saved image to {image_path}")

                    # Call OCR function
                    input_text = extract_text_from_image(image_path)
                    break # Stop after processing the first image found
                elif attachment and attachment.filename:
                    logging.info(f"Skipping non-image attachment: {attachment.filename}")


        # If no text came from an image, use the email body (prefer plain text)
        if not input_text:
            logging.info("No image text found, using email body.")
            input_text = body_plain if body_plain else body_html

        logging.info(f"Received email from: {sender} | Subject: {subject}")
        logging.info(f"Input text for AI (first 200 chars): {input_text[:200]}...")

        # Call AI Parser
        parsed_data = parse_expense_with_ai(input_text)

        # Log to Google Sheets if parsing was successful
        if parsed_data:
            log_successful = log_to_google_sheet(parsed_data)
            if log_successful:
                logging.info("Expense logged successfully.")
            else:
                logging.warning("Failed to log expense to Google Sheet.")
        else:
            logging.info("No valid expense data parsed by AI. Nothing logged.")

    except Exception as e:
        logging.error(f"An error occurred in the webhook handler: {e}")
        # Still return success to SendGrid unless it's a critical failure
        # to avoid SendGrid retrying endlessly for parsing errors.
        # Consider more nuanced error handling if needed.

    finally:
        # Clean up the temporary image file if it exists
        if cleanup_path and os.path.exists(cleanup_path):
            try:
                os.remove(cleanup_path)
                logging.info(f"Cleaned up temporary image: {cleanup_path}")
            except Exception as e:
                logging.error(f"Error cleaning up image {cleanup_path}: {e}")

    # Tell SendGrid the webhook was received successfully
    return jsonify({"status": "received"}), 200

# --- Main Entry Point ---

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001)) # Changed default port slightly just in case 5000 is common
    # Turn debug=False when deploying to Render
    app.run(host='0.0.0.0', port=port, debug=False)