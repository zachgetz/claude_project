# WhatsApp Daily Standup Bot

A Django + Twilio bot for daily standups via WhatsApp.
Users send their standup update to a WhatsApp number powered by Twilio;
the bot stores the entry, replies with a confirmation, and delivers a
morning check-in prompt and an evening digest automatically via Celery.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Clone the repo](#clone-the-repo)
3. [Python environment](#python-environment)
4. [Environment variables](#environment-variables)
5. [Database setup](#database-setup)
6. [Run the dev server](#run-the-dev-server)
7. [Run Celery worker and beat](#run-celery-worker-and-beat)
8. [Expose webhook via ngrok](#expose-webhook-via-ngrok)
9. [Run tests](#run-tests)
10. [Project structure](#project-structure)
11. [Deployment (Railway)](#deployment-railway)

---

## Prerequisites

| Tool | Minimum version | Notes |
|---|---|---|
| Python | 3.11 | `python --version` |
| Redis | 7.x | Used as Celery broker |
| ngrok | any | Required for Twilio webhook in local dev |
| Twilio account | — | Free trial is enough for sandbox testing |

---

## Clone the repo

```bash
git clone https://github.com/zachgetz/claude_project.git
cd claude_project
```

---

## Python environment

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## Environment variables

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
# Django
SECRET_KEY=replace-with-a-long-random-string
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886   # Twilio sandbox number

# Redis (broker for Celery)
REDIS_URL=redis://localhost:6379/0

# Timezone for Celery scheduled tasks
TIME_ZONE=UTC
```

> Never commit `.env` — it is listed in `.gitignore`.

---

## Database setup

```bash
# Apply all migrations (creates SQLite db.sqlite3 by default)
python manage.py migrate

# Optional: seed Celery-beat periodic tasks (also run automatically by migration 0002/0003)
python manage.py setup_periodic_tasks

# Create a superuser to access the Django admin
python manage.py createsuperuser
```

The admin panel is at `http://localhost:8000/admin/`.

---

## Run the dev server

```bash
python manage.py runserver
```

The app listens on `http://localhost:8000`.

---

## Run Celery worker and beat

Open two additional terminal tabs (with the virtual environment activated):

**Terminal 2 — Celery worker**

```bash
celery -A standup_bot worker --loglevel=info
```

**Terminal 3 — Celery beat (task scheduler)**

```bash
celery -A standup_bot beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

Make sure Redis is running before starting either process:

```bash
redis-server          # or: brew services start redis
```

---

## Expose webhook via ngrok

Twilio needs a public URL to send incoming WhatsApp messages to your local server.

```bash
ngrok http 8000
```

Copy the HTTPS forwarding URL (e.g. `https://abc123.ngrok.io`) and configure it in the
[Twilio Console](https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn):

- **Sandbox configuration > When a message comes in:**
  `https://abc123.ngrok.io/standup/webhook/`  (HTTP method: POST)

Send a message from your WhatsApp to the sandbox number to test.

---

## Run tests

```bash
python manage.py test apps.standup.tests
```

The test suite covers:
- `WhatsAppWebhookView` — entry creation, `/summary` command, validation, permission enforcement
- `send_morning_checkin` — Twilio calls mocked, skips when no entries
- `send_evening_digest` — digest vs. reminder branching, per-user isolation
- `purge_old_standup_entries` — retention-day logic, configurable via `STANDUP_RETENTION_DAYS`

---

## Project structure

```
claude_project/
├── apps/
│   ├── bot/                   # WhatsApp bot app (webhook routing)
│   └── standup/               # Core standup logic
│       ├── migrations/        # DB migrations (incl. celery-beat task seeding)
│       ├── management/
│       │   └── commands/
│       │       └── setup_periodic_tasks.py
│       ├── tests/
│       │   ├── test_webhook_view.py
│       │   └── test_tasks.py
│       ├── models.py          # StandupEntry model
│       ├── views.py           # WhatsAppWebhookView
│       ├── tasks.py           # Celery tasks
│       ├── permissions.py     # TwilioSignaturePermission
│       └── urls.py
├── standup_bot/               # Django project settings
│   ├── celery.py
│   ├── settings.py
│   └── urls.py
├── .env.example
├── Procfile                   # Process types for Railway / Heroku
├── railway.toml               # Railway deployment config
├── requirements.txt
└── manage.py
```

---

## Deployment (Railway)

1. Push the repo to GitHub.
2. Create a new Railway project and connect the GitHub repo.
3. Set all environment variables from `.env.example` in the Railway dashboard
   (use a production `SECRET_KEY`, `DEBUG=False`, and your live Twilio credentials).
4. Railway will detect the `Procfile` and start the `web` process automatically.
5. Add a **Redis** plugin in Railway and copy the `REDIS_URL` it provides into your env vars.
6. For `worker` and `beat`, create two additional Railway services pointing at the same repo
   with custom start commands:
   - Worker: `celery -A standup_bot worker --loglevel=info --concurrency=2`
   - Beat: `celery -A standup_bot beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler`
7. Point your Twilio WhatsApp webhook URL at the Railway web service domain:
   `https://<your-service>.railway.app/standup/webhook/`
