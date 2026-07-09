import json
import os
import threading
import time
from datetime import datetime, timezone
from email.utils import parseaddr
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy import inspect, text
from twilio.rest import Client
from werkzeug.security import check_password_hash, generate_password_hash


load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))
TWILIO_HELP_URL = "https://www.twilio.com/docs/whatsapp/sandbox"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-change-me")

database_url = os.getenv("DATABASE_URL", "sqlite:///mailping.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.debug = os.getenv("FLASK_DEBUG", "0") == "1"

db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    whatsapp_number = db.Column(db.String(32))
    twilio_account_sid = db.Column(db.String(255))
    twilio_auth_token = db.Column(db.String(255))
    twilio_whatsapp_from = db.Column(db.String(50), default="whatsapp:+14155238886")

    gmail_token_json = db.Column(db.Text)
    last_message_id = db.Column(db.String(255))
    monitoring_enabled = db.Column(db.Boolean, default=False, nullable=False)

    last_checked_at = db.Column(db.DateTime)
    last_alert_at = db.Column(db.DateTime)
    last_alert_status = db.Column(db.String(64))
    last_alert_error = db.Column(db.String(255))
    last_alert_subject = db.Column(db.String(255))
    last_twilio_sid = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def google_client_config():
    raw_config = os.getenv("GOOGLE_CLIENT_CONFIG_JSON")
    if raw_config:
        return json.loads(raw_config)

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("Google OAuth credentials are missing.")

    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [url_for("oauth_callback", _external=True)],
        }
    }


def google_flow(state=None):
    return Flow.from_client_config(
        google_client_config(),
        scopes=SCOPES,
        state=state,
        redirect_uri=url_for("oauth_callback", _external=True),
    )


