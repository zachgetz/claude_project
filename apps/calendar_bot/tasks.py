import datetime
import logging

import pytz
from celery import shared_task
from django.conf import settings
from twilio.rest import Client

from .models import CalendarToken, CalendarWatchChannel
from .calendar_service import get_calendar_service, get_user_tz

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_morning_meetings_digest(self):
    """
    Send each connected user their meetings for today via WhatsApp.
    Registered in django-celery-beat at 08:00 UTC daily by default.
    """
    client = Client(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN,
    )
    from_number = settings.TWILIO_WHATSAPP_NUMBER

    for token in CalendarToken.objects.all():
        phone_number = token.phone_number
        try:
            _send_digest_for_user(client, from_number, phone_number)
        except Exception as exc:
            logger.exception('Error sending morning digest to %s: %s', phone_number, exc)
            try:
                raise self.retry(exc=exc)
            except Exception:
                pass


def _send_digest_for_user(client, from_number, phone_number):
    user_tz = get_user_tz(phone_number)
    today = datetime.datetime.now(tz=user_tz).date()

    try:
        service = get_calendar_service(phone_number)
    except Exception as exc:
        logger.warning('Could not get calendar service for %s: %s', phone_number, exc)
        return

    # Build timezone-aware start/end
    day_start = user_tz.localize(datetime.datetime(today.year, today.month, today.day, 0, 0, 0))
    day_end = user_tz.localize(datetime.datetime(today.year, today.month, today.day, 23, 59, 59))

    try:
        events_result = service.events().list(
            calendarId='primary',
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy='startTime',
        ).execute()
    except Exception as exc:
        logger.warning('Calendar API error for %s: %s', phone_number, exc)
        return

    items = events_result.get('items', [])

    if not items:
        message = 'Good morning! No meetings today \U0001f389'
    else:
        lines = ['Good morning! Your meetings today:']
        for item in items:
            start_raw = item.get('start', {})
            if 'dateTime' in start_raw:
                start_dt = datetime.datetime.fromisoformat(start_raw['dateTime'])
                if start_dt.tzinfo is None:
                    start_dt = pytz.UTC.localize(start_dt)
                start_local = start_dt.astimezone(user_tz)
                time_str = start_local.strftime('%H:%M')
            else:
                time_str = 'All day'
            summary = item.get('summary', '(No title)')
            lines.append(f'{time_str} {summary}')
        message = '\n'.join(lines)

    client.messages.create(
        from_=from_number,
        to=phone_number,
        body=message,
    )
    logger.info('Morning digest sent to %s (%d events)', phone_number, len(items))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def renew_watch_channels(self):
    """
    Runs daily. Finds CalendarWatchChannel records expiring within 24 hours
    and renews them by calling register_watch_channel().
    """
    from .sync import register_watch_channel

    now = datetime.datetime.now(tz=pytz.UTC)
    expiry_threshold = now + datetime.timedelta(hours=24)

    expiring_channels = CalendarWatchChannel.objects.filter(
        expiry__lt=expiry_threshold
    )

    for channel in expiring_channels:
        phone_number = channel.phone_number
        try:
            # register_watch_channel deletes old channels and creates a new one
            register_watch_channel(phone_number)
            logger.info('Renewed watch channel for %s', phone_number)
        except Exception as exc:
            logger.exception('Failed to renew watch channel for %s: %s', phone_number, exc)
            try:
                raise self.retry(exc=exc)
            except Exception:
                pass
