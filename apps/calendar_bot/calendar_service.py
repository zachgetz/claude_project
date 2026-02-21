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
    Return the pytz timezone object for the user. Defaults to UTC.
    """
    try:
        token = CalendarToken.objects.get(phone_number=phone_number)
        return pytz.timezone(token.timezone)
    except (CalendarToken.DoesNotExist, Exception):
        return pytz.UTC


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
