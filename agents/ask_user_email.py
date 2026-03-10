#!/usr/bin/env python3
"""
Sends an email to the user when the programmer agent needs input.

Usage:
  python3 agents/ask_user_email.py --phase 2 --ticket "TZA-9" --question "The webhook URL format is unclear. I assumed X — is that correct?"
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


def send_question_email(phase: int, ticket: str, question: str, assumption: str = None):
    subject = f"❓ Programmer Agent needs input — {ticket} (Phase {phase})"

    body = f"""Hey 👋,

The programmer agent hit a question while working on {ticket} (Phase {phase}) and needs your input.

Question:
{question}
"""
    if assumption:
        body += f"""
Assumption made (agent will proceed with this unless you say otherwise):
{assumption}

Reply to this email or come back to Claude Code to override.
"""
    else:
        body += """
Please come back to Claude Code and answer so the agent can continue.
"""

    body += "\n— Programmer Agent\n"

    msg = MIMEMultipart()
    msg["From"] = SENDER
    msg["To"] = RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SENDER, APP_PASSWORD)
        server.sendmail(SENDER, RECIPIENT, msg.as_string())

    print(f"✓ Question email sent to {RECIPIENT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--ticket", type=str, required=True)
    parser.add_argument("--question", type=str, required=True)
    parser.add_argument("--assumption", type=str, default=None)
    args = parser.parse_args()

    send_question_email(args.phase, args.ticket, args.question, args.assumption)
