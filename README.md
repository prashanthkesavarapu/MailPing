# MailPing

MailPing watches a connected Gmail inbox and sends a WhatsApp alert through the signed-in user's own Twilio account.

## What users need

Each user creates an account, connects Gmail, and enters their own Twilio WhatsApp settings from the dashboard:

- Twilio Account SID
- Twilio Auth Token
- Twilio WhatsApp sender, usually `whatsapp:+14155238886` for the Twilio sandbox
- Their own WhatsApp number, such as `+919876543210`

Twilio WhatsApp sandbox setup guide: https://www.twilio.com/docs/whatsapp/sandbox

## Local setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
flask --app app init-db
flask --app app run
```

Set these values in `.env` before connecting Gmail:

```env
SECRET_KEY=replace-with-a-long-random-secret
GOOGLE_CLIENT_ID=your-google-oauth-client-id
GOOGLE_CLIENT_SECRET=your-google-oauth-client-secret
```

For local Google OAuth testing, add this redirect URI in Google Cloud:

```text
http://127.0.0.1:5000/oauth2callback
```

## Render deployment

Use a Python web service with this start command:

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
```

In Google Cloud, add your Render redirect URI:

```text
https://your-render-app.onrender.com/oauth2callback
```

Do not add Twilio credentials to Render. MailPing asks every user for their own Twilio SID and Auth Token inside the dashboard.
