import datetime
import re
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

    # Refresh if token is not valid (handles token_expiry=None safely)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
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
    Returns a list of event dicts with 'start', 'summary', 'end' keys.
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
        end_raw = item.get('end', {})
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
                'end': end_raw.get('dateTime', end_raw.get('date')),
                'raw': item,
            })
        else:
            # all-day event
            events.append({
                'start': None,
                'start_str': 'All day',
                'summary': item.get('summary', '(No title)'),
                'end': end_raw.get('date'),
                'raw': item,
            })
    return events


def sync_calendar_snapshot(phone_number, send_alerts=True):
    """
    Fetches events for next 7 days, compares with stored snapshots.
    Returns list of changes: [{type, event_id, title, old_start, new_start}]
    Debounce: ignore if same event_id updated less than 5 min ago.
    Updates snapshots to latest state.
    If send_alerts=False, snapshots are updated silently (no changes returned).
    """
    now = datetime.datetime.now(tz=pytz.UTC)
    debounce_cutoff = now - datetime.timedelta(minutes=5)

    service = get_calendar_service(phone_number)

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

    # Load existing snapshots for this user (filtered to next 7 days window)
    existing_snapshots = {
        snap.event_id: snap
        for snap in CalendarEventSnapshot.objects.filter(
            phone_number=phone_number,
            start_time__gte=time_min,
            start_time__lte=time_max,
        )
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
            if send_alerts:
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
            if send_alerts:
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
                if send_alerts:
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
            if send_alerts:
                changes.append({
                    'type': 'cancelled',
                    'event_id': event_id,
                    'title': snap.title,
                    'old_start': snap.start_time,
                    'new_start': None,
                })

    return changes


def handle_block_command(phone_number, body):
    """
    Parse natural language block command.
    Check conflicts with existing events.
    If conflict: return warning message asking YES to confirm.
    Store pending confirmation in database.
    If no conflict or confirmed: create event via Google Calendar API.
    Return confirmation message.
    """
    from .models import PendingBlockConfirmation

    # Parse the command
    parsed = _parse_block_command(body)
    if parsed is None:
        return (
            'Could not parse your block command.\n'
            'Try: "block tomorrow 2-4pm" or "block friday 10am-12pm deep work"'
        )

    target_date, start_hour, start_min, end_hour, end_min, title = parsed
    user_tz = get_user_tz(phone_number)
    now_local = datetime.datetime.now(tz=user_tz)
    today = now_local.date()

    # Enforce: only within next 7 days
    delta = (target_date - today).days
    if delta < 0 or delta > 7:
        return 'You can only block time within the next 7 days.'

    # Build timezone-aware start/end datetimes
    start_dt_local = user_tz.localize(
        datetime.datetime(target_date.year, target_date.month, target_date.day, start_hour, start_min)
    )
    end_dt_local = user_tz.localize(
        datetime.datetime(target_date.year, target_date.month, target_date.day, end_hour, end_min)
    )

    if end_dt_local <= start_dt_local:
        return 'End time must be after start time.'

    # Check for conflicts
    try:
        service = get_calendar_service(phone_number)
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_dt_local.isoformat(),
            timeMax=end_dt_local.isoformat(),
            singleEvents=True,
            orderBy='startTime',
        ).execute()
        conflicts = [
            item for item in events_result.get('items', [])
            if 'dateTime' in item.get('start', {})
        ]
    except Exception as exc:
        return f'Could not check calendar: {exc}'

    event_data = {
        'date': target_date.isoformat(),
        'start': start_dt_local.isoformat(),
        'end': end_dt_local.isoformat(),
        'title': title,
    }

    if conflicts:
        # Store pending confirmation
        PendingBlockConfirmation.objects.update_or_create(
            phone_number=phone_number,
            defaults={'event_data': event_data},
        )
        conflict_names = ', '.join(
            f'"{ c.get("summary", "(No title)")}"' for c in conflicts[:3]
        )
        time_range = f'{start_hour:02d}:{start_min:02d}-{end_hour:02d}:{end_min:02d}'
        return (
            f'\u26a0\ufe0f Conflict detected: {conflict_names} overlaps with '
            f'{time_range} on {target_date.strftime("%A, %b %d")}.\n'
            f'Reply YES to create "{title}" anyway.'
        )

    # No conflict — create the event directly
    return _create_calendar_block(phone_number, service, start_dt_local, end_dt_local, title, user_tz)


def confirm_block_command(phone_number):
    """
    Called when user replies YES to a pending block confirmation.
    Creates the event and deletes the pending record.
    Returns confirmation message.
    """
    from .models import PendingBlockConfirmation
    from django.utils import timezone as tz
    import datetime as dt

    try:
        pending = PendingBlockConfirmation.objects.get(phone_number=phone_number)
    except PendingBlockConfirmation.DoesNotExist:
        return 'No pending block to confirm.'

    # Check expiry (10-minute window)
    if hasattr(pending, 'pending_at') and tz.now() - pending.pending_at > dt.timedelta(minutes=10):
        pending.delete()
        return 'Confirmation expired. Please send the block command again.'

    event_data = pending.event_data
    pending.delete()

    user_tz = get_user_tz(phone_number)
    start_dt_local = datetime.datetime.fromisoformat(event_data['start'])
    end_dt_local = datetime.datetime.fromisoformat(event_data['end'])
    title = event_data['title']

    # Ensure timezone-aware
    if start_dt_local.tzinfo is None:
        start_dt_local = user_tz.localize(start_dt_local)
    if end_dt_local.tzinfo is None:
        end_dt_local = user_tz.localize(end_dt_local)

    try:
        service = get_calendar_service(phone_number)
    except Exception as exc:
        return f'Could not connect to calendar: {exc}'

    return _create_calendar_block(phone_number, service, start_dt_local, end_dt_local, title, user_tz)


