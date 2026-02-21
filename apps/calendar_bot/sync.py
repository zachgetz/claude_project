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

    # Delete any existing channels for this user before registering a new one
    CalendarWatchChannel.objects.filter(phone_number=phone_number).delete()

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
        logger.exception('Failed to register watch channel for %s: %s', phone_number, exc)
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

    logger.info('Registered watch channel %s for %s (expires %s)', channel_id_str, phone_number, expiry_dt)
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
        return

    user_tz = get_user_tz(phone_number)
    now_local = datetime.datetime.now(tz=user_tz)
    today = now_local.date()
    tomorrow = today + datetime.timedelta(days=1)

    client = Client(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN,
    )
    from_number = settings.TWILIO_WHATSAPP_NUMBER

    for change in changes:
        change_type = change.get('type')
        event_id = change.get('event_id')
        title = change.get('title', '(No title)')
        title = title[:60]  # cap title length

        # Determine the relevant datetime for the change (new_start or old_start)
        relevant_dt_utc = change.get('new_start') or change.get('old_start')
        if relevant_dt_utc is None:
            continue

        # Convert to user's local timezone
        if relevant_dt_utc.tzinfo is None:
            relevant_dt_utc = pytz.UTC.localize(relevant_dt_utc)
        event_local = relevant_dt_utc.astimezone(user_tz)
        event_date = event_local.date()

        # Only notify for today or tomorrow
        if event_date not in (today, tomorrow):
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
            continue

        try:
            client.messages.create(
                from_=from_number,
                to=phone_number,
                body=message,
            )
            logger.info(
                'Change alert sent to %s: %s event_id=%s',
                phone_number, change_type, event_id,
            )
        except Exception as exc:
            logger.exception(
                'Failed to send change alert to %s for event %s: %s',
                phone_number, event_id, exc,
            )
