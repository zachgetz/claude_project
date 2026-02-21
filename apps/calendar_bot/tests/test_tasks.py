"""
Unit tests for apps.calendar_bot.tasks.

All Google Calendar API and Twilio calls are mocked.
Celery tasks are called directly (synchronously) — no broker needed.
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
PATCH_CAL_SVC = 'apps.calendar_bot.tasks.get_calendar_service'
PATCH_GET_USER_TZ = 'apps.calendar_bot.tasks.get_user_tz'


def _make_token(phone='+1111111111', digest_enabled=True, digest_hour=8, digest_minute=0,
                digest_always=False):
    return CalendarToken.objects.create(
        phone_number=phone,
        access_token='access_abc',
        refresh_token='refresh_xyz',
        timezone='UTC',
        digest_enabled=digest_enabled,
        digest_hour=digest_hour,
        digest_minute=digest_minute,
        digest_always=digest_always,
    )


def _make_cal_event(title, hour, minute=0, all_day=False):
    if all_day:
        return {'summary': title, 'start': {'date': '2026-02-21'}}
    dt = datetime.datetime(2026, 2, 21, hour, minute, tzinfo=pytz.UTC)
    return {'summary': title, 'start': {'dateTime': dt.isoformat()}}


@override_settings(**TWILIO_SETTINGS)
class MorningDigestTaskTests(TestCase):
    """Tests for send_morning_meetings_digest task."""

    PHONE_A = '+1111111111'
    PHONE_B = '+2222222222'

    def _run_task(self):
        """Invoke the Celery task synchronously."""
        from apps.calendar_bot.tasks import send_morning_meetings_digest
        send_morning_meetings_digest()

    def _make_mock_service(self, events):
        mock_svc = MagicMock()
        mock_svc.events().list().execute.return_value = {'items': events}
        return mock_svc

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_CAL_SVC)
    @patch(PATCH_TWILIO)
    def test_sends_digest_when_digest_hour_matches(self, mock_twilio_cls, mock_cal_svc, mock_tz):
        """User with matching digest_hour/minute gets a WhatsApp message."""
        token = _make_token(phone=self.PHONE_A, digest_hour=8, digest_minute=0)

        user_tz = pytz.UTC
        mock_tz.return_value = user_tz

        # Simulate now_local.hour == 8, minute == 0
        with patch('apps.calendar_bot.tasks.datetime') as mock_dt:
            fake_now = datetime.datetime(2026, 2, 21, 8, 0, tzinfo=pytz.UTC)
            mock_dt.datetime.now.return_value = fake_now
            mock_dt.datetime.fromisoformat = datetime.datetime.fromisoformat
            mock_dt.timedelta = datetime.timedelta

            mock_cal_svc.return_value = self._make_mock_service([
                _make_cal_event('Standup', 9)
            ])

            mock_client = MagicMock()
            mock_twilio_cls.return_value = mock_client

            self._run_task()

        mock_client.messages.create.assert_called_once()
        body = mock_client.messages.create.call_args.kwargs['body']
        self.assertIn('Standup', body)

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_CAL_SVC)
    @patch(PATCH_TWILIO)
    def test_skips_when_digest_disabled(self, mock_twilio_cls, mock_cal_svc, mock_tz):
        """Users with digest_enabled=False are not sent any message."""
        _make_token(phone=self.PHONE_A, digest_enabled=False)

        mock_client = MagicMock()
        mock_twilio_cls.return_value = mock_client

        self._run_task()

        mock_client.messages.create.assert_not_called()

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_CAL_SVC)
    @patch(PATCH_TWILIO)
    def test_skips_empty_day_unless_digest_always(self, mock_twilio_cls, mock_cal_svc, mock_tz):
        """No events + digest_always=False -> no message sent."""
        token = _make_token(phone=self.PHONE_A, digest_hour=8, digest_minute=0, digest_always=False)

        user_tz = pytz.UTC
        mock_tz.return_value = user_tz

        with patch('apps.calendar_bot.tasks.datetime') as mock_dt:
            fake_now = datetime.datetime(2026, 2, 21, 8, 0, tzinfo=pytz.UTC)
            mock_dt.datetime.now.return_value = fake_now
            mock_dt.datetime.fromisoformat = datetime.datetime.fromisoformat
            mock_dt.timedelta = datetime.timedelta

            mock_cal_svc.return_value = self._make_mock_service([])  # no events

            mock_client = MagicMock()
            mock_twilio_cls.return_value = mock_client

            self._run_task()

        mock_client.messages.create.assert_not_called()

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_CAL_SVC)
    @patch(PATCH_TWILIO)
    def test_sends_no_meetings_when_digest_always(self, mock_twilio_cls, mock_cal_svc, mock_tz):
        """digest_always=True + no events -> still sends 'No meetings' message."""
        token = _make_token(phone=self.PHONE_A, digest_hour=8, digest_minute=0, digest_always=True)

        user_tz = pytz.UTC
        mock_tz.return_value = user_tz

        with patch('apps.calendar_bot.tasks.datetime') as mock_dt:
            fake_now = datetime.datetime(2026, 2, 21, 8, 0, tzinfo=pytz.UTC)
            mock_dt.datetime.now.return_value = fake_now
            mock_dt.datetime.fromisoformat = datetime.datetime.fromisoformat
            mock_dt.timedelta = datetime.timedelta

            mock_cal_svc.return_value = self._make_mock_service([])

            mock_client = MagicMock()
            mock_twilio_cls.return_value = mock_client

            self._run_task()

        mock_client.messages.create.assert_called_once()
        body = mock_client.messages.create.call_args.kwargs['body']
        self.assertIn('No meetings', body)

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_CAL_SVC)
    @patch(PATCH_TWILIO)
    def test_per_user_failure_does_not_stop_other_users(self, mock_twilio_cls, mock_cal_svc, mock_tz):
        """Exception for user A should not prevent user B getting digest."""
        token_a = _make_token(phone=self.PHONE_A, digest_hour=8, digest_minute=0)
        token_b = _make_token(phone=self.PHONE_B, digest_hour=8, digest_minute=0)

        user_tz = pytz.UTC
        mock_tz.return_value = user_tz

        # First user's cal service raises, second succeeds
        mock_cal_svc.side_effect = [
            Exception('Google API Error'),
            self._make_mock_service([_make_cal_event('Sync', 9)]),
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


@override_settings(**TWILIO_SETTINGS)
class RenewWatchChannelsTests(TestCase):
    """Tests for renew_watch_channels task."""

    PHONE = '+3333333333'

    def setUp(self):
        CalendarToken.objects.create(
            phone_number=self.PHONE,
            access_token='a',
            refresh_token='b',
        )

    @patch('apps.calendar_bot.sync.register_watch_channel')
    def test_renews_expiring_channels(self, mock_register):
        from apps.calendar_bot.tasks import renew_watch_channels

        now = datetime.datetime.now(tz=pytz.UTC)
        # Create channel expiring in 12 hours (within threshold of 24h)
        channel = CalendarWatchChannel.objects.create(
            phone_number=self.PHONE,
            expiry=now + datetime.timedelta(hours=12),
        )

        renew_watch_channels()

        mock_register.assert_called_once_with(self.PHONE)

    @patch('apps.calendar_bot.sync.register_watch_channel')
    def test_skips_channels_not_expiring_soon(self, mock_register):
        from apps.calendar_bot.tasks import renew_watch_channels

        now = datetime.datetime.now(tz=pytz.UTC)
        # Channel expires in 48 hours — outside 24-hour threshold
        channel = CalendarWatchChannel.objects.create(
            phone_number=self.PHONE,
            expiry=now + datetime.timedelta(hours=48),
        )

        renew_watch_channels()

        mock_register.assert_not_called()

    @patch('apps.calendar_bot.sync.register_watch_channel')
    def test_no_channels_does_not_crash(self, mock_register):
        from apps.calendar_bot.tasks import renew_watch_channels

        renew_watch_channels()
        mock_register.assert_not_called()
