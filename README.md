<div align="center">
  <img src="static/images/logo.jpg" alt="MailPing logo" width="120">

  <h1>MailPing</h1>

  <p><strong>Gmail-to-WhatsApp alerts for people who do not want to live inside their inbox.</strong></p>

  <p>
    <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"></a>
    <a href="https://flask.palletsprojects.com/"><img src="https://img.shields.io/badge/Flask-Web_App-000000?style=for-the-badge&logo=flask&logoColor=white" alt="Flask"></a>
    <a href="https://developers.google.com/gmail/api"><img src="https://img.shields.io/badge/Gmail-Readonly_E-mail-EA4335?style=for-the-badge&logo=gmail&logoColor=white" alt="Gmail"></a>
    <a href="https://www.twilio.com/docs/whatsapp"><img src="https://img.shields.io/badge/Twilio-WhatsApp_Alerts-F22F46?style=for-the-badge&logo=twilio&logoColor=white" alt="Twilio"></a>
  </p>
</div>

---

MailPing connects a user's Gmail inbox to their own Twilio WhatsApp setup. Once Gmail is connected and Twilio details are saved, MailPing watches quietly in the background and sends a WhatsApp ping when a new email arrives.

## Highlights

| Feature | What it does |
| --- | --- |
| User accounts | Each person signs up and manages their own alert settings. |
| Gmail OAuth | Connects Gmail with readonly inbox access. |
| WhatsApp alerts | Sends message details through Twilio WhatsApp. |
| Per-user Twilio setup | Users provide their own Account SID, Auth Token, sender, and WhatsApp number. |
| Test alerts | Lets users verify WhatsApp delivery before enabling monitoring. |
| Activity dashboard | Shows setup status, last check time, latest alert status, subject, and Twilio SID. |
| Deploy-ready | Works locally with SQLite and can run on Render with PostgreSQL. |

## How It Works

```text
Gmail inbox
    |
    | readonly OAuth connection
    v
MailPing watcher
    |
    | checks for latest message
    v
Twilio WhatsApp
    |
    | sends alert
    v
Your phone
```

MailPing stores Gmail OAuth tokens and Twilio credentials per user. The app checks enabled accounts on a configurable interval and only sends an alert when the latest Gmail message changes.

## Tech Stack

- **Backend:** Flask, SQLAlchemy, Gunicorn
- **Database:** SQLite locally, PostgreSQL in production
- **Auth:** Local account login with hashed passwords
- **Gmail:** Google OAuth + Gmail API readonly scope
- **Messaging:** Twilio WhatsApp API
- **Deployment:** Render-compatible `Procfile`

## Local Setup

### 1. Create a virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create your environment file

```bash
copy .env.example .env
```

Update `.env` with your Google OAuth credentials:

```env
SECRET_KEY=replace-with-a-long-random-secret
DATABASE_URL=sqlite:///mailping.db
GOOGLE_CLIENT_ID=your-google-oauth-client-id
GOOGLE_CLIENT_SECRET=your-google-oauth-client-secret
CHECK_INTERVAL_SECONDS=60
DISABLE_WATCHER=0
```

For local Google OAuth testing, add this redirect URI in Google Cloud:

```text
http://127.0.0.1:5000/oauth2callback
```

### 4. Initialize the database

```bash
flask --app app init-db
```

### 5. Run the app

```bash
flask --app app run
```

Open:

```text
http://127.0.0.1:5000
```

## User Setup Flow

After creating an account, each user should:

1. Connect Gmail from the dashboard.
2. Add their Twilio Account SID and Auth Token.
3. Add a Twilio WhatsApp sender, usually:

```text
whatsapp:+14155238886
```

4. Add their own WhatsApp number, for example:

```text
+919876543210
```

5. Send a test alert.
6. Enable email monitoring.

Twilio WhatsApp sandbox guide: [twilio.com/docs/whatsapp/sandbox](https://www.twilio.com/docs/whatsapp/sandbox)

## Render Deployment

Create a Python web service and use this start command:

```bash
gunicorn app:app
```

Add these environment variables in Render:

```env
SECRET_KEY=replace-with-a-long-random-secret
DATABASE_URL=your-render-postgres-url
GOOGLE_CLIENT_ID=your-google-oauth-client-id
GOOGLE_CLIENT_SECRET=your-google-oauth-client-secret
CHECK_INTERVAL_SECONDS=60
DISABLE_WATCHER=0
```

Then add your production redirect URI in Google Cloud:

```text
https://your-render-app.onrender.com/oauth2callback
```

> Do not put personal Twilio credentials in Render environment variables. MailPing asks every user for their own Twilio details inside the dashboard.

## Security Notes

- Gmail access uses the readonly scope only.
- Passwords are stored as hashes, not plain text.
- Twilio credentials are user-specific and should be treated as secrets.
- Use a strong `SECRET_KEY` in production.
- Use HTTPS in production so OAuth callbacks and session cookies are protected.

## Project Structure

```text
MailPing/
|-- app.py                 # Flask app, models, routes, watcher, integrations
|-- requirements.txt       # Python dependencies
|-- Procfile               # Render/Gunicorn start command
|-- templates/             # Flask templates
|-- static/                # Styles and images
|-- .env.example           # Example environment variables
`-- README.md              # Project guide
```

## License

This project is licensed under the terms in [LICENSE](LICENSE).
