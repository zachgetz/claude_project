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
    Respects per-user digest_enabled, digest_hour/minute (in user TZ), and digest_always.
    Registered in django-celery-beat — runs every minute; per-user time check is inside.
    Per-user errors are logged and skipped; self.retry() is only for infrastructure failures.
    """
    logger.info('send_morning_meetings_digest task started')

    try:
        tokens = list(CalendarToken.objects.filter(digest_enabled=True))
    except Exception as exc:
        logger.exception('Failed to query CalendarToken table: %s', exc)
        raise self.retry(exc=exc)

    try:
        client = Client(
            settings.TWILIO_ACCOUNT_SID,
            settings.TWILIO_AUTH_TOKEN,
        )
    except Exception as exc:
        logger.exception('Failed to initialise Twilio client: %s', exc)
        raise self.retry(exc=exc)

    from_number = settings.TWILIO_WHATSAPP_NUMBER
    now_utc = datetime.datetime.now(tz=pytz.UTC)

    logger.info(
        'send_morning_meetings_digest: processing %d eligible user(s)',
        len(tokens),
    )

    processed = 0
    skipped = 0

    for token in tokens:
        phone_number = token.phone_number
        try:
            # Check if it's now the user's configured digest time (within the current minute)
            user_tz = get_user_tz(phone_number)
            now_local = now_utc.astimezone(user_tz)
            if now_local.hour != token.digest_hour or now_local.minute != token.digest_minute:
                skipped += 1
                continue

            logger.info(
                'Sending digest to phone=%s (digest_time=%02d:%02d)',
                phone_number,
                token.digest_hour,
                token.digest_minute,
            )
            _send_digest_for_user(client, from_number, token)
            processed += 1
        except Exception:
            # Log and continue — do NOT retry whole task for single-user failure
            logger.exception('Error sending morning digest to phone=%s', phone_number)

    logger.info(
        'send_morning_meetings_digest task complete: processed=%d skipped=%d',
        processed,
        skipped,
    )


def _send_digest_for_user(client, from_number, token):
    phone_number = token.phone_number
    user_tz = get_user_tz(phone_number)
    today = datetime.datetime.now(tz=user_tz).date()

    logger.info('_send_digest_for_user: phone=%s date=%s', phone_number, today)

    try:
        service = get_calendar_service(phone_number)
    except Exception as exc:
        logger.warning('Could not get calendar service for phone=%s: %s', phone_number, exc)
        return

    # Build timezone-aware start/end
    day_start = datetime.datetime(today.year, today.month, today.day, 0, 0, 0).astimezone(user_tz)
    day_end = datetime.datetime(today.year, today.month, today.day, 23, 59, 59).astimezone(user_tz)

    try:
        events_result = service.events().list(
            calendarId='primary',
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True,
            orderBy='startTime',
        ).execute()
    except Exception as exc:
        logger.warning('Calendar API error for phone=%s: %s', phone_number, exc)
        return

    items = events_result.get('items', [])

    logger.info(
        '_send_digest_for_user: phone=%s date=%s events_found=%d',
        phone_number,
        today,
        len(items),
    )

    # Skip if no meetings and user hasn't opted into always-send
    if not items and not token.digest_always:
        logger.info(
            'No meetings for phone=%s date=%s — skipping digest (digest_always=False)',
            phone_number,
            today,
        )
        return

    if not items:
        message = 'Good morning! No meetings today \U0001f389'
    else:
        lines = ['Good morning! Your meetings today:']
        for item in items:
            start_raw = item.get('start', {})
            if 'dateTime' in start_raw:
                start_dt = datetime.datetime.fromisoformat(start_raw['dateTime'])
                if start_dt.tzinfo is None:
                    start_dt = start_dt.astimezone(pytz.UTC)
                start_local = start_dt.astimezone(user_tz)
                time_str = start_local.strftime('%H:%M')
            else:
                time_str = 'All day'
            summary = item.get('summary', '(No title)')
            lines.append(f'{time_str} {summary}')
        message = '\n'.join(lines)

    try:
        client.messages.create(
            from_=from_number,
            to=phone_number,
            body=message,
        )
        logger.info(
            'Morning digest sent: phone=%s date=%s events=%d',
            phone_number,
            today,
            len(items),
        )
    except Exception as exc:
        logger.exception(
            'Failed to send morning digest to phone=%s: %s',
            phone_number,
            exc,
        )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def renew_watch_channels(self):
    """
    Runs daily. Finds CalendarWatchChannel records expiring within 24 hours
    and renews them by calling register_watch_channel().
    """
    from .sync import register_watch_channel

    logger.info('renew_watch_channels task started')

    now = datetime.datetime.now(tz=pytz.UTC)
    expiry_threshold = now + datetime.timedelta(hours=24)

    expiring_channels = CalendarWatchChannel.objects.filter(
        expiry__lt=expiry_threshold
    )

    channel_count = expiring_channels.count()
    logger.info(
        'renew_watch_channels: found %d channel(s) expiring within 24h',
        channel_count,
    )

    renewed = 0
    failed = 0

    for channel in expiring_channels:
        phone_number = channel.phone_number
        try:
            # register_watch_channel deletes old channels and creates a new one
            register_watch_channel(phone_number)
            renewed += 1
            logger.info('Renewed watch channel for phone=%s', phone_number)
        except Exception as exc:
            failed += 1
            logger.exception(
                'Failed to renew watch channel for phone=%s: %s',
                phone_number,
                exc,
            )
            try:
                raise self.retry(exc=exc)
            except Exception:
                pass

    logger.info(
        'renew_watch_channels task complete: renewed=%d failed=%d',
        renewed,
        failed,
    )
