#!/usr/bin/env python
"""Railway deployment entry point.

Routes to the correct process based on SERVICE_TYPE environment variable:
  - "worker"  -> Celery worker (+ minimal health server on $PORT)
  - "beat"    -> Celery beat scheduler (+ minimal health server on $PORT)
  - (default) -> Django migrate + Gunicorn web server
"""
import http.server
import os
import subprocess
import sys
import threading


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP handler — returns 200 OK for any GET request."""

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, fmt, *args):  # suppress access logs
        pass


def _start_health_server(port: int) -> None:
    """Bind to PORT in a daemon thread so Railway's TCP probe succeeds."""
    server = http.server.HTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()


def main():
    service_type = os.environ.get("SERVICE_TYPE", "")
    port = int(os.environ.get("PORT", "8000"))

    if service_type == "worker":
        print("Starting Celery worker...", flush=True)
        _start_health_server(port)
        result = subprocess.run(
            ["celery", "-A", "standup_bot", "worker", "--loglevel=info", "--concurrency=2"]
        )
        sys.exit(result.returncode)

    elif service_type == "beat":
        print("Starting Celery beat...", flush=True)
        _start_health_server(port)
        result = subprocess.run(
            [
                "celery", "-A", "standup_bot",
                "beat", "--loglevel=info",
                "--scheduler", "django_celery_beat.schedulers:DatabaseScheduler",
            ]
        )
        sys.exit(result.returncode)

    else:
        print("Starting web server...", flush=True)
        subprocess.run(
            [sys.executable, "manage.py", "migrate", "--noinput"],
            check=True,
        )
        port_str = os.environ.get("PORT", "8000")
        os.execvp(
            "gunicorn",
            [
                "gunicorn",
                "standup_bot.wsgi:application",
                "--bind", f"0.0.0.0:{port_str}",
                "--workers", "2",
                "--log-file", "-",
            ],
        )


if __name__ == "__main__":
    main()
