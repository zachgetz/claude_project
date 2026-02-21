import datetime
import logging

import pytz
from django.conf import settings

from .calendar_service import get_calendar_service, sync_calendar_snapshot
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
    Stub: send WhatsApp alerts for calendar changes.
    Fully implemented in TZA-37.
    """
    if not changes:
        return
    logger.info('send_change_alerts called for %s with %d changes (stub)', phone_number, len(changes))
