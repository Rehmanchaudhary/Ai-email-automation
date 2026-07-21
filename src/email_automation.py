import os
import time
import json
import base64
import logging

from email.mime.text import MIMEText

from dotenv import load_dotenv
from groq import Groq

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TOKEN_JSON = os.getenv("TOKEN_JSON")
CREDENTIALS_JSON = os.getenv("CREDENTIALS_JSON")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is missing from environment variables.")

if not TOKEN_JSON:
    raise RuntimeError("TOKEN_JSON is missing from environment variables.")

if not CREDENTIALS_JSON:
    raise RuntimeError("CREDENTIALS_JSON is missing from environment variables.")


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# ============================================================
# AI CONFIGURATION
# ============================================================

client = Groq(api_key=GROQ_API_KEY)
MODEL = "llama-3.1-8b-instant"
YOUR_NAME = "Rehman"

CHECK_INTERVAL_SECONDS = 60

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


# ============================================================
# GMAIL API AUTH (HTTPS only — no SMTP/IMAP, no blocked ports)
# ============================================================

def get_gmail_service():
    token_data = json.loads(TOKEN_JSON)
    creds_data = json.loads(CREDENTIALS_JSON)

    client_info = creds_data.get("installed") or creds_data.get("web") or {}

    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id") or client_info.get("client_id"),
        client_secret=token_data.get("client_secret") or client_info.get("client_secret"),
        scopes=token_data.get("scopes", SCOPES),
    )

    if creds.expired and creds.refresh_token:
        print("🔄 Refreshing Gmail access token...")
        creds.refresh(Request())

    return build("gmail", "v1", credentials=creds)


GMAIL_SERVICE = get_gmail_service()
MY_EMAIL_ADDRESS = GMAIL_SERVICE.users().getProfile(userId="me").execute()["emailAddress"]
print(f"✅ Authenticated as: {MY_EMAIL_ADDRESS}")


# ============================================================
# FETCH LATEST UNREAD EMAIL (via Gmail API, HTTPS)
# ============================================================

def fetch_latest_unread_email():
    try:
        print("🔍 Checking Gmail for unread emails...")

        resp = (
            GMAIL_SERVICE.users()
            .messages()
            .list(userId="me", labelIds=["INBOX", "UNREAD"], maxResults=1)
            .execute()
        )

        messages = resp.get("messages", [])

        if not messages:
            return None

        msg_id = messages[0]["id"]

        msg = (
            GMAIL_SERVICE.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )

        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}

        raw_from = headers.get("From", "")
        if "<" in raw_from and ">" in raw_from:
            sender_name = raw_from.split("<")[0].strip().strip('"')
            sender_email = raw_from.split("<")[1].split(">")[0].strip()
        else:
            sender_email = raw_from.strip()
            sender_name = sender_email.split("@")[0]

        if not sender_name:
            sender_name = sender_email.split("@")[0]

        subject = headers.get("Subject", "(no subject)")

        body = _extract_body(msg["payload"])

        if not body:
            body = "(No readable plain-text content found.)"

        return {
            "msg_id": msg_id,
            "sender_name": sender_name,
            "sender_email": sender_email,
            "subject": subject,
            "body": body.strip(),
        }

    except HttpError as e:
        logging.exception("❌ ERROR WHILE FETCHING EMAIL")
        print(f"❌ Error while fetching email: {e}")
        return None


def _extract_body(payload):
    """Recursively find the text/plain part of a Gmail API message payload."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        result = _extract_body(part)
        if result:
            return result

    return ""


# ============================================================
# FILTERS
# ============================================================

def is_automated_sender(sender_email):
    automated_patterns = ["no-reply", "noreply", "donotreply", "notifications", "mailer-daemon"]
    sender_email = sender_email.lower()
    return any(p in sender_email for p in automated_patterns)


def is_self_sent(sender_email):
    return sender_email.lower() == MY_EMAIL_ADDRESS.lower()


# ============================================================
# GROQ AI
# ============================================================

def ask_ai(prompt):
    try:
        print("🤖 Sending request to Groq AI...")
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.exception("❌ GROQ AI REQUEST FAILED")
        print(f"❌ Groq AI request failed: {e}")
        return None


def classify_email(email_text):
    prompt = f"""
