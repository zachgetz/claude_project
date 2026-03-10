# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Memory File
Located at: `/Users/tzachgetz/Projects/claude_project/.claude/memory/MEMORY.md`
Always read this file at the start of every session before doing anything else.

---

## Commands

```bash
# Run all standup tests
python manage.py test apps.standup.tests

# Run all calendar_bot tests
python manage.py test apps.calendar_bot.tests

# Run a single test file
python manage.py test apps.standup.tests.test_webhook_view

# Apply migrations
python manage.py migrate

# Dev server (SQLite, DEBUG=True)
DJANGO_SETTINGS_MODULE=standup_bot.settings.dev python manage.py runserver

# Celery worker
celery -A standup_bot worker --loglevel=info

# Celery beat (scheduler)
celery -A standup_bot beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

Python binary: `/Users/tzachgetz/.pyenv/versions/3.11.1/bin/python`

---

## Architecture

This is a **Django + Twilio WhatsApp bot** backed by Google Calendar. Users interact entirely via WhatsApp messages. There is no frontend.

### Request Flow

Every incoming WhatsApp message hits `POST /standup/webhook/` → `WhatsAppWebhookView` (`apps/standup/views.py`). The view is a **state machine** driven by `UserMenuState` (stored in DB). States:

- No state → root handler → show main menu or onboarding
- `main_menu` → digit 1–6 routes to submenus
- `meetings_menu`, `free_time_menu`, `birthdays_menu`, `settings_menu`, `timezone_menu`, `disconnect_confirm`, `digest_prompt`, `name_prompt` → submenu handlers
- `schedule` → 7-step multi-turn flow (date → start time → end time → title → description → location → confirm)

All bot response strings are **Hebrew**, defined in `apps/standup/strings_he.py`. Do not hardcode Hebrew in views.

### Apps

| App | Purpose |
|---|---|
| `apps/standup` | Core webhook handler, StandupEntry model, Celery tasks (morning check-in, evening digest, purge), Hebrew strings |
| `apps/calendar_bot` | Google Calendar OAuth2, CalendarToken model, push notification webhook, calendar queries, event scheduling, multi-account support |
| `apps/bot` | Legacy routing only (`apps/bot/urls.py` → `apps/bot/views.py`) |

### Key Files

- `apps/standup/views.py` — entire state machine + all menu logic (900 lines)
- `apps/standup/strings_he.py` — all Hebrew UI strings
- `apps/calendar_bot/calendar_service.py` — Google Calendar API calls, token refresh, event creation, snapshot sync
- `apps/calendar_bot/models.py` — `CalendarToken`, `UserMenuState`, `OnboardingState`, `CalendarWatchChannel`
- `apps/calendar_bot/sync.py` — Google Calendar push notification registration + change detection
- `apps/calendar_bot/query_helpers.py` — formatting helpers for event/free-time display
- `standup_bot/settings/dev.py` — SQLite, DEBUG=True
- `standup_bot/settings/prod.py` — Postgres, DEBUG=False

### Celery Tasks

Scheduled via `django-celery-beat` (tasks seeded by migrations):
- `send_morning_checkin` — morning prompt to all users
- `send_evening_digest` — evening summary
- `purge_old_standup_entries` — nightly cleanup

### Google Calendar Integration

OAuth2 flow: `GET /calendar/auth/start/` → Google consent → `GET /calendar/auth/callback/` → stores `CalendarToken`.

Push notifications: Google pings `POST /calendar/notifications/` → `CalendarNotificationsView` → `sync_calendar_snapshot()` → `send_change_alerts()`.

`CalendarToken` supports **multi-account** (one phone → many tokens, one per `account_email`). Queries iterate all tokens for a phone number.

---

## Agents & Automation

### Subagents (`.claude/agents/`)
| Agent | Trigger |
|---|---|
| `programmer.md` | `/implement TZA-X` or "work on this ticket" |
| `pm-agent.md` | `/next-phase` or "break into tickets" |
| `qa-agent.md` | `/review-pr` or "run QA" |
| `idea-creator.md` | "give me an idea" |
| `ux-agent.md` | "write the copy for this" |
| `translator-agent.md` | "translate to Hebrew" |

### Skills (`.claude/skills/`)
- `/after-merge TZA-X` — mark Linear ticket Done post-merge
- `/next-phase` — promote next phase of tickets from Backlog → Todo
- `/assign-to-project` — assign Linear tickets to a project
- `/review-pr [PR-number]` — code review agent

### Monitoring Agents (`agents/`)
Self-healing pipeline (manual trigger):
1. `monitoring-collector.md` (Haiku) → outputs JSON health status
2. `monitoring-decision.md` (Sonnet) → decides if alert needed
3. `monitoring-diagnosis.md` (Sonnet) → opens Linear ticket
4. `health-bug-fixer.md` (Sonnet/Opus) → fixes, merges, marks Done

### MCP Servers (`mcp_servers/`)
- `mcp_railway.py` — Railway tools: `get_recent_logs`, `get_env_vars`, `redeploy_service`
- Railway CLI path: `/Users/tzachgetz/.nvm/versions/node/v18.20.8/bin/railway`

---

## Deployment

- Platform: Railway (project `intelligent-growth`, service `claude_project`)
- Entry point: `scripts/start.py` (see `railway.toml`)
- Uses Postgres (prod) and Redis (Celery broker) as Railway plugins
- `DJANGO_SETTINGS_MODULE=standup_bot.settings.prod` in Railway env vars
