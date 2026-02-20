import logging
from celery import shared_task
from django.conf import settings
from twilio.rest import Client
from apps.standup.models import StandupEntry

logger = logging.getLogger(__name__)

MORNING_CHECKIN_MESSAGE = (
    "Good morning! ☀️ Time for your daily standup.\n\n"
    "Please reply with your update:\n"
    "- What did you work on yesterday?\n"
    "- What are you working on today?\n"
    "- Any blockers?"
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
