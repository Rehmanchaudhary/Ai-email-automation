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


# ============================================================
# SETUP
# ============================================================

load_dotenv()

logging.basicConfig(
    filename="automation.log",
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

# This Gmail label permanently tracks emails already handled.
PROCESSED_LABEL = "AI_AUTOMATION_PROCESSED"


# ============================================================
# GMAIL LABEL SETUP
# ============================================================

def ensure_processed_label(server):
    """
    Makes sure the Gmail label used to track processed emails exists.
    """
    try:
        folders = server.list_folders()
        folder_names = [folder[2] for folder in folders]

        if PROCESSED_LABEL not in folder_names:
            server.create_folder(PROCESSED_LABEL)
            print(f"Created Gmail label: {PROCESSED_LABEL}")
            logging.info(f"Created Gmail label: {PROCESSED_LABEL}")

    except Exception as e:
        # The label may already exist under a slightly different Gmail
        # folder representation. We do not stop the whole application.
        logging.warning(f"Could not create/check Gmail label: {e}")


# ============================================================
# ONE-TIME INITIALIZATION
# ============================================================

def initialize_existing_emails():
    """
    On the first run, mark all currently existing Inbox emails as processed.

    This prevents the automation from replying to old emails already in
    the inbox before the automation was deployed.

    After this first initialization, only future unprocessed emails
    will be handled.
    """

    try:
        with IMAPClient(IMAP_HOST) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.select_folder("INBOX", readonly=False)

            ensure_processed_label(server)

            # Search for all Inbox emails that do not have our processed label.
            unprocessed = server.search([
                "X-GM-RAW",
                f"in:inbox -label:{PROCESSED_LABEL}"
            ])

            if not unprocessed:
                print("No existing emails need initialization.")
                return

            print(
                f"Initializing {len(unprocessed)} existing email(s). "
                "These will not receive automatic replies."
            )

            server.add_gmail_labels(
                unprocessed,
                [PROCESSED_LABEL]
            )

            logging.info(
                f"Initialized {len(unprocessed)} existing emails as processed."
            )

            print(
                f"Initialized {len(unprocessed)} existing email(s). "
                "Future emails will be processed automatically."
            )

    except Exception as e:
        logging.error(f"Initialization failed: {e}")
        print(f"Initialization error: {e}")


# ============================================================
# FETCH NEW EMAIL
# ============================================================

def fetch_latest_unprocessed_email():
    """
    Finds the newest Inbox email that does not have the processed label.

    It does NOT depend on UNSEEN/read status.
    """

    try:
        with IMAPClient(IMAP_HOST) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.select_folder("INBOX", readonly=False)

            ensure_processed_label(server)

            messages = server.search([
                "X-GM-RAW",
                f"in:inbox -label:{PROCESSED_LABEL}"
            ])

            if not messages:
                return None

            # Process the newest matching email.
            latest_uid = messages[-1]

            # BODY.PEEK[] reads the email without marking it as read.
            fetched = server.fetch(
                [latest_uid],
                ["BODY.PEEK[]"]
            )

            message_data = fetched[latest_uid]

            raw_message = (
                message_data.get(b"BODY[]")
                or message_data.get(b"BODY.PEEK[]")
            )

            if raw_message is None:
                raise ValueError("Could not retrieve email body.")

            msg = email.message_from_bytes(raw_message)

            raw_from = msg.get("From", "")
            sender_name, sender_email = parseaddr(raw_from)

            if not sender_name:
                sender_name = sender_email.split("@")[0]

            subject = msg.get("Subject", "(no subject)")

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
                body = "(No plain text content found in this email)"

            return {
                "uid": latest_uid,
                "sender_name": sender_name,
                "sender_email": sender_email,
                "subject": subject,
                "body": body
            }

    except Exception as e:

        logging.error(
            f"Failed to fetch email: {e}"
        )

        print(
            f"Error fetching email: {e}"
        )

        return None


# ============================================================
# MARK EMAIL AS PROCESSED
# ============================================================

def mark_email_as_processed(uid):

    try:

        with IMAPClient(IMAP_HOST) as server:

            server.login(
                GMAIL_ADDRESS,
                GMAIL_APP_PASSWORD
            )

            server.select_folder(
                "INBOX",
                readonly=False
            )

            ensure_processed_label(server)

            server.add_gmail_labels(
                [uid],
                [PROCESSED_LABEL]
            )

            logging.info(
                f"Email UID {uid} marked as processed."
            )

    except Exception as e:

        logging.error(
            f"Failed to mark email as processed: {e}"
        )

        print(
            f"Failed to mark email as processed: {e}"
        )


# ============================================================
# FILTERS
# ============================================================

def is_automated_sender(sender_email):

    automated_patterns = [
        "no-reply",
        "noreply",
        "donotreply",
        "notifications",
        "mailer-daemon"
    ]

    sender_lower = sender_email.lower()

    return any(
        pattern in sender_lower
        for pattern in automated_patterns
    )


def is_self_sent(sender_email):

    return (
        sender_email.lower()
        == GMAIL_ADDRESS.lower()
    )


# ============================================================
# AI
# ============================================================

def ask_ai(prompt):

    try:

        response = client.chat.completions.create(

            model=MODEL,

            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        return (
            response
            .choices[0]
            .message
            .content
            .strip()
        )

    except Exception as e:

        logging.error(
            f"AI request failed: {e}"
        )

        print(
            f"Error talking to the AI: {e}"
        )

        return None


def classify_email(email_text):

    prompt = f"""
Classify the following email into exactly ONE of these categories:

- Order Issue
- Complaint
- General Inquiry
- Support Request
- Spam/Irrelevant

Respond with ONLY the category name.

Email:
{email_text}

Category:
"""

    return ask_ai(prompt)


def detect_urgency(email_text):

    prompt = f"""
Read the following email and rate its urgency as exactly ONE of these:

- High
- Medium
- Low

Respond with ONLY the urgency level.

Email:
{email_text}

Urgency:
"""

    return ask_ai(prompt)


def generate_reply(email_text, sender_name):

    prompt = f"""
You are a professional email assistant.

Read the following email and write a short, professional reply.

The sender's name is:
{sender_name}

Address them by this name in the greeting.

Sign off exactly as:

Best regards,
{YOUR_NAME}

Do not use placeholders such as [Your Name].

Email:
{email_text}

Reply:
"""

    return ask_ai(prompt)


# ============================================================
# SEND EMAIL
# ============================================================

def send_email_real(
    to_address,
    subject,
    body
):

    try:

        msg = MIMEMultipart()

        msg["From"] = GMAIL_ADDRESS
        msg["To"] = to_address
        msg["Subject"] = f"Re: {subject}"

        msg.attach(
            MIMEText(
                body,
                "plain"
            )
        )

        with smtplib.SMTP(
            SMTP_HOST,
            SMTP_PORT
        ) as server:

            server.starttls()

            server.login(
                GMAIL_ADDRESS,
                GMAIL_APP_PASSWORD
            )

            server.sendmail(
                GMAIL_ADDRESS,
                to_address,
                msg.as_string()
            )

        logging.info(
            f"Email auto-sent to {to_address}"
        )

        print(
            "\n✅ Email sent successfully."
        )

        return True

    except Exception as e:

        logging.error(
            f"Failed to send email: {e}"
        )

        print(
            f"\n❌ Failed to send: {e}"
        )

        return False


# ============================================================
# PROCESS ONE EMAIL
# ============================================================

def process_one_email():

    email_data = (
        fetch_latest_unprocessed_email()
    )

    if email_data is None:

        return False

    uid = email_data["uid"]
    sender_email = email_data["sender_email"]

    print("\n" + "=" * 60)

    print(
        "----- NEW EMAIL FOUND -----"
    )

    print(
        f"From: "
        f"{email_data['sender_name']} "
        f"<{sender_email}>"
    )

    print(
        f"Subject: "
        f"{email_data['subject']}"
    )

    print(
        email_data["body"]
    )

    # --------------------------------------------------------
    # AUTOMATED EMAIL
    # --------------------------------------------------------

    if is_automated_sender(sender_email):

        print(
            f"\n⏭️ Skipping automated sender: "
            f"{sender_email}"
        )

        logging.info(
            f"Skipped automated sender: "
            f"{sender_email}"
        )

        mark_email_as_processed(uid)

        return True

    # --------------------------------------------------------
    # SELF-SENT EMAIL
    # --------------------------------------------------------

    if is_self_sent(sender_email):

        print(
            "\n⏭️ Skipping self-sent email "
            "to avoid a reply loop."
        )

        logging.info(
            "Skipped self-sent email."
        )

        mark_email_as_processed(uid)

        return True

    # --------------------------------------------------------
    # CLASSIFY
    # --------------------------------------------------------

    category = classify_email(
        email_data["body"]
    )

    if category is None:

        return False

    print(
        f"\n----- CATEGORY -----\n"
        f"{category}"
    )

    logging.info(
        f"Classified as: {category}"
    )

    # --------------------------------------------------------
    # URGENCY
    # --------------------------------------------------------

    urgency = detect_urgency(
        email_data["body"]
    )

    if urgency is None:

        return False

    print(
        f"\n----- URGENCY -----\n"
        f"{urgency}"
    )

    logging.info(
        f"Urgency: {urgency}"
    )

    # --------------------------------------------------------
    # GENERATE REPLY
    # --------------------------------------------------------

    reply = generate_reply(
        email_data["body"],
        email_data["sender_name"]
    )

    if reply is None:

        return False

    print(
        f"\n----- AUTO-REPLY -----\n"
        f"{reply}"
    )

    # --------------------------------------------------------
    # SEND REPLY
    # --------------------------------------------------------

    sent_successfully = send_email_real(

        email_data["sender_email"],

        email_data["subject"],

        reply
    )

    # Only mark as processed after successful handling.
    # This prevents failed emails from being permanently skipped.

    if sent_successfully:

        mark_email_as_processed(uid)

        return True

    return False


# ============================================================
# MAIN LOOP
# ============================================================

def run_forever():

    print(
        "📬 AI Email Automation is starting up..."
    )

    # This only initializes old emails the first time.
    # Future emails are tracked using a persistent Gmail label.
    initialize_existing_emails()

    print(
        f"Now checking for NEW emails every "
        f"{CHECK_INTERVAL_SECONDS} seconds."
    )

    print(
        "Auto-send mode: replies go out immediately."
    )

    logging.info(
        "Automation started."
    )

    while True:

        try:

            processed = process_one_email()

            if not processed:

                print(
                    f"No new emails. "
                    f"Checking again in "
                    f"{CHECK_INTERVAL_SECONDS} seconds..."
                )

        except KeyboardInterrupt:

            print(
                "\n🛑 Automation stopped."
            )

            logging.info(
                "Automation stopped."
            )

            break

        except Exception as e:

            logging.error(
                f"Unexpected error: {e}"
            )

            print(
                f"Unexpected error: {e}"
            )

        time.sleep(
            CHECK_INTERVAL_SECONDS
        )


if __name__ == "__main__":

    run_forever()