def _create_calendar_block(phone_number, service, start_dt_local, end_dt_local, title, user_tz):
    """
    Creates a personal (no attendees) event in Google Calendar.
    Returns a confirmation message string.
    """
    title = title[:60]  # enforce max 60 chars
    event_body = {
        'summary': title,
        'start': {'dateTime': start_dt_local.isoformat(), 'timeZone': str(user_tz)},
        'end': {'dateTime': end_dt_local.isoformat(), 'timeZone': str(user_tz)},
    }
    try:
        created = service.events().insert(calendarId='primary', body=event_body).execute()
    except Exception as exc:
        return f'Failed to create event: {exc}'

    time_str = f'{start_dt_local.strftime("%H:%M")}-{end_dt_local.strftime("%H:%M")}'
    date_str = start_dt_local.strftime('%A, %b %d')
    return f'\u2705 Blocked: "{title}" on {date_str} {time_str}'


def _parse_block_command(body):
    """
    Parses commands like:
      block tomorrow 2-4pm
      block friday 10am-12pm deep work
      block today 3pm-4pm
      add meeting tomorrow 9am-10am Client call
    Returns (date, start_hour, start_min, end_hour, end_min, title) or None.
    """
    body_stripped = body.strip()
    # Strip prefix
    lower = body_stripped.lower()
    if lower.startswith('add meeting '):
        rest = body_stripped[len('add meeting '):].strip()
    elif lower.startswith('block '):
        rest = body_stripped[len('block '):].strip()
    else:
        return None

    # Split into tokens: first is date, second is time range, remainder is title
    tokens = rest.split()
    if len(tokens) < 2:
        return None

    date_token = tokens[0].lower()
    time_token = tokens[1]
    title_tokens = tokens[2:]
    title = ' '.join(title_tokens) if title_tokens else 'Blocked'

    # Resolve date
    today = datetime.date.today()
    target_date = _resolve_date(date_token, today)
    if target_date is None:
        return None

    # Parse time range: patterns like "2-4pm", "10am-12pm", "2:30pm-4pm"
    times = _parse_time_range(time_token)
    if times is None:
        return None

    start_hour, start_min, end_hour, end_min = times
    return target_date, start_hour, start_min, end_hour, end_min, title


def _resolve_date(date_token, today):
    """Resolve date token (today, tomorrow, monday..sunday, next monday..sunday) to a date."""
    if date_token == 'today':
        return today
    if date_token == 'tomorrow':
        return today + datetime.timedelta(days=1)

    day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

    # "next monday" pattern
    if date_token.startswith('next '):
        day_name = date_token[5:]
        if day_name in day_names:
            target_weekday = day_names.index(day_name)
            days_ahead = (target_weekday - today.weekday() + 7) % 7
            if days_ahead == 0:
                days_ahead = 7
            return today + datetime.timedelta(days=days_ahead)
        return None

    # Just day name
    if date_token in day_names:
        target_weekday = day_names.index(date_token)
        days_ahead = (target_weekday - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return today + datetime.timedelta(days=days_ahead)

    return None


def _parse_time_range(time_str):
    """
    Parse time range strings like: "2-4pm", "10am-12pm", "2:30pm-4pm", "14:00-16:00".
    Returns (start_hour, start_min, end_hour, end_min) in 24-hour format, or None.
    """
    time_str = time_str.lower().strip()

    # Split on '-' that separates two time parts
    pattern = r'^(\d{1,2}(?::\d{2})?(?:am|pm)?)-((\d{1,2})(?::\d{2})?(?:am|pm)?)$'
    m = re.match(pattern, time_str, re.IGNORECASE)
    if not m:
        return None

    start_str = m.group(1)
    end_str = m.group(2)

    start = _parse_single_time(start_str)
    end = _parse_single_time(end_str)

    if start is None or end is None:
        return None

    start_hour, start_min, start_ampm = start
    end_hour, end_min, end_ampm = end

    # If end has am/pm but start does not, inherit end's am/pm for start
    if start_ampm is None and end_ampm is not None:
        if end_ampm == 'pm' and start_hour < 12:
            start_hour += 12
        elif end_ampm == 'am' and start_hour == 12:
            start_hour = 0
    elif start_ampm == 'pm' and start_hour != 12:
        start_hour += 12
    elif start_ampm == 'am' and start_hour == 12:
        start_hour = 0

    if end_ampm == 'pm' and end_hour != 12:
        end_hour += 12
    elif end_ampm == 'am' and end_hour == 12:
        end_hour = 0

    if not (0 <= start_hour <= 23 and 0 <= start_min <= 59):
        return None
    if not (0 <= end_hour <= 23 and 0 <= end_min <= 59):
        return None

    return start_hour, start_min, end_hour, end_min


def _parse_single_time(time_str):
    """
    Parse a single time like "2", "2:30", "2pm", "2:30pm".
    Returns (hour, minute, ampm_str_or_None).
    """
    m = re.match(r'^(\d{1,2})(?::(\d{2}))?(am|pm)?$', time_str.lower())
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    ampm = m.group(3)
    return hour, minute, ampm


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
