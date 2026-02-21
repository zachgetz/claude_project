"""
Unit tests for apps.calendar_bot.tasks.

All Google Calendar API and Twilio calls are mocked.
Celery tasks are called directly (synchronously) -- no broker needed.
Updated for TZA-78 multi-account: tasks use get_events_for_date and token FK.
"""
import datetime
from unittest.mock import patch, MagicMock, call

import pytz
from django.test import TestCase, override_settings

from apps.calendar_bot.models import CalendarToken, CalendarWatchChannel


TWILIO_SETTINGS = dict(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
    GOOGLE_CLIENT_ID='fake_id',
    GOOGLE_CLIENT_SECRET='fake_secret',
)

PATCH_TWILIO = 'apps.calendar_bot.tasks.Client'
# New tasks.py uses get_events_for_date, not get_calendar_service
PATCH_GET_EVENTS = 'apps.calendar_bot.tasks.get_events_for_date'
PATCH_GET_USER_TZ = 'apps.calendar_bot.tasks.get_user_tz'


def _make_token(phone='+1111111111', digest_enabled=True, digest_hour=8, digest_minute=0,
                digest_always=False, email='test@example.com'):
    return CalendarToken.objects.create(
        phone_number=phone,
        account_email=email,
        access_token='access_abc',
        refresh_token='refresh_xyz',
        timezone='UTC',
        digest_enabled=digest_enabled,
        digest_hour=digest_hour,
        digest_minute=digest_minute,
        digest_always=digest_always,
    )


def _make_cal_event_dict(title, hour, minute=0):
    """Build an event dict in get_events_for_date format."""
    import pytz
    import datetime
    dt = datetime.datetime(2026, 2, 21, hour, minute, tzinfo=pytz.UTC)
    return {
        'start': dt,
        'start_str': f'{hour:02d}:{minute:02d}',
        'summary': title,
        'end': (dt + datetime.timedelta(hours=1)).isoformat(),
        'raw': {},
    }


@override_settings(**TWILIO_SETTINGS)
class MorningDigestTaskTests(TestCase):
    """Tests for send_morning_meetings_digest task."""

    PHONE_A = '+1111111111'
    PHONE_B = '+2222222222'

    def _run_task(self):
        """Invoke the Celery task synchronously."""
        from apps.calendar_bot.tasks import send_morning_meetings_digest
        send_morning_meetings_digest()

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_GET_EVENTS)
    @patch(PATCH_TWILIO)
    def test_sends_digest_when_digest_hour_matches(self, mock_twilio_cls, mock_get_events, mock_tz):
        """User with matching digest_hour/minute gets a WhatsApp message."""
        _make_token(phone=self.PHONE_A, digest_hour=8, digest_minute=0)

        user_tz = pytz.UTC
        mock_tz.return_value = user_tz
        mock_get_events.return_value = [_make_cal_event_dict('Standup', 9)]

        with patch('apps.calendar_bot.tasks.datetime') as mock_dt:
            fake_now = datetime.datetime(2026, 2, 21, 8, 0, tzinfo=pytz.UTC)
            mock_dt.datetime.now.return_value = fake_now
            mock_dt.datetime.fromisoformat = datetime.datetime.fromisoformat
            mock_dt.timedelta = datetime.timedelta

            mock_client = MagicMock()
            mock_twilio_cls.return_value = mock_client

            self._run_task()

        mock_client.messages.create.assert_called_once()
        body = mock_client.messages.create.call_args.kwargs['body']
        self.assertIn('Standup', body)

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_GET_EVENTS)
    @patch(PATCH_TWILIO)
    def test_skips_when_digest_disabled(self, mock_twilio_cls, mock_get_events, mock_tz):
        """Users with digest_enabled=False are not sent any message."""
        _make_token(phone=self.PHONE_A, digest_enabled=False)

        mock_client = MagicMock()
        mock_twilio_cls.return_value = mock_client

        self._run_task()

        mock_client.messages.create.assert_not_called()

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_GET_EVENTS)
    @patch(PATCH_TWILIO)
    def test_skips_empty_day_unless_digest_always(self, mock_twilio_cls, mock_get_events, mock_tz):
        """No events + digest_always=False -> no message sent."""
        _make_token(phone=self.PHONE_A, digest_hour=8, digest_minute=0, digest_always=False)

        user_tz = pytz.UTC
        mock_tz.return_value = user_tz
        mock_get_events.return_value = []  # no events

        with patch('apps.calendar_bot.tasks.datetime') as mock_dt:
            fake_now = datetime.datetime(2026, 2, 21, 8, 0, tzinfo=pytz.UTC)
            mock_dt.datetime.now.return_value = fake_now
            mock_dt.datetime.fromisoformat = datetime.datetime.fromisoformat
            mock_dt.timedelta = datetime.timedelta

            mock_client = MagicMock()
            mock_twilio_cls.return_value = mock_client

            self._run_task()

        mock_client.messages.create.assert_not_called()

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_GET_EVENTS)
    @patch(PATCH_TWILIO)
    def test_sends_no_meetings_when_digest_always(self, mock_twilio_cls, mock_get_events, mock_tz):
        """digest_always=True + no events -> still sends a no-meetings message in Hebrew."""
        _make_token(phone=self.PHONE_A, digest_hour=8, digest_minute=0, digest_always=True)

        user_tz = pytz.UTC
        mock_tz.return_value = user_tz
        mock_get_events.return_value = []

        with patch('apps.calendar_bot.tasks.datetime') as mock_dt:
            fake_now = datetime.datetime(2026, 2, 21, 8, 0, tzinfo=pytz.UTC)
            mock_dt.datetime.now.return_value = fake_now
            mock_dt.datetime.fromisoformat = datetime.datetime.fromisoformat
            mock_dt.timedelta = datetime.timedelta

            mock_client = MagicMock()
            mock_twilio_cls.return_value = mock_client

            self._run_task()

        mock_client.messages.create.assert_called_once()
        body = mock_client.messages.create.call_args.kwargs['body']
        # App sends Hebrew text; assert the Hebrew "no meetings today" phrase is present
        self.assertIn('\u05d0\u05d9\u05df \u05e4\u05d2\u05d9\u05e9\u05d5\u05ea \u05d4\u05d9\u05d5\u05dd', body)

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_GET_EVENTS)
    @patch(PATCH_TWILIO)
    def test_per_user_failure_does_not_stop_other_users(self, mock_twilio_cls, mock_get_events, mock_tz):
        """Exception for user A should not prevent user B getting digest."""
        _make_token(phone=self.PHONE_A, digest_hour=8, digest_minute=0, email='a@example.com')
        _make_token(phone=self.PHONE_B, digest_hour=8, digest_minute=0, email='b@example.com')

        user_tz = pytz.UTC
        mock_tz.return_value = user_tz

        # First phone's get_events_for_date raises, second succeeds
        mock_get_events.side_effect = [
            Exception('Google API Error'),
            [_make_cal_event_dict('Sync', 9)],
        ]

        mock_client = MagicMock()
        mock_twilio_cls.return_value = mock_client

        with patch('apps.calendar_bot.tasks.datetime') as mock_dt:
            fake_now = datetime.datetime(2026, 2, 21, 8, 0, tzinfo=pytz.UTC)
            mock_dt.datetime.now.return_value = fake_now
            mock_dt.datetime.fromisoformat = datetime.datetime.fromisoformat
            mock_dt.timedelta = datetime.timedelta

            # Should not raise
            self._run_task()

        # User B still gets a message
        self.assertGreaterEqual(mock_client.messages.create.call_count, 1)

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_GET_EVENTS)
    @patch(PATCH_TWILIO)
    def test_two_tokens_same_phone_sends_one_digest(self, mock_twilio_cls, mock_get_events, mock_tz):
        """Two tokens for the same phone should result in only ONE merged digest message."""
        _make_token(phone=self.PHONE_A, digest_hour=8, digest_minute=0, email='work@example.com')
        _make_token(phone=self.PHONE_A, digest_hour=8, digest_minute=0, email='personal@example.com')

        user_tz = pytz.UTC
        mock_tz.return_value = user_tz
        mock_get_events.return_value = [
            _make_cal_event_dict('Work Meeting', 9),
            _make_cal_event_dict('Personal Event', 10),
        ]

        mock_client = MagicMock()
        mock_twilio_cls.return_value = mock_client

        with patch('apps.calendar_bot.tasks.datetime') as mock_dt:
            fake_now = datetime.datetime(2026, 2, 21, 8, 0, tzinfo=pytz.UTC)
            mock_dt.datetime.now.return_value = fake_now
            mock_dt.datetime.fromisoformat = datetime.datetime.fromisoformat
            mock_dt.timedelta = datetime.timedelta

            self._run_task()

        # Should send exactly ONE message (not two)
        self.assertEqual(mock_client.messages.create.call_count, 1)


