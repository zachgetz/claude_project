"""
Unit tests for apps.calendar_bot.sync.

Focuses on send_change_alerts() alert message format and filtering logic.
"""
import datetime
from unittest.mock import patch, MagicMock

import pytz
from django.test import TestCase, override_settings

from apps.calendar_bot.models import CalendarToken


TWILIO_SETTINGS = dict(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
    GOOGLE_CLIENT_ID='fake_id',
    GOOGLE_CLIENT_SECRET='fake_secret',
)

PATCH_TWILIO = 'apps.calendar_bot.sync.Client'
PATCH_GET_USER_TZ = 'apps.calendar_bot.sync.get_user_tz'


def _make_token(phone='+1234567890', tz='UTC'):
    return CalendarToken.objects.create(
        phone_number=phone,
        access_token='a',
        refresh_token='b',
        timezone=tz,
    )


@override_settings(**TWILIO_SETTINGS)
class SendChangeAlertsTests(TestCase):
    """
    Tests for send_change_alerts(phone_number, changes).
    Only events today or tomorrow trigger alerts; next-week events are suppressed.
    """

    PHONE = '+1234567890'

    def setUp(self):
        _make_token(phone=self.PHONE)

    def _today_dt(self, hour=10):
        now = datetime.datetime.now(tz=pytz.UTC)
        return datetime.datetime(now.year, now.month, now.day, hour, 0, 0, tzinfo=pytz.UTC)

    def _tomorrow_dt(self, hour=10):
        tomorrow = datetime.datetime.now(tz=pytz.UTC).date() + datetime.timedelta(days=1)
        return datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, hour, 0, 0, tzinfo=pytz.UTC)

    def _next_week_dt(self, hour=10):
        next_week = datetime.datetime.now(tz=pytz.UTC).date() + datetime.timedelta(days=7)
        return datetime.datetime(next_week.year, next_week.month, next_week.day, hour, 0, 0, tzinfo=pytz.UTC)

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_TWILIO)
    def test_rescheduled_alert_format(self, mock_twilio_cls, mock_get_tz):
        from apps.calendar_bot.sync import send_change_alerts

        mock_get_tz.return_value = pytz.UTC
        mock_client = MagicMock()
        mock_twilio_cls.return_value = mock_client

        old_start = self._today_dt(9)
        new_start = self._today_dt(11)

        changes = [{
            'type': 'rescheduled',
            'event_id': 'evt_1',
            'title': 'Team Standup',
            'old_start': old_start,
            'new_start': new_start,
        }]
        send_change_alerts(self.PHONE, changes)

        mock_client.messages.create.assert_called_once()
        body = mock_client.messages.create.call_args.kwargs['body']
        # Hebrew: פגישה הוזזה
        self.assertIn('\u05d4\u05d5\u05d6\u05d6\u05d4', body)
        self.assertIn('Team Standup', body)
        self.assertIn('09:00', body)
        self.assertIn('11:00', body)

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_TWILIO)
    def test_cancelled_alert_format(self, mock_twilio_cls, mock_get_tz):
        from apps.calendar_bot.sync import send_change_alerts

        mock_get_tz.return_value = pytz.UTC
        mock_client = MagicMock()
        mock_twilio_cls.return_value = mock_client

        changes = [{
            'type': 'cancelled',
            'event_id': 'evt_2',
            'title': 'Design Review',
            'old_start': self._today_dt(14),
            'new_start': None,
        }]
        send_change_alerts(self.PHONE, changes)

        mock_client.messages.create.assert_called_once()
        body = mock_client.messages.create.call_args.kwargs['body']
        # Hebrew: פגישה בוטלה
        self.assertIn('\u05d1\u05d5\u05d8\u05dc\u05d4', body)
        self.assertIn('Design Review', body)

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_TWILIO)
    def test_new_meeting_alert_for_today(self, mock_twilio_cls, mock_get_tz):
        from apps.calendar_bot.sync import send_change_alerts

        mock_get_tz.return_value = pytz.UTC
        mock_client = MagicMock()
        mock_twilio_cls.return_value = mock_client

        changes = [{
            'type': 'new',
            'event_id': 'evt_3',
            'title': 'Emergency Sync',
            'old_start': None,
            'new_start': self._today_dt(15),
        }]
        send_change_alerts(self.PHONE, changes)

        mock_client.messages.create.assert_called_once()
        body = mock_client.messages.create.call_args.kwargs['body']
        self.assertIn('Emergency Sync', body)
        # Hebrew: היום
        self.assertIn('\u05d4\u05d9\u05d5\u05dd', body)

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_TWILIO)
    def test_new_meeting_alert_for_tomorrow(self, mock_twilio_cls, mock_get_tz):
        from apps.calendar_bot.sync import send_change_alerts

        mock_get_tz.return_value = pytz.UTC
        mock_client = MagicMock()
        mock_twilio_cls.return_value = mock_client

        changes = [{
            'type': 'new',
            'event_id': 'evt_4',
            'title': 'Planning',
            'old_start': None,
            'new_start': self._tomorrow_dt(10),
        }]
        send_change_alerts(self.PHONE, changes)

        mock_client.messages.create.assert_called_once()
        body = mock_client.messages.create.call_args.kwargs['body']
        self.assertIn('Planning', body)
        # Hebrew: מחר
        self.assertIn('\u05de\u05d7\u05e8', body)

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_TWILIO)
    def test_no_alert_for_next_week_changes(self, mock_twilio_cls, mock_get_tz):
        from apps.calendar_bot.sync import send_change_alerts

        mock_get_tz.return_value = pytz.UTC
        mock_client = MagicMock()
        mock_twilio_cls.return_value = mock_client

        changes = [{
            'type': 'new',
            'event_id': 'evt_5',
            'title': 'Future Meeting',
            'old_start': None,
            'new_start': self._next_week_dt(10),
        }]
        send_change_alerts(self.PHONE, changes)

        mock_client.messages.create.assert_not_called()

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_TWILIO)
    def test_empty_changes_does_nothing(self, mock_twilio_cls, mock_get_tz):
        from apps.calendar_bot.sync import send_change_alerts

        mock_get_tz.return_value = pytz.UTC
        mock_client = MagicMock()
        mock_twilio_cls.return_value = mock_client

        send_change_alerts(self.PHONE, [])

        mock_twilio_cls.assert_not_called()

    @patch(PATCH_GET_USER_TZ)
    @patch(PATCH_TWILIO)
    def test_twilio_failure_does_not_propagate(self, mock_twilio_cls, mock_get_tz):
        """A Twilio exception for one alert should not stop processing of others."""
        from apps.calendar_bot.sync import send_change_alerts

        mock_get_tz.return_value = pytz.UTC
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception('Twilio 500')
        mock_twilio_cls.return_value = mock_client

        changes = [{
            'type': 'new',
            'event_id': 'evt_6',
            'title': 'Crash Meeting',
            'old_start': None,
            'new_start': self._today_dt(10),
        }]
        # Should not raise
        send_change_alerts(self.PHONE, changes)
