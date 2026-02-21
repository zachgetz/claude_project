import datetime
import logging
from collections import defaultdict

import pytz
from celery import shared_task
from django.conf import settings
from twilio.rest import Client

from .models import CalendarToken, CalendarWatchChannel
from .calendar_service import get_events_for_date, get_user_tz
from .sync import register_watch_channel

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_morning_meetings_digest(self):
    """
    Send each connected user their meetings for today via WhatsApp.
    Groups tokens by phone_number and sends ONE merged digest per phone.
    Respects per-user digest_enabled, digest_hour/minute (from the first/primary token).
    Registered in django-celery-beat -- runs every minute; per-user time check is inside.
    """
    logger.info('send_morning_meetings_digest task started')

    try:
        all_tokens = list(CalendarToken.objects.filter(digest_enabled=True).order_by('phone_number', 'created_at'))
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

    # Group tokens by phone; first token in list is primary (earliest created_at)
    phone_to_tokens = defaultdict(list)
    for token in all_tokens:
        phone_to_tokens[token.phone_number].append(token)

    logger.info(
        'send_morning_meetings_digest: processing %d phone(s)',
        len(phone_to_tokens),
    )

    processed = 0
    skipped = 0

    for phone_number, tokens in phone_to_tokens.items():
        primary_token = tokens[0]  # earliest token = primary for timing/settings
        try:
            # Check if it's the configured digest time (in user's TZ)
            user_tz = get_user_tz(phone_number)
            now_local = now_utc.astimezone(user_tz)
            if (now_local.hour != primary_token.digest_hour or
                    now_local.minute != primary_token.digest_minute):
                skipped += 1
                continue

            logger.info(
                'Sending digest to phone=%s (digest_time=%02d:%02d)',
                phone_number,
                primary_token.digest_hour,
                primary_token.digest_minute,
            )
            _send_digest_for_phone(client, from_number, phone_number, primary_token)
            processed += 1
        except Exception:
            logger.exception('Error sending morning digest to phone=%s', phone_number)

    logger.info(
        'send_morning_meetings_digest task complete: processed=%d skipped=%d',
        processed,
        skipped,
    )


def _send_digest_for_phone(client, from_number, phone_number, primary_token):
    """
    Send a merged morning digest for all connected accounts of the given phone.
    Uses get_events_for_date which already loops all tokens and merges events.
    """
    user_tz = get_user_tz(phone_number)
    today = datetime.datetime.now(tz=user_tz).date()

    logger.info('_send_digest_for_phone: phone=%s date=%s', phone_number, today)

    try:
        items = get_events_for_date(phone_number, today)
    except Exception as exc:
        logger.warning('Could not get events for phone=%s date=%s: %s', phone_number, today, exc)
        return

    logger.info(
        '_send_digest_for_phone: phone=%s date=%s events_found=%d',
        phone_number,
        today,
        len(items),
    )

    # Build name part safely (token.name may not exist yet -- TZA-92 adds it)
    user_name = getattr(primary_token, 'name', '') or ''
    name_part = f' {user_name}' if user_name else ''

    # Skip if no meetings and user hasn't opted into always-send
    if not items and not primary_token.digest_always:
        logger.info(
            'No meetings for phone=%s date=%s -- skipping digest (digest_always=False)',
            phone_number,
            today,
        )
        return

    if not items:
        message = f'\u2600\ufe0f \u1e'  # placeholder rebuilt below
        message = '\u2600\ufe0f \u05d1\u05d5\u05e7\u05e8 \u05d8\u05d5\u05d1' + name_part + '! \U0001f31f\n\n\U0001f389 \u05d0\u05d9\u05df \u05e4\u05d2\u05d9\u05e9\u05d5\u05ea \u05d4\u05d9\u05d5\u05dd \u2014 \u05ea\u05d4\u05e0\u05d4!'
    else:
        # Count timed events (those with an actual start time, not all-day)
        timed_count = sum(1 for ev in items if ev.get('start_str', 'All day') != 'All day')

        # Opening greeting
        greeting = f'\u2600\ufe0f \u05d1\u05d5\u05e7\u05e8 \u05d8\u05d5\u05d1' + name_part + '! \u05de\u05e7\u05d5\u05d5\u05d4 \u05e9\u05d4\u05d9\u05d5\u05dd \u05d9\u05d4\u05d9\u05d4 \u05de\u05d3\u05d4\u05d9\u05dd \U0001f31f\n\n'

        lines = [greeting + '\u05d4\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea \u05e9\u05dc\u05da \u05d4\u05d9\u05d5\u05dd:']
        for ev in items:
            time_str = ev.get('start_str', 'All day')
            summary = ev.get('summary', '(No title)')
            lines.append(f'{time_str} {summary}')

        # Closing line based on timed meeting count
        if timed_count == 0:
            closing = '\n\n\U0001f389 \u05d0\u05d9\u05df \u05e4\u05d2\u05d9\u05e9\u05d5\u05ea \u05d4\u05d9\u05d5\u05dd \u2014 \u05ea\u05d4\u05e0\u05d4!'
        elif timed_count <= 4:
            closing = '\n\n\u2728 \u05d9\u05d5\u05dd \u05e4\u05e8\u05d5\u05d3\u05d5\u05e7\u05d8\u05d9\u05d1\u05d9 \u05dc\u05e4\u05e0\u05d9\u05da!'
        elif timed_count <= 6:
            closing = '\n\n\U0001f4aa \u05d9\u05d5\u05dd \u05e2\u05de\u05d5\u05e1 \u2014 \u05ea\u05d6\u05db\u05d5\u05e8 \u05dc\u05e0\u05e9\u05d5\u05dd \u05d1\u05d9\u05df \u05e4\u05d2\u05d9\u05e9\u05d5\u05ea \U0001f9d8'
        else:
            closing = '\n\n\U0001f525 \u05de\u05e8\u05ea\u05d5\u05df \u05e4\u05d2\u05d9\u05e9\u05d5\u05ea \u05d4\u05d9\u05d5\u05dd! \u05e9\u05de\u05d5\u05e8 \u05e2\u05dc \u05e2\u05e6\u05de\u05da'

        message = '\n'.join(lines) + closing

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
    and renews them by calling register_watch_channel(token).
    Skips NULL-token channels (legacy/orphaned).
    """
    logger.info('renew_watch_channels task started')

    now = datetime.datetime.now(tz=pytz.UTC)
    expiry_threshold = now + datetime.timedelta(hours=24)

    # Only renew channels that have a valid token FK
    expiring_channels = CalendarWatchChannel.objects.select_related('token').filter(
        expiry__lt=expiry_threshold,
        token__isnull=False,
    )

    channel_count = expiring_channels.count()
    logger.info(
        'renew_watch_channels: found %d channel(s) expiring within 24h (with token)',
        channel_count,
    )

    renewed = 0
    failed = 0

    for channel in expiring_channels:
        token = channel.token
        try:
            register_watch_channel(token)
            renewed += 1
            logger.info(
                'Renewed watch channel for phone=%s email=%s',
                token.phone_number,
                token.account_email,
            )
        except Exception as exc:
            failed += 1
            logger.exception(
                'Failed to renew watch channel for phone=%s email=%s: %s',
                token.phone_number,
                token.account_email,
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
