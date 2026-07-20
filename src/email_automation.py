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

# ----- SETUP -----
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


# ----- STARTUP: IGNORE OLD EMAILS -----
def mark_existing_unread_as_seen():
    try:
        with IMAPClient(IMAP_HOST) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.select_folder("INBOX", readonly=False)

            existing_unseen = server.search(["UNSEEN"])
            if existing_unseen:
                server.add_flags(existing_unseen, [b"\\Seen"])
                print(f"🧹 Ignored {len(existing_unseen)} pre-existing unread email(s). Only new emails from now on will be processed.")
                logging.info(f"Marked {len(existing_unseen)} pre-existing unread emails as seen (ignored).")
            else:
                print("🧹 No pre-existing unread emails found.")

    except Exception as e:
        logging.error(f"Failed during startup cleanup: {e}")
        print(f"Error during startup cleanup: {e}")


# ----- FETCH REAL EMAIL -----
def fetch_latest_unread_email():
    try:
        with IMAPClient(IMAP_HOST) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.select_folder("INBOX", readonly=False)

            messages = server.search(["UNSEEN"])
            if not messages:
                return None

            latest_uid = messages[-1]
            raw_message = server.fetch([latest_uid], ["RFC822"])[latest_uid][b"RFC822"]
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
                    disposition = str(part.get("Content-Disposition"))
                    if content_type == "text/plain" and "attachment" not in disposition:
                        charset = part.get_content_charset() or "utf-8"
                        body = part.get_payload(decode=True).decode(charset, errors="replace")
                        break
            else:
                charset = msg.get_content_charset() or "utf-8"
                body = msg.get_payload(decode=True).decode(charset, errors="replace")

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
        logging.error(f"Failed to fetch email: {e}")
        print(f"Error fetching email: {e}")
        return None


# ----- FILTERS -----
def is_automated_sender(sender_email):
    automated_patterns = ["no-reply", "noreply", "donotreply", "notifications", "mailer-daemon"]
    sender_lower = sender_email.lower()
    return any(pattern in sender_lower for pattern in automated_patterns)


def is_self_sent(sender_email):
    return sender_email.lower() == GMAIL_ADDRESS.lower()


# ----- AI FUNCTIONS -----
def ask_ai(prompt):
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"AI request failed: {e}")
        print(f"Error talking to the AI: {e}")
        return None


def classify_email(email_text):
    prompt = f"""Classify the following email into exactly ONE of these categories:
- Order Issue
- Complaint
- General Inquiry
- Support Request
- Spam/Irrelevant

Respond with ONLY the category name, nothing else.

Email:
{email_text}

Category:"""
    return ask_ai(prompt)


def detect_urgency(email_text):
    prompt = f"""Read the following email and rate its urgency as exactly ONE of these:
- High
- Medium
- Low

Respond with ONLY the urgency level, nothing else.

Email:
{email_text}

Urgency:"""
    return ask_ai(prompt)


def generate_reply(email_text, sender_name):
    prompt = f"""You are a professional email assistant. Read the following email and write a short, professional reply.

The sender's name is: {sender_name}
Address them by this name in the greeting (e.g. "Dear {sender_name},").
Sign off as:
Best regards,
{YOUR_NAME}

Do not use any placeholder like [Your Name] — always sign with the exact name "{YOUR_NAME}".

Email:
{email_text}

Reply:"""
    return ask_ai(prompt)


# ----- SEND -----
def send_email_real(to_address, subject, body):
    try:
        msg = MIMEMultipart()
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = to_address
        msg["Subject"] = f"Re: {subject}"
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, to_address, msg.as_string())

        logging.info(f"Email auto-sent to {to_address}")
        print("\n✅ Email sent successfully.")

    except Exception as e:
        logging.error(f"Failed to send email: {e}")
        print(f"\n❌ Failed to send: {e}")


# ----- PROCESS ONE EMAIL -----
def process_one_email():
    email_data = fetch_latest_unread_email()
    if email_data is None:
        return False

    if is_automated_sender(email_data["sender_email"]):
        print(f"\n⏭️  Skipping automated sender: {email_data['sender_email']}")
        logging.info(f"Skipped automated sender: {email_data['sender_email']}")
        return True

    if is_self_sent(email_data["sender_email"]):
        print(f"\n⏭️  Skipping self-sent email to avoid a reply loop: {email_data['sender_email']}")
        logging.info("Skipped self-sent email to avoid reply loop.")
        return True

    print("\n" + "=" * 50)
    print("----- NEW EMAIL FOUND -----")
    print(f"From: {email_data['sender_name']} <{email_data['sender_email']}>")
    print(f"Subject: {email_data['subject']}")
    print(email_data["body"])

    category = classify_email(email_data["body"])
    if category is None:
        return False
    print(f"\n----- CATEGORY -----\n{category}")
    logging.info(f"Classified as: {category}")

    urgency = detect_urgency(email_data["body"])
    if urgency is None:
        return False
    print(f"\n----- URGENCY -----\n{urgency}")
    logging.info(f"Urgency: {urgency}")

    reply = generate_reply(email_data["body"], email_data["sender_name"])
    if reply is None:
        return False

    print(f"\n----- AUTO-REPLY -----\n{reply}")
    send_email_real(email_data["sender_email"], email_data["subject"], reply)
    return True


# ----- MAIN LOOP -----
def run_forever():
    print(f"📬 AI Email Automation is starting up...")
    mark_existing_unread_as_seen()
    print(f"Now checking for NEW emails every {CHECK_INTERVAL_SECONDS} seconds.")
    print("Auto-send mode: replies go out immediately, no review step.")
    print("Press Ctrl+C to stop.\n")
    logging.info("Automation started (auto-send mode, ignoring pre-existing unread emails).")

    while True:
        try:
            processed = process_one_email()
            if not processed:
                print(f"No new unread emails. Checking again in {CHECK_INTERVAL_SECONDS} seconds...")
        except KeyboardInterrupt:
            print("\n\n🛑 Stopped by user.")
            logging.info("Automation stopped by user.")
            break
        except Exception as e:
            logging.error(f"Unexpected error in main loop: {e}")
            print(f"Unexpected error: {e}")
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    run_forever()