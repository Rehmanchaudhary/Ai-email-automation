import os
import time
import logging
import smtplib
import email
from email.utils import parseaddr
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from dotenv import load_dotenv
from groq import Groq
from imapclient import IMAPClient


# =========================
# SETUP
# =========================

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

MODEL = "llama-3.1-8b-instant"

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

YOUR_NAME = "Rehman"

IMAP_HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

CHECK_INTERVAL_SECONDS = 60


# =========================
# FETCH EMAIL
# =========================

def fetch_latest_unread_email():

    try:

        print("🔍 Checking Gmail for unread emails...")

        with IMAPClient(IMAP_HOST, ssl=True) as server:

            server.login(
                GMAIL_ADDRESS,
                GMAIL_APP_PASSWORD
            )

            server.select_folder("INBOX")

            messages = server.search(["UNSEEN"])

            if not messages:
                return None

            latest_uid = messages[-1]

            raw_message = server.fetch(
                [latest_uid],
                ["RFC822"]
            )[latest_uid][b"RFC822"]

            msg = email.message_from_bytes(raw_message)

            raw_from = msg.get("From", "")

            sender_name, sender_email = parseaddr(raw_from)

            if not sender_name:
                sender_name = sender_email.split("@")[0]

            subject = msg.get(
                "Subject",
                "(no subject)"
            )

            body = ""

            if msg.is_multipart():

                for part in msg.walk():

                    content_type = part.get_content_type()

                    disposition = str(
                        part.get("Content-Disposition")
                    )

                    if (
                        content_type == "text/plain"
                        and "attachment" not in disposition
                    ):

                        charset = (
                            part.get_content_charset()
                            or "utf-8"
                        )

                        payload = part.get_payload(
                            decode=True
                        )

                        if payload:

                            body = payload.decode(
                                charset,
                                errors="replace"
                            )

                        break

            else:

                charset = (
                    msg.get_content_charset()
                    or "utf-8"
                )

                payload = msg.get_payload(
                    decode=True
                )

                if payload:

                    body = payload.decode(
                        charset,
                        errors="replace"
                    )

            body = body.strip()

            if not body:

                body = "(No plain text content found)"

            return {
                "uid": latest_uid,
                "sender_name": sender_name,
                "sender_email": sender_email,
                "subject": subject,
                "body": body
            }

    except Exception as e:

        logging.exception(
            "❌ Error while fetching email"
        )

        print(
            f"❌ Error while fetching email: {e}"
        )

        return None


# =========================
# FILTERS
# =========================

def is_automated_sender(sender_email):

    automated_patterns = [
        "no-reply",
        "noreply",
        "donotreply",
        "notifications",
        "mailer-daemon"
    ]

    sender_email = sender_email.lower()

    return any(
        pattern in sender_email
        for pattern in automated_patterns
    )


def is_self_sent(sender_email):

    return (
        sender_email.lower()
        == GMAIL_ADDRESS.lower()
    )


# =========================
# AI
# =========================

def ask_ai(prompt):

    try:

        print("🤖 Sending request to Groq AI...")

        response = client.chat.completions.create(

            model=MODEL,

            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],

            temperature=0.3
        )

        result = (
            response
            .choices[0]
            .message
            .content
            .strip()
        )

        return result

    except Exception as e:

        logging.exception(
            "❌ Groq AI request failed"
        )

        print(
            f"❌ Groq AI request failed: {e}"
        )

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


# =========================
# SEND EMAIL
# =========================

def send_email_real(
    to_address,
    subject,
    body
):

    try:

        print(
            f"📤 Sending reply to {to_address}..."
        )

        msg = MIMEMultipart()

        msg["From"] = GMAIL_ADDRESS

        msg["To"] = to_address

        msg["Subject"] = f"Re: {subject}"

        msg.attach(
            MIMEText(
                body,
                "plain",
                "utf-8"
            )
        )

        with smtplib.SMTP(
            SMTP_HOST,
            SMTP_PORT
        ) as server:

            server.ehlo()

            server.starttls()

            server.ehlo()

            server.login(
                GMAIL_ADDRESS,
                GMAIL_APP_PASSWORD
            )

            server.sendmail(
                GMAIL_ADDRESS,
                to_address,
                msg.as_string()
            )

        print(
            f"✅ REPLY SENT SUCCESSFULLY TO {to_address}"
        )

        logging.info(
            f"Reply successfully sent to {to_address}"
        )

        return True

    except Exception as e:

        logging.exception(
            "❌ SMTP SEND FAILED"
        )

        print(
            f"❌ SMTP SEND FAILED: {e}"
        )

        return False


