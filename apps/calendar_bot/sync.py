import datetime
import logging

import pytz
from django.conf import settings
from twilio.rest import Client

from .calendar_service import get_calendar_service, sync_calendar_snapshot, get_user_tz
from .models import CalendarWatchChannel

logger = logging.getLogger(__name__)


def register_watch_channel(phone_number):
    """
    Calls events.watch() on Google Calendar API.
    Uses WEBHOOK_BASE_URL setting + '/calendar/notifications/' as the address.
    Stores channel_id, resource_id, expiry in CalendarWatchChannel.
    Returns the new CalendarWatchChannel instance.
    """
    from .models import CalendarWatchChannel

    logger.info('register_watch_channel called: phone=%s', phone_number)

    # Delete any existing channels for this user before registering a new one
    deleted_count, _ = CalendarWatchChannel.objects.filter(phone_number=phone_number).delete()
    if deleted_count:
        logger.info(
            'Deleted %d existing watch channel(s) for phone=%s before re-registering',
            deleted_count,
            phone_number,
        )

    service = get_calendar_service(phone_number)

    webhook_base_url = getattr(settings, 'WEBHOOK_BASE_URL', 'https://localhost')
    notification_url = webhook_base_url.rstrip('/') + '/calendar/notifications/'

    # Create a new channel
    new_channel = CalendarWatchChannel(phone_number=phone_number)
    new_channel.save()  # saves to get channel_id UUID assigned

    channel_id_str = str(new_channel.channel_id)

    try:
        watch_response = service.events().watch(
            calendarId='primary',
            body={
                'id': channel_id_str,
                'type': 'web_hook',
                'address': notification_url,
            },
        ).execute()
    except Exception as exc:
        logger.exception(
            'Failed to register watch channel for phone=%s channel_id=%s: %s',
            phone_number,
            channel_id_str,
            exc,
        )
        new_channel.delete()
        raise

    resource_id = watch_response.get('resourceId', '')
    expiry_ms = watch_response.get('expiration')
    expiry_dt = None
    if expiry_ms:
        expiry_dt = datetime.datetime.fromtimestamp(int(expiry_ms) / 1000, tz=pytz.UTC)

    new_channel.resource_id = resource_id
    new_channel.expiry = expiry_dt
    new_channel.save()

    logger.info(
        'Registered watch channel: phone=%s channel_id=%s expiry=%s',
        phone_number,
        channel_id_str,
        expiry_dt,
    )
    return new_channel


def send_change_alerts(phone_number, changes):
    """
    Takes list of changes from sync_calendar_snapshot().
    Only alerts for events today or tomorrow (ignores next-week events).
    Debounce: skip if same event_id was alerted less than 5 minutes ago
    (checks CalendarEventSnapshot.updated_at).
    Sends alerts via Twilio WhatsApp.
    """
    if not changes:
        logger.info('send_change_alerts: no changes to report for phone=%s', phone_number)
        return

    logger.info(
        'send_change_alerts called: phone=%s total_changes=%d',
        phone_number,
        len(changes),
    )

    user_tz = get_user_tz(phone_number)
    now_local = datetime.datetime.now(tz=user_tz)
    today = now_local.date()
    tomorrow = today + datetime.timedelta(days=1)

    client = Client(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN,
    )
    from_number = settings.TWILIO_WHATSAPP_NUMBER

    alerts_sent = 0
    alerts_skipped = 0

    for change in changes:
        change_type = change.get('type')
        event_id = change.get('event_id')
        title = change.get('title', '(No title)')
        title = title[:60]  # cap title length

        # Determine the relevant datetime for the change (new_start or old_start)
        relevant_dt_utc = change.get('new_start') or change.get('old_start')
        if relevant_dt_utc is None:
            logger.warning(
                'send_change_alerts: skipping change with no start time: '
                'phone=%s event_id=%s type=%s',
                phone_number,
                event_id,
                change_type,
            )
            continue

        # Convert to user's local timezone
        if relevant_dt_utc.tzinfo is None:
            relevant_dt_utc = pytz.UTC.localize(relevant_dt_utc)
        event_local = relevant_dt_utc.astimezone(user_tz)
        event_date = event_local.date()

        # Only notify for today or tomorrow
        if event_date not in (today, tomorrow):
            logger.info(
                'send_change_alerts: skipping event not today/tomorrow: '
                'phone=%s event_id=%s event_date=%s',
                phone_number,
                event_id,
                event_date,
            )
            alerts_skipped += 1
            continue

        # Determine relative day label
        if event_date == today:
            day_label = 'today'
        else:
            day_label = 'tomorrow'

        time_str = event_local.strftime('%H:%M')

        # Build message
        if change_type == 'rescheduled':
            old_start_utc = change.get('old_start')
            if old_start_utc is None:
                logger.warning(
                    'send_change_alerts: rescheduled change missing old_start: '
                    'phone=%s event_id=%s',
                    phone_number,
                    event_id,
                )
                continue
            if old_start_utc.tzinfo is None:
                old_start_utc = pytz.UTC.localize(old_start_utc)
            old_local = old_start_utc.astimezone(user_tz)
            old_time_str = old_local.strftime('%H:%M')
            message = (
                f'\U0001f4c5 Meeting rescheduled:\n'
                f'"{title}" moved from {old_time_str} to {time_str} {day_label}'
            )
        elif change_type == 'cancelled':
            message = (
                f'\u274c Meeting cancelled:\n'
                f'"{title}" at {time_str} {day_label} was removed'
            )
        elif change_type == 'new':
            message = (
                f'\U0001f4ec New meeting added:\n'
                f'"{title}" at {time_str} {day_label}'
            )
        else:
            logger.warning(
                'send_change_alerts: unknown change type %r for phone=%s event_id=%s',
                change_type,
                phone_number,
                event_id,
            )
            continue

        try:
            client.messages.create(
                from_=from_number,
                to=phone_number,
                body=message,
            )
            alerts_sent += 1
            logger.info(
                'Change alert sent: phone=%s type=%s event_id=%s',
                phone_number,
                change_type,
                event_id,
            )
        except Exception as exc:
            logger.exception(
                'Failed to send change alert: phone=%s event_id=%s type=%s: %s',
                phone_number,
                event_id,
                change_type,
                exc,
            )

    logger.info(
        'send_change_alerts complete: phone=%s alerts_sent=%d alerts_skipped=%d',
        phone_number,
        alerts_sent,
        alerts_skipped,
    )
