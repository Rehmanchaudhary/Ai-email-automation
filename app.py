import threading

from flask import Flask

from src.email_automation import run_forever


app = Flask(__name__)


@app.route("/")
def health_check():

    return (
        "AI Email Automation is running.",
        200
    )


def start_background_loop():

    run_forever()


automation_thread = threading.Thread(
    target=start_background_loop,
    daemon=True
)

automation_thread.start()