# =========================
# MARK EMAIL AS PROCESSED
# =========================

def mark_as_seen(uid):

    try:

        with IMAPClient(
            IMAP_HOST,
            ssl=True
        ) as server:

            server.login(
                GMAIL_ADDRESS,
                GMAIL_APP_PASSWORD
            )

            server.select_folder(
                "INBOX",
                readonly=False
            )

            server.add_flags(
                [uid],
                [b"\\Seen"]
            )

        print(
            "✅ Email marked as processed."
        )

    except Exception as e:

        print(
            f"⚠️ Could not mark email as seen: {e}"
        )


# =========================
# PROCESS EMAIL
# =========================

def process_one_email():

    email_data = fetch_latest_unread_email()

    if email_data is None:

        print(
            "📭 No new unread emails."
        )

        return False


    print("\n")
    print("=" * 60)
    print("📩 NEW EMAIL FOUND")
    print("=" * 60)

    print(
        f"From: {email_data['sender_name']} "
        f"<{email_data['sender_email']}>"
    )

    print(
        f"Subject: {email_data['subject']}"
    )


    sender_email = email_data[
        "sender_email"
    ]


    # Skip automated emails

    if is_automated_sender(
        sender_email
    ):

        print(
            "⏭️ Automated sender skipped."
        )

        mark_as_seen(
            email_data["uid"]
        )

        return True


    # Skip emails sent from the same account

    if is_self_sent(
        sender_email
    ):

        print(
            "⏭️ Self-sent email skipped."
        )

        mark_as_seen(
            email_data["uid"]
        )

        return True


    # CLASSIFICATION

    print("🏷️ Classifying email...")

    category = classify_email(
        email_data["body"]
    )

    if category is None:

        print(
            "❌ Classification failed."
        )

        return False

    print(
        f"🏷️ CATEGORY: {category}"
    )


    # URGENCY

    print(
        "⚡ Detecting urgency..."
    )

    urgency = detect_urgency(
        email_data["body"]
    )

    if urgency is None:

        print(
            "❌ Urgency detection failed."
        )

        return False

    print(
        f"⚡ URGENCY: {urgency}"
    )


    # GENERATE REPLY

    print(
        "✍️ Generating AI reply..."
    )

    reply = generate_reply(

        email_data["body"],

        email_data["sender_name"]

    )

    if reply is None:

        print(
            "❌ Reply generation failed."
        )

        return False


    print("\n")
    print("🤖 GENERATED REPLY:")
    print("-" * 60)
    print(reply)
    print("-" * 60)


    # SEND REPLY

    sent = send_email_real(

        email_data["sender_email"],

        email_data["subject"],

        reply

    )


    if sent:

        # Only mark as seen after successful processing

        mark_as_seen(
            email_data["uid"]
        )

        print(
            "🎉 COMPLETE: Email processed and reply sent!"
        )

        return True


    print(
        "❌ Email was NOT sent."
    )

    return False


# =========================
# MAIN LOOP
# =========================

def run_forever():

    print(
        "📬 AI EMAIL AUTOMATION STARTED"
    )

    print(
        "📡 Checking Gmail every 60 seconds"
    )

    print(
        "🚀 Automatic reply mode enabled"
    )


    while True:

        try:

            process_one_email()

        except Exception as e:

            logging.exception(
                "Unexpected error in main loop"
            )

            print(
                f"❌ Unexpected error: {e}"
            )

        time.sleep(
            CHECK_INTERVAL_SECONDS
        )


if __name__ == "__main__":

    run_forever()