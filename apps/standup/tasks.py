import logging
import datetime
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from twilio.rest import Client
from apps.standup.models import StandupEntry

logger = logging.getLogger(__name__)

MORNING_CHECKIN_MESSAGE = (
    "Good morning! \u2600\ufe0f Time for your daily standup.\n\n"
    "Please reply with your update:\n"
    "- What did you work on yesterday?\n"
    "- What are you working on today?\n"
    "- Any blockers?"
)

EVENING_NO_ENTRIES_MESSAGE = (
    "Hey! \u{1F31D} Looks like you haven't submitted a standup today. "
    "Don't forget to log your update!"
)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_morning_checkin(self):
    """
    Celery task: send a morning check-in WhatsApp prompt to every unique
    phone number that has ever submitted a standup entry.

    Retries up to 3 times (60 s apart) on transient Twilio errors.
    """
    phone_numbers = (
        StandupEntry.objects.values_list('phone_number', flat=True)
        .distinct()
    )

    if not phone_numbers:
        logger.info('send_morning_checkin: no phone numbers found, skipping.')
        return

    client = Client(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN,
    )
    from_number = settings.TWILIO_WHATSAPP_NUMBER

    success_count = 0
    error_count = 0

    for number in phone_numbers:
        try:
            client.messages.create(
                from_=from_number,
                to=number,
                body=MORNING_CHECKIN_MESSAGE,
            )
            logger.info('Morning check-in sent to %s', number)
            success_count += 1
        except Exception as exc:  # noqa: BLE001
            logger.error(
                'Failed to send morning check-in to %s: %s', number, exc
            )
            error_count += 1

    logger.info(
        'send_morning_checkin complete: %d sent, %d failed.',
        success_count,
        error_count,
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_evening_digest(self):
    """
    Celery task: send each user an evening digest of their standup entries
    for the current day.

    - If a user submitted entries today, they receive a summary.
    - If a user has no entries today (but has historic entries), they receive
      a gentle reminder.
    - Retries up to 3 times (60 s apart) on transient Twilio errors.
    """
    today = timezone.now().date()

    # All phone numbers that have EVER submitted an entry
    all_numbers = list(
        StandupEntry.objects.values_list('phone_number', flat=True)
        .distinct()
    )

    if not all_numbers:
        logger.info('send_evening_digest: no phone numbers found, skipping.')
        return

    # Entries submitted today, keyed by phone number
    todays_entries = (
        StandupEntry.objects.filter(created_at__date=today)
        .order_by('phone_number', 'created_at')
    )
    entries_by_number = {}
    for entry in todays_entries:
        entries_by_number.setdefault(entry.phone_number, []).append(entry)

    client = Client(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN,
    )
    from_number = settings.TWILIO_WHATSAPP_NUMBER

    success_count = 0
    error_count = 0

    for number in all_numbers:
        entries = entries_by_number.get(number)
        if entries:
            lines = [f"\U0001f4cb Your standup digest for {today}:\n"]
            for i, entry in enumerate(entries, start=1):
                time_str = entry.created_at.strftime('%H:%M')
                lines.append(f"{i}. [{time_str}] {entry.message}")
            message_body = "\n".join(lines)
        else:
            message_body = (
                f"\U0001f31d Hey! No standup entry recorded today ({today}). "
                "Make sure to log your update — reply here anytime!"
            )

        try:
            client.messages.create(
                from_=from_number,
                to=number,
                body=message_body,
            )
            logger.info('Evening digest sent to %s', number)
            success_count += 1
        except Exception as exc:  # noqa: BLE001
            logger.error(
                'Failed to send evening digest to %s: %s', number, exc
            )
            error_count += 1

    logger.info(
        'send_evening_digest complete: %d sent, %d failed.',
        success_count,
        error_count,
    )
