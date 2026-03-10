import logging
import subprocess

import requests
from celery import shared_task
from django.conf import settings
from twilio.rest import Client

logger = logging.getLogger(__name__)

import os as _os
_BASE = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

MONITORING_COLLECTOR_PROMPT = open(
    _os.path.join(_BASE, "agents", "monitoring-collector.md")
).read()

MONITORING_DECISION_PROMPT = open(
    _os.path.join(_BASE, "agents", "monitoring-decision.md")
).read()


@shared_task
def run_monitoring_agent():
    """
    Runs the monitoring agent via Claude Code CLI.
    Triggered daily at 8:00 AM UTC (before the morning digest).
    """
    try:
        collector_result = subprocess.run(
            ["claude", "-p", MONITORING_COLLECTOR_PROMPT, "--allowedTools", "Bash,WebFetch,Read", "--model", "claude-haiku-4-5-20251001"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        DECISION_PROMPT = MONITORING_DECISION_PROMPT + "\n\n## Health Check Data\n" + collector_result.stdout

        result = subprocess.run(
            ["claude", "-p", DECISION_PROMPT, "--model","claude-sonnet-4-6"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error("Monitoring agent failed: %s", result.stderr)
        else:
            logger.info("Monitoring agent completed: %s", result.stdout[:200])
    except subprocess.TimeoutExpired:
        logger.error("Monitoring agent timed out")
    except Exception as exc:
        logger.error("Monitoring agent error: %s", exc)
