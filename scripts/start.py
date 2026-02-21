#!/usr/bin/env python
"""Railway deployment entry point.

Routes to the correct process based on SERVICE_TYPE environment variable:
  - "worker"  -> Celery worker
  - "beat"    -> Celery beat scheduler
  - (default) -> Django migrate + Gunicorn web server
"""
import os
import subprocess
import sys


def main():
    service_type = os.environ.get("SERVICE_TYPE", "")

    if service_type == "worker":
        print("Starting Celery worker...", flush=True)
        os.execvp(
            "celery",
            ["celery", "-A", "standup_bot", "worker", "--loglevel=info", "--concurrency=2"],
        )

    elif service_type == "beat":
        print("Starting Celery beat...", flush=True)
        os.execvp(
            "celery",
            [
                "celery", "-A", "standup_bot",
                "beat", "--loglevel=info",
                "--scheduler", "django_celery_beat.schedulers:DatabaseScheduler",
            ],
        )

    else:
        print("Starting web server...", flush=True)
        subprocess.run(
            [sys.executable, "manage.py", "migrate", "--noinput"],
            check=True,
        )
        port = os.environ.get("PORT", "8000")
        os.execvp(
            "gunicorn",
            [
                "gunicorn",
                "standup_bot.wsgi:application",
                "--bind", f"0.0.0.0:{port}",
                "--workers", "2",
                "--log-file", "-",
            ],
        )


if __name__ == "__main__":
    main()