def user_credentials(user):
    if not user.gmail_token_json:
        return None

    creds = Credentials.from_authorized_user_info(
        json.loads(user.gmail_token_json),
        SCOPES,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        user.gmail_token_json = creds.to_json()
        db.session.commit()
    return creds


def latest_gmail_message(user):
    creds = user_credentials(user)
    if not creds:
        return None

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    results = service.users().messages().list(userId="me", maxResults=1).execute()
    messages = results.get("messages", [])
    if not messages:
        return None

    message_id = messages[0]["id"]
    message = service.users().messages().get(userId="me", id=message_id).execute()
    headers = {
        header["name"].lower(): header["value"]
        for header in message.get("payload", {}).get("headers", [])
    }

    return {
        "id": message_id,
        "sender": headers.get("from", "Unknown sender"),
        "subject": headers.get("subject", "(No subject)"),
        "date": headers.get("date", ""),
        "snippet": message.get("snippet", ""),
    }


def short_text(value, limit=180):
    value = " ".join((value or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def normalize_whatsapp_number(value):
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("whatsapp:"):
        return value
    return f"whatsapp:{value}"


def format_email_alert(email_message):
    sender_name, sender_email = parseaddr(email_message["sender"])
    sender = sender_name or sender_email or email_message["sender"]
    subject = short_text(email_message["subject"], 120)
    snippet = short_text(email_message.get("snippet"), 180)

    lines = ["MailPing: new email", "", f"From: {sender}"]
    if sender_email and sender_email != sender:
        lines.append(f"Email: {sender_email}")
    lines.extend([f"Subject: {subject}", f"Date: {email_message.get('date', '')}"])
    if snippet:
        lines.extend(["", snippet])
    return "\n".join(lines)


def validate_twilio_settings(user):
    missing = []
    if not user.twilio_account_sid:
        missing.append("Twilio Account SID")
    if not user.twilio_auth_token:
        missing.append("Twilio Auth Token")
    if not user.twilio_whatsapp_from:
        missing.append("Twilio WhatsApp sender")
    if not user.whatsapp_number:
        missing.append("your WhatsApp number")
    if missing:
        raise RuntimeError("Add " + ", ".join(missing) + " before sending alerts.")


def send_whatsapp_alert(user, email_message):
    validate_twilio_settings(user)
    client = Client(user.twilio_account_sid, user.twilio_auth_token)
    return client.messages.create(
        from_=normalize_whatsapp_number(user.twilio_whatsapp_from),
        to=normalize_whatsapp_number(user.whatsapp_number),
        body=format_email_alert(email_message),
    )


def fetch_twilio_message(user, message_sid):
    client = Client(user.twilio_account_sid, user.twilio_auth_token)
    return client.messages(message_sid).fetch()


def record_alert_result(user, email_message, twilio_message=None, error=None):
    user.last_alert_at = datetime.now(timezone.utc)
    user.last_alert_subject = short_text(email_message.get("subject"), 255)
    user.last_twilio_sid = getattr(twilio_message, "sid", None)
    user.last_alert_status = getattr(twilio_message, "status", None) or "failed"
    user.last_alert_error = short_text(str(error), 255) if error else None


def send_and_record_alert(user, email_message, delivery_wait_seconds=3):
    twilio_message = send_whatsapp_alert(user, email_message)
    if delivery_wait_seconds:
        time.sleep(delivery_wait_seconds)
        twilio_message = fetch_twilio_message(user, twilio_message.sid)
    record_alert_result(user, email_message, twilio_message)
    return twilio_message


def watcher_loop():
    with app.app_context():
        while True:
            users = User.query.filter_by(monitoring_enabled=True).all()
            for user in users:
                try:
                    message = latest_gmail_message(user)
                    user.last_checked_at = datetime.now(timezone.utc)
                    if not message:
                        db.session.commit()
                        continue

                    if user.last_message_id is None:
                        user.last_message_id = message["id"]
                    elif message["id"] != user.last_message_id:
                        try:
                            send_and_record_alert(user, message)
                        except Exception as exc:
                            record_alert_result(user, message, error=exc)
                            app.logger.exception("Alert failed for user %s", user.id)
                        user.last_message_id = message["id"]

                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    app.logger.exception("Watcher failed for user %s", user.id)

            time.sleep(CHECK_INTERVAL_SECONDS)


def twilio_ready(user):
    return bool(
        user.twilio_account_sid
        and user.twilio_auth_token
        and user.twilio_whatsapp_from
        and user.whatsapp_number
    )


@app.route("/")
def index():
    if current_user():
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if len(password) < 8:
            flash("Use a password with at least 8 characters.", "danger")
            return redirect(url_for("register"))

        if User.query.filter_by(email=email).first():
            flash("An account already exists for that email.", "danger")
            return redirect(url_for("register"))

        user = User(email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        session["user_id"] = user.id
        flash("Account created. Connect Gmail and add your Twilio details.", "success")
        return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()

        if not user or not user.check_password(password):
            flash("Invalid email or password.", "danger")
            return redirect(url_for("login"))

        session["user_id"] = user.id
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    gmail_connected = bool(user.gmail_token_json)
    ready_for_alerts = gmail_connected and twilio_ready(user)
    return render_template(
        "dashboard.html",
        user=user,
        gmail_connected=gmail_connected,
        ready_for_alerts=ready_for_alerts,
        twilio_ready=twilio_ready(user),
        check_interval=CHECK_INTERVAL_SECONDS,
        twilio_help_url=TWILIO_HELP_URL,
    )


@app.route("/settings", methods=["POST"])
@login_required
def settings():
    user = current_user()
    user.whatsapp_number = request.form["whatsapp_number"].strip()
    user.twilio_account_sid = request.form["twilio_account_sid"].strip()
    user.twilio_whatsapp_from = request.form["twilio_whatsapp_from"].strip()

    new_token = request.form["twilio_auth_token"].strip()
    if new_token:
        user.twilio_auth_token = new_token

    wants_monitoring = request.form.get("monitoring_enabled") == "on"
    user.monitoring_enabled = wants_monitoring and bool(user.gmail_token_json) and twilio_ready(user)

    db.session.commit()

    if wants_monitoring and not user.monitoring_enabled:
        flash("Saved, but monitoring needs Gmail and complete Twilio settings first.", "warning")
    else:
        flash("Settings saved.", "success")
    return redirect(url_for("dashboard"))


@app.route("/send-test-alert", methods=["POST"])
@login_required
def send_test_alert():
    user = current_user()
    test_message = {
        "sender": "MailPing <hello@mailping.local>",
        "subject": "Test WhatsApp alert",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "snippet": "Your Twilio WhatsApp setup is connected to MailPing.",
    }
    try:
        message = send_and_record_alert(user, test_message)
        db.session.commit()
    except Exception as exc:
        app.logger.exception("Test WhatsApp alert failed")
        record_alert_result(user, test_message, error=exc)
        db.session.commit()
        flash(f"WhatsApp test failed: {exc}", "danger")
        return redirect(url_for("dashboard"))

    if message.status == "failed":
        flash(f"Twilio rejected the message. Error code: {message.error_code}.", "danger")
    else:
        flash(f"WhatsApp test submitted. Twilio status: {message.status}.", "success")
    return redirect(url_for("dashboard"))


@app.route("/connect-gmail")
@login_required
def connect_gmail():
    try:
        flow = google_flow()
    except Exception as exc:
        app.logger.exception("Could not start Gmail OAuth")
        flash(f"Google OAuth is not configured yet: {exc}", "danger")
        return redirect(url_for("dashboard"))

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["oauth_state"] = state
    return redirect(authorization_url)


@app.route("/oauth2callback")
@login_required
def oauth_callback():
    state = session.get("oauth_state")
    try:
        flow = google_flow(state=state)
        flow.fetch_token(authorization_response=request.url)
    except Exception:
        app.logger.exception("Gmail OAuth callback failed")
        flash("Gmail connection failed. Check your Google OAuth settings.", "danger")
        return redirect(url_for("dashboard"))

    user = current_user()
    user.gmail_token_json = flow.credentials.to_json()
    user.last_message_id = None
    db.session.commit()

    flash("Gmail connected successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/disconnect-gmail", methods=["POST"])
@login_required
def disconnect_gmail():
    user = current_user()
    user.gmail_token_json = None
    user.last_message_id = None
    user.monitoring_enabled = False
    db.session.commit()
    flash("Gmail disconnected.", "success")
    return redirect(url_for("dashboard"))


@app.cli.command("init-db")
def init_db_command():
    db.create_all()
    ensure_schema()
    print("Database initialized.")


def ensure_schema():
    inspector = inspect(db.engine)
    if "user" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("user")}
    required_columns = {
        "whatsapp_number": "VARCHAR(32)",
        "twilio_account_sid": "VARCHAR(255)",
        "twilio_auth_token": "VARCHAR(255)",
        "twilio_whatsapp_from": "VARCHAR(50)",
        "gmail_token_json": "TEXT",
        "last_message_id": "VARCHAR(255)",
        "monitoring_enabled": "BOOLEAN DEFAULT 0 NOT NULL",
        "last_checked_at": "DATETIME",
        "last_alert_at": "DATETIME",
        "last_alert_status": "VARCHAR(64)",
        "last_alert_error": "VARCHAR(255)",
        "last_alert_subject": "VARCHAR(255)",
        "last_twilio_sid": "VARCHAR(64)",
        "created_at": "DATETIME",
    }

    with db.engine.begin() as connection:
        for column_name, column_type in required_columns.items():
            if column_name not in existing:
                connection.execute(text(f"ALTER TABLE user ADD COLUMN {column_name} {column_type}"))

        if "twilio_sid" in existing and "twilio_account_sid" in required_columns:
            connection.execute(
                text(
                    "UPDATE user SET twilio_account_sid = twilio_sid "
                    "WHERE twilio_account_sid IS NULL AND twilio_sid IS NOT NULL"
                )
            )


def start_watcher_once():
    if os.getenv("DISABLE_WATCHER", "0") == "1":
        return
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    thread = threading.Thread(target=watcher_loop, daemon=True)
    thread.start()


with app.app_context():
    db.create_all()
    ensure_schema()

start_watcher_once()


if __name__ == "__main__":
    app.run(debug=app.debug)