@override_settings(**TWILIO_SETTINGS)
class RenewWatchChannelsTests(TestCase):
    """Tests for renew_watch_channels task."""

    PHONE = '+3333333333'

    def setUp(self):
        self.token = CalendarToken.objects.create(
            phone_number=self.PHONE,
            account_email='renew@example.com',
            access_token='a',
            refresh_token='b',
        )

    @patch('apps.calendar_bot.tasks.register_watch_channel')
    def test_renews_expiring_channels_with_token(self, mock_register):
        """Channels with a token FK that are expiring should be renewed."""
        from apps.calendar_bot.tasks import renew_watch_channels

        now = datetime.datetime.now(tz=pytz.UTC)
        # Create channel expiring in 12 hours (within threshold of 24h), with token FK
        channel = CalendarWatchChannel.objects.create(
            phone_number=self.PHONE,
            token=self.token,
            expiry=now + datetime.timedelta(hours=12),
        )

        renew_watch_channels()

        mock_register.assert_called_once_with(self.token)

    @patch('apps.calendar_bot.tasks.register_watch_channel')
    def test_skips_channels_without_token_fk(self, mock_register):
        """Channels without a token FK (legacy) should be skipped."""
        from apps.calendar_bot.tasks import renew_watch_channels

        now = datetime.datetime.now(tz=pytz.UTC)
        # Channel has no token FK
        CalendarWatchChannel.objects.create(
            phone_number=self.PHONE,
            token=None,
            expiry=now + datetime.timedelta(hours=12),
        )

        renew_watch_channels()

        mock_register.assert_not_called()

    @patch('apps.calendar_bot.tasks.register_watch_channel')
    def test_skips_channels_not_expiring_soon(self, mock_register):
        from apps.calendar_bot.tasks import renew_watch_channels

        now = datetime.datetime.now(tz=pytz.UTC)
        # Channel expires in 48 hours -- outside 24-hour threshold
        CalendarWatchChannel.objects.create(
            phone_number=self.PHONE,
            token=self.token,
            expiry=now + datetime.timedelta(hours=48),
        )

        renew_watch_channels()

        mock_register.assert_not_called()

    @patch('apps.calendar_bot.tasks.register_watch_channel')
    def test_no_channels_does_not_crash(self, mock_register):
        from apps.calendar_bot.tasks import renew_watch_channels

        renew_watch_channels()
        mock_register.assert_not_called()
