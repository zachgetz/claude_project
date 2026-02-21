import datetime
import pytz
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from .models import CalendarToken, CalendarEventSnapshot


def get_calendar_service(phone_number):
    """
    Load the CalendarToken for phone_number, refresh if expired, and
    return a Google Calendar API service client.
    """
    token = CalendarToken.objects.get(phone_number=phone_number)

    creds = Credentials(
        token=token.access_token,
        refresh_token=token.refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=_get_client_id(),
        client_secret=_get_client_secret(),
    )

    # Refresh if expired
    if token.token_expiry and _is_expired(token.token_expiry):
        creds.refresh(Request())
        # Persist refreshed token
        token.access_token = creds.token
        if creds.expiry:
            token.token_expiry = creds.expiry.replace(tzinfo=pytz.UTC)
        token.save()

    return build('calendar', 'v3', credentials=creds)


def get_user_tz(phone_number):
    """
    Return the pytz timezone object for the user. Defaults to UTC if
    no token exists or the stored timezone is invalid.
    """
    try:
        token = CalendarToken.objects.get(phone_number=phone_number)
        return pytz.timezone(token.timezone)
    except CalendarToken.DoesNotExist:
        return pytz.UTC
    except Exception:
        return pytz.UTC


def get_events_for_date(phone_number, target_date):
    """
    Fetch all-day and timed events from Google Calendar for a specific
    date (datetime.date) in the user's local timezone.
    Returns a list of event dicts with 'start', 'summary' keys.
    """
    user_tz = get_user_tz(phone_number)
    service = get_calendar_service(phone_number)

    # Build timezone-aware start/end for the day
    day_start = user_tz.localize(datetime.datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0))
    day_end = user_tz.localize(datetime.datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59))

    events_result = service.events().list(
        calendarId='primary',
        timeMin=day_start.isoformat(),
        timeMax=day_end.isoformat(),
        singleEvents=True,
        orderBy='startTime',
    ).execute()

    events = []
    for item in events_result.get('items', []):
        start_raw = item.get('start', {})
        # timed event
        if 'dateTime' in start_raw:
            start_dt = datetime.datetime.fromisoformat(start_raw['dateTime'])
            if start_dt.tzinfo is None:
                start_dt = pytz.UTC.localize(start_dt)
            start_local = start_dt.astimezone(user_tz)
            events.append({
                'start': start_local,
                'start_str': start_local.strftime('%H:%M'),
                'summary': item.get('summary', '(No title)'),
                'raw': item,
            })
        else:
            # all-day event
            events.append({
                'start': None,
                'start_str': 'All day',
                'summary': item.get('summary', '(No title)'),
                'raw': item,
            })
    return events


def sync_calendar_snapshot(phone_number):
    """
    Fetches events for next 7 days, compares with stored snapshots.
    Returns list of changes: [{type, event_id, title, old_start, new_start}]
    Debounce: ignore if same event_id updated less than 5 min ago.
    Updates snapshots to latest state.
    """
    now = datetime.datetime.now(tz=pytz.UTC)
    debounce_cutoff = now - datetime.timedelta(minutes=5)

    service = get_calendar_service(phone_number)
    user_tz = get_user_tz(phone_number)

    # Fetch events for next 7 days
    time_min = now
    time_max = now + datetime.timedelta(days=7)

    events_result = service.events().list(
        calendarId='primary',
        timeMin=time_min.isoformat(),
        timeMax=time_max.isoformat(),
        singleEvents=True,
        orderBy='startTime',
    ).execute()

    # Build a dict of current events from Google {event_id -> event_item}
    current_events = {}
    for item in events_result.get('items', []):
        event_id = item.get('id')
        if not event_id:
            continue
        start_raw = item.get('start', {})
        end_raw = item.get('end', {})
        if 'dateTime' not in start_raw or 'dateTime' not in end_raw:
            # Skip all-day events for snapshot tracking
            continue
        start_dt = datetime.datetime.fromisoformat(start_raw['dateTime'])
        end_dt = datetime.datetime.fromisoformat(end_raw['dateTime'])
        if start_dt.tzinfo is None:
            start_dt = pytz.UTC.localize(start_dt)
        if end_dt.tzinfo is None:
            end_dt = pytz.UTC.localize(end_dt)
        current_events[event_id] = {
            'event_id': event_id,
            'title': item.get('summary', '(No title)'),
            'start_time': start_dt.astimezone(pytz.UTC),
            'end_time': end_dt.astimezone(pytz.UTC),
        }

    # Load existing snapshots for this user
    existing_snapshots = {
        snap.event_id: snap
        for snap in CalendarEventSnapshot.objects.filter(phone_number=phone_number)
    }

    changes = []

    # Detect new events and rescheduled events
    for event_id, current in current_events.items():
        snap = existing_snapshots.get(event_id)

        if snap is None:
            # New event — create snapshot
            CalendarEventSnapshot.objects.create(
                phone_number=phone_number,
                event_id=event_id,
                title=current['title'],
                start_time=current['start_time'],
                end_time=current['end_time'],
                status='active',
            )
            changes.append({
                'type': 'new',
                'event_id': event_id,
                'title': current['title'],
                'old_start': None,
                'new_start': current['start_time'],
            })
        elif snap.status == 'cancelled':
            # Was cancelled but now active again — treat as new
            snap.title = current['title']
            snap.start_time = current['start_time']
            snap.end_time = current['end_time']
            snap.status = 'active'
            snap.save()
            changes.append({
                'type': 'new',
                'event_id': event_id,
                'title': current['title'],
                'old_start': None,
                'new_start': current['start_time'],
            })
        else:
            # Check for reschedule — compare start_time
            if snap.start_time != current['start_time']:
                # Debounce: skip if updated < 5 min ago
                if snap.updated_at > debounce_cutoff:
                    continue
                old_start = snap.start_time
                snap.title = current['title']
                snap.start_time = current['start_time']
                snap.end_time = current['end_time']
                snap.save()
                changes.append({
                    'type': 'rescheduled',
                    'event_id': event_id,
                    'title': current['title'],
                    'old_start': old_start,
                    'new_start': current['start_time'],
                })

    # Detect cancelled events (in snapshot but not in current events)
    for event_id, snap in existing_snapshots.items():
        if event_id not in current_events and snap.status == 'active':
            # Debounce: skip if updated < 5 min ago
            if snap.updated_at > debounce_cutoff:
                continue
            snap.status = 'cancelled'
            snap.save()
            changes.append({
                'type': 'cancelled',
                'event_id': event_id,
                'title': snap.title,
                'old_start': snap.start_time,
                'new_start': None,
            })

    return changes


def _is_expired(token_expiry):
    now = datetime.datetime.now(tz=pytz.UTC)
    aware_expiry = token_expiry if token_expiry.tzinfo else pytz.UTC.localize(token_expiry)
    return now >= aware_expiry


def _get_client_id():
    from decouple import config
    return config('GOOGLE_CLIENT_ID')


def _get_client_secret():
    from decouple import config
    return config('GOOGLE_CLIENT_SECRET')
