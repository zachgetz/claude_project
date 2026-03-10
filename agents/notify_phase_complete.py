#!/usr/bin/env python3
"""
Sends an email notification when all tickets in a phase are In Review.

Usage:
  python3 agents/notify_phase_complete.py --phase 1 --tickets "TZA-6,TZA-7,TZA-8" --prs "https://github.com/.../pull/2,https://github.com/.../pull/3,https://github.com/.../pull/4"
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


def send_phase_complete_email(phase: int, tickets: list[str], prs: list[str]):
    subject = f"✅ Phase {phase} Complete — All Tickets In Review"

    ticket_lines = ""
    for i, (ticket, pr) in enumerate(zip(tickets, prs), 1):
        ticket_lines += f"  {i}. {ticket} → {pr}\n"

    body = f"""Hey 👋,

Phase {phase} is complete! All tickets are implemented and in review.

PRs ready for your review:
{ticket_lines}
Merge them when you're ready, then run /after-merge for each ticket followed by /next-phase to kick off Phase {phase + 1}.

— Programmer Agent
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

    print(f"✓ Email sent to {RECIPIENT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--tickets", type=str, required=True, help="Comma-separated ticket IDs")
    parser.add_argument("--prs", type=str, required=True, help="Comma-separated PR URLs")
    args = parser.parse_args()

    tickets = [t.strip() for t in args.tickets.split(",")]
    prs = [p.strip() for p in args.prs.split(",")]

    send_phase_complete_email(args.phase, tickets, prs)