Classify this email into exactly ONE category:

Order Issue
Complaint
General Inquiry
Support Request
Spam/Irrelevant

Respond with ONLY the category name.

Email:

{email_text}
"""
    return ask_ai(prompt)


def detect_urgency(email_text):
    prompt = f"""
Rate this email as exactly ONE:

High
Medium
Low

Respond with ONLY the urgency level.

Email:

{email_text}
"""
    return ask_ai(prompt)


def generate_reply(email_text, sender_name):
    prompt = f"""
You are a professional email assistant.

Write a short, natural, professional reply to this email.

The sender's name is:

{sender_name}

Start with:

Dear {sender_name},

End with exactly:

Best regards,
{YOUR_NAME}

Do not use placeholders.

Email:

{email_text}
"""
    return ask_ai(prompt)


# ============================================================
# SEND EMAIL USING GMAIL API (HTTPS — never blocked)
# ============================================================

def send_email_real(to_address, subject, body):
    try:
        print(f"📤 Sending reply to {to_address} using Gmail API...")

        message = MIMEText(body)
        message["to"] = to_address
        message["subject"] = f"Re: {subject}"

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        sent = (
            GMAIL_SERVICE.users()
            .messages()
            .send(userId="me", body={"raw": raw_message})
            .execute()
        )

        print(f"✅ REPLY SENT SUCCESSFULLY TO {to_address} (id: {sent['id']})")
        logging.info(f"Gmail API email sent successfully to {to_address}")
        return True

    except HttpError as e:
        logging.exception("❌ GMAIL API SEND FAILED")
        print(f"❌ GMAIL API SEND FAILED: {e}")
        return False


# ============================================================
# MARK EMAIL AS SEEN (via Gmail API)
# ============================================================

def mark_as_seen(msg_id):
    try:
        GMAIL_SERVICE.users().messages().modify(
            userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()
        print("✅ Email marked as processed.")
    except HttpError as e:
        print(f"⚠️ Could not mark email as seen: {e}")


# ============================================================
# PROCESS ONE EMAIL
# ============================================================

def process_one_email():
    email_data = fetch_latest_unread_email()

    if email_data is None:
        print("📭 No new unread emails.")
        return False

    print()
    print("=" * 60)
    print("📩 NEW EMAIL FOUND")
    print("=" * 60)
    print(f"From: {email_data['sender_name']} <{email_data['sender_email']}>")
    print(f"Subject: {email_data['subject']}")

    sender_email = email_data["sender_email"]

    if is_automated_sender(sender_email):
        print("⏭️ Automated sender skipped.")
        mark_as_seen(email_data["msg_id"])
        return True

    if is_self_sent(sender_email):
        print("⏭️ Self-sent email skipped.")
        mark_as_seen(email_data["msg_id"])
        return True

    print("🏷️ Classifying email...")
    category = classify_email(email_data["body"])
    if category is None:
        print("❌ Classification failed.")
        return False
    print(f"🏷️ CATEGORY: {category}")

    print("⚡ Detecting urgency...")
    urgency = detect_urgency(email_data["body"])
    if urgency is None:
        print("❌ Urgency detection failed.")
        return False
    print(f"⚡ URGENCY: {urgency}")

    print("✍️ Generating AI reply...")
    reply = generate_reply(email_data["body"], email_data["sender_name"])
    if reply is None:
        print("❌ Reply generation failed.")
        return False

    print()
    print("🤖 GENERATED REPLY:")
    print("-" * 60)
    print(reply)
    print("-" * 60)

    sent = send_email_real(email_data["sender_email"], email_data["subject"], reply)

    if sent:
        mark_as_seen(email_data["msg_id"])
        print("🎉 COMPLETE: Email processed and reply sent!")
        return True

    print("❌ Email was NOT sent.")
    return False


# ============================================================
# MAIN LOOP
# ============================================================

def run_forever():
    print("📬 AI EMAIL AUTOMATION STARTED (Gmail API mode)")
    print("📡 Checking Gmail every 60 seconds")
    print("🚀 Automatic reply mode enabled")

    while True:
        try:
            process_one_email()
        except Exception as e:
            logging.exception("❌ UNEXPECTED ERROR IN MAIN LOOP")
            print(f"❌ Unexpected error: {e}")

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    run_forever()
