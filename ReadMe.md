# 📩 AI Inbox Expense Tracker

An automated expense logger that uses AI to understand your emails.

You can forward receipts, expense emails, or even photo attachments to a dedicated email inbox — the app reads them automatically, extracts key information using AI, and logs everything neatly into a Google Sheet.  

Supports both **IMAP polling** (periodic checks) and **FastAPI webhook** (real-time) modes.

---

## 🚀 Features

- ✅ Automatically reads new expense emails (IMAP or webhook)
- 🧠 Uses **GPT-3.5** (or similar LLM) to extract:
  - Vendor  
  - Amount  
  - Category  
  - Date (optional)
- 🖼️ Handles **photo receipts** using **Tesseract OCR**
- 🗂️ Logs clean, structured data into a **Google Sheet** using `gspread`
- ⚙️ Configurable polling interval or webhook setup
- 🔒 Secure credential handling via environment variables

---

Create a .env file in the project root:

```
EMAIL_USER=your_inbox@gmail.com
EMAIL_PASS=your_app_password
OPENAI_API_KEY=your_openai_key
GOOGLE_APPLICATION_CREDENTIALS=service_account.json
```

---


### How IMAP Polling Mode works

- Connects to Gmail via IMAP using imaplib

- Checks for new (unread) emails every few minutes

- Downloads attachments or extracts email body text

- Runs Tesseract OCR if an image is found

- Sends the text to GPT-3.5 with a structured extraction prompt

- Logs the clean data into Google Sheets via the Sheets API


### FastAPI Webhook Mode

- Configure your email service (like SendGrid) to forward inbound messages to your FastAPI endpoint

- The webhook receives the email payload instantly

- Extracts attachments/text → runs OCR → sends to GPT-3.5 → logs to Google Sheets

## Key Libraries

- imaplib, email – Read and parse emails

- pytesseract – OCR for images

- openai – GPT-3.5 API for text extraction

- gspread – Google Sheets integration

- fastapi, uvicorn – Webhook mode

- python-dotenv – Environment management


---

Author

Built by Ritika Ghanti — exploring how AI + automation can simplify everyday workflows.
Feel free to connect [LinkedIn](https://www.linkedin.com/in/ritika-ghanti/)