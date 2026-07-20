# AI Email Automation

An AI-powered email assistant that reads incoming emails from a real Gmail inbox, classifies their intent, detects urgency, and generates a professional reply — automatically, using a free open-source LLM.

## What it does

1. Connects to a Gmail inbox via IMAP
2. Detects new unread emails (ignores anything already in the inbox before it starts)
3. Classifies each email into a category: Order Issue, Complaint, General Inquiry, Support Request, or Spam/Irrelevant
4. Rates the email's urgency: High, Medium, or Low
5. Generates a short, professional reply addressed to the sender by name
6. Sends the reply automatically via Gmail SMTP
7. Skips automated senders (no-reply addresses, mailer-daemons) and self-sent emails to avoid reply loops
8. Logs every action to `automation.log`

## Tech stack

- **Python**
- **Groq API** — running Meta's Llama 3.1 8B Instant model, free tier, no local hardware requirements
- **IMAP / SMTP** (via `imapclient` and Python's built-in `smtplib`/`email`) for real Gmail integration
- **python-dotenv** for keeping API keys and credentials out of source control

## Try it yourself (live demo)

This project's automation is genuinely running — send a test email to:

**abdulrehmanrauf5551@gmail.com**

Try something:

Within about 60 seconds (while the script is actively running), you should receive an AI-generated reply — classified by category and urgency, and written specifically in response to your message.

**Note:** This only works while the automation is actively running on my machine. If you don't get a reply, the script may not be running at that moment — feel free to reach out and I can start it up for a live demo.
