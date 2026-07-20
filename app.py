import threading
from flask import Flask
from src.email_automation import run_forever

app = Flask(__name__)

@app.route("/")
def health_check():
    return "AI Email Automation is running.", 200

def start_background_loop():
    """Runs the email-checking loop forever in a background thread."""
    run_forever()

automation_thread = threading.Thread(target=start_background_loop, daemon=True)
automation_thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)