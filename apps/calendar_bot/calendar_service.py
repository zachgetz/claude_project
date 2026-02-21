import datetime
import pytz
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from .models import CalendarToken


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
