#!/usr/bin/env python3
"""
Sends a QA findings summary email to the user.

Usage:
  python3 agents/notify_qa_findings.py \
    --phase 7 \
    --critical 2 \
    --high 3 \
    --medium 4 \
    --low 1 \
    --tickets "TZA-40,TZA-41,TZA-42" \
    --summary "OAuth callback doesn't handle revoked tokens..."
"""
import argparse
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SENDER = "getz992@gmail.com"
APP_PASSWORD = "rmds eppp wfrw sadj"
RECIPIENT = "princesszohar2002@gmail.com"


def send_qa_findings_email(phase: int, critical: int, high: int, medium: int, low: int,
                            tickets: list[str], summary: str):
    total = critical + high + medium + low
    has_issues = total > 0

    if has_issues:
        subject = f"🔍 QA Review Complete — Phase {phase} ({total} issues found)"
    else:
        subject = f"✅ QA Review Complete — Phase {phase} (All checks passed)"

    severity_table = f"""
Severity breakdown:
  🔴 Critical : {critical}
  🟠 High     : {high}
  🟡 Medium   : {medium}
  🔵 Low      : {low}
  ─────────────────
  Total       : {total}
"""

    if has_issues:
        tickets_str = ", ".join(tickets) if tickets else "none"
        body = f"""Hey 👋,

QA review of Phase {phase} is complete. Here's what was found:
{severity_table}
Summary:
{summary}

Linear tickets created for the programmer agents:
{tickets_str}

The programmer agents can pick these up on their next pass.

— QA Agent
"""
    else:
        body = f"""Hey 👋,

QA review of Phase {phase} is complete.

✅ All checks passed — no issues found.

The code looks good and is ready for deployment testing.

— QA Agent
"""

    msg = MIMEMultipart()
    msg["From"] = SENDER
    msg["To"] = RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SENDER, APP_PASSWORD)
        server.sendmail(SENDER, RECIPIENT, msg.as_string())

    print(f"✓ QA findings email sent to {RECIPIENT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--critical", type=int, default=0)
    parser.add_argument("--high", type=int, default=0)
    parser.add_argument("--medium", type=int, default=0)
    parser.add_argument("--low", type=int, default=0)
    parser.add_argument("--tickets", type=str, default="", help="Comma-separated ticket IDs")
    parser.add_argument("--summary", type=str, default="No summary provided.")
    args = parser.parse_args()

    tickets = [t.strip() for t in args.tickets.split(",") if t.strip()]

    send_qa_findings_email(
        phase=args.phase,
        critical=args.critical,
        high=args.high,
        medium=args.medium,
        low=args.low,
        tickets=tickets,
        summary=args.summary,
    )
