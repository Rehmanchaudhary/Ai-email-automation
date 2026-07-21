import os
import time
import logging
import email

from email.utils import parseaddr
from email.mime.text import MIMEText

import smtplib
import socket

from dotenv import load_dotenv
from groq import Groq
from imapclient import IMAPClient


# ============================================================
# FORCE IPv4 (fixes "OSError: [Errno 101] Network is unreachable"
# on Render, which happens when Python tries IPv6 first and the
# container has no IPv6 route)
# ============================================================

_original_getaddrinfo = socket.getaddrinfo

def _ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

socket.getaddrinfo = _ipv4_only_getaddrinfo


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")


# ============================================================
# VALIDATE ENVIRONMENT VARIABLES
# ============================================================

if not GMAIL_ADDRESS:
    raise RuntimeError(
        "GMAIL_ADDRESS is missing from environment variables."
    )

if not GMAIL_APP_PASSWORD:
    raise RuntimeError(
        "GMAIL_APP_PASSWORD is missing from environment variables."
    )

if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY is missing from environment variables."
    )


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


# ============================================================
# AI CONFIGURATION
# ============================================================

client = Groq(
    api_key=GROQ_API_KEY
)

MODEL = "llama-3.1-8b-instant"

YOUR_NAME = "Rehman"


# ============================================================
# GMAIL IMAP / SMTP CONFIGURATION
# ============================================================

IMAP_HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

CHECK_INTERVAL_SECONDS = 60


# ============================================================
# FETCH LATEST UNREAD EMAIL
# ============================================================

def fetch_latest_unread_email():

    try:

        print("🔍 Checking Gmail for unread emails...")

        with IMAPClient(
            IMAP_HOST,
            ssl=True
        ) as server:

            server.login(
                GMAIL_ADDRESS,
                GMAIL_APP_PASSWORD
            )

            server.select_folder(
                "INBOX"
            )

            messages = server.search(
                ["UNSEEN"]
            )

            if not messages:

                return None

            latest_uid = messages[-1]

            raw_message = server.fetch(
                [latest_uid],
                ["RFC822"]
            )[latest_uid][b"RFC822"]

            msg = email.message_from_bytes(
                raw_message
            )

            raw_from = msg.get(
                "From",
                ""
            )

            sender_name, sender_email = parseaddr(
                raw_from
            )

            if not sender_email:

                logging.warning(
                    "Email has no valid sender address."
                )

                return None

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

                    content_disposition = str(
                        part.get(
                            "Content-Disposition",
                            ""
                        )
                    )

                    if (
                        content_type == "text/plain"
                        and
                        "attachment"
                        not in content_disposition.lower()
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

                body = (
                    "(No readable plain-text "
                    "content found.)"
                )

            return {

                "uid": latest_uid,

                "sender_name": sender_name,

                "sender_email": sender_email,

                "subject": subject,

                "body": body

            }

    except Exception as e:

        logging.exception(
            "❌ ERROR WHILE FETCHING EMAIL"
        )

        print(
            f"❌ Error while fetching email: {e}"
        )

        return None


# ============================================================
# FILTERS
# ============================================================

def is_automated_sender(
    sender_email
):

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


def is_self_sent(
    sender_email
):

    return (

        sender_email.lower()

        ==

        GMAIL_ADDRESS.lower()

    )


# ============================================================
# GROQ AI
# ============================================================

def ask_ai(
    prompt
):

    try:

        print(
            "🤖 Sending request to Groq AI..."
        )

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

            "❌ GROQ AI REQUEST FAILED"

        )

        print(

            f"❌ Groq AI request failed: {e}"

        )

        return None


# ============================================================
# CLASSIFY EMAIL
# ============================================================

def classify_email(
    email_text
):

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

    return ask_ai(
        prompt
    )


# ============================================================
# DETECT URGENCY
# ============================================================

def detect_urgency(
    email_text
):

    prompt = f"""

Rate this email as exactly ONE:

High
Medium
Low

Respond with ONLY the urgency level.

Email:

{email_text}

"""

    return ask_ai(
        prompt
    )


# ============================================================
# GENERATE REPLY
# ============================================================

def generate_reply(
    email_text,
    sender_name
):

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

    return ask_ai(
        prompt
    )


# ============================================================
# SEND EMAIL USING GMAIL SMTP (App Password)
# ============================================================

def send_email_real(

    to_address,

    subject,

    body

):

    try:

        print(

            f"📤 Sending reply to {to_address} using Gmail SMTP..."

        )

        message = MIMEText(body)

        message["From"] = GMAIL_ADDRESS

        message["To"] = to_address

        message["Subject"] = f"Re: {subject}"

        with smtplib.SMTP(

            SMTP_HOST,

            SMTP_PORT,

            timeout=30

        ) as server:

            server.starttls()

            server.login(

                GMAIL_ADDRESS,

                GMAIL_APP_PASSWORD

            )

            server.sendmail(

                GMAIL_ADDRESS,

                [to_address],

                message.as_string()

            )

        print(

            f"✅ REPLY SENT SUCCESSFULLY TO {to_address}"

        )

        logging.info(

            f"Gmail SMTP email sent successfully to {to_address}"

        )

        return True

    except Exception as e:

        logging.exception(

            "❌ GMAIL SMTP SEND FAILED"

        )

        print(

            f"❌ GMAIL SMTP SEND FAILED: {e}"

        )

        return False


# ============================================================
# MARK EMAIL AS SEEN
# ============================================================

def mark_as_seen(
    uid
):

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


# ============================================================
# PROCESS ONE EMAIL
# ============================================================

def process_one_email():

    email_data = fetch_latest_unread_email()

    if email_data is None:

        print(

            "📭 No new unread emails."

        )

        return False


    print()

    print(

        "=" * 60

    )

    print(

        "📩 NEW EMAIL FOUND"

    )

    print(

        "=" * 60

    )


    print(

        f"From: {email_data['sender_name']} "

        f"<{email_data['sender_email']}>"

    )

    print(

        f"Subject: {email_data['subject']}"

    )


    sender_email = (

        email_data["sender_email"]

    )


    # --------------------------------------------------------
    # SKIP AUTOMATED EMAILS
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # SKIP SELF-SENT EMAILS
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # CLASSIFY EMAIL
    # --------------------------------------------------------

    print(

        "🏷️ Classifying email..."

    )

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


    # --------------------------------------------------------
    # DETECT URGENCY
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # GENERATE REPLY
    # --------------------------------------------------------

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


    print()

    print(

        "🤖 GENERATED REPLY:"

    )

    print(

        "-" * 60

    )

    print(

        reply

    )

    print(

        "-" * 60

    )


    # --------------------------------------------------------
    # SEND REPLY
    # --------------------------------------------------------

    sent = send_email_real(

        email_data["sender_email"],

        email_data["subject"],

        reply

    )


    if sent:

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


# ============================================================
# MAIN LOOP
# ============================================================

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

                "❌ UNEXPECTED ERROR IN MAIN LOOP"

            )

            print(

                f"❌ Unexpected error: {e}"

            )

        time.sleep(

            CHECK_INTERVAL_SECONDS

        )


# ============================================================
# LOCAL EXECUTION
# ============================================================

if __name__ == "__main__":

    run_forever()
