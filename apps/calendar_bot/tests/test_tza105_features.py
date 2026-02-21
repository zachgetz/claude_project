"""
Tests for TZA-105 features:
  - 'calendar status' WhatsApp command
  - renew_watch_channels management command
"""
import datetime
from io import StringIO
from unittest.mock import patch, MagicMock

import pytz
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from django.urls import reverse

from apps.calendar_bot.models import CalendarToken, CalendarWatchChannel


PATCH_PERMISSION = patch(
    'apps.standup.permissions.TwilioSignaturePermission.has_permission',
    return_value=True,
)

TWILIO_SETTINGS = dict(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
)


def _make_token(phone='whatsapp:+1234567890', email='test@example.com', access_token='tok'):
    return CalendarToken.objects.create(
        phone_number=phone,
        account_email=email,
        access_token=access_token,
        refresh_token='ref',
    )


# ---------------------------------------------------------------------------
# calendar status command tests
# ---------------------------------------------------------------------------

@override_settings(
    **TWILIO_SETTINGS,
    WEBHOOK_BASE_URL='https://myapp.example.com',
)
class CalendarStatusCommandTests(TestCase):
    """Tests for the 'calendar status' WhatsApp command (TZA-105 Fix 2)."""

    PHONE = 'whatsapp:+1234567890'

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')

    def _post(self, body):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url,
                data={'From': self.PHONE, 'Body': body},
                format='multipart',
            )

    def test_calendar_status_returns_200(self):
        _make_token(phone=self.PHONE)
        response = self._post('calendar status')
        self.assertEqual(response.status_code, 200)

    def test_calendar_status_case_insensitive(self):
        """Command must match case-insensitively."""
        _make_token(phone=self.PHONE)
        response = self._post('Calendar Status')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Status', content)

    def test_calendar_status_shows_webhook_url_configured(self):
        _make_token(phone=self.PHONE)
        response = self._post('calendar status')
        content = response.content.decode()
        self.assertIn('myapp.example.com', content)

    def test_calendar_status_shows_connected_email(self):
        _make_token(phone=self.PHONE, email='user@gmail.com')
        response = self._post('calendar status')
        content = response.content.decode()
        self.assertIn('user@gmail.com', content)

    def test_calendar_status_shows_watch_channel_expiry(self):
        token = _make_token(phone=self.PHONE)
        expiry = datetime.datetime(2026, 3, 1, 12, 0, 0, tzinfo=pytz.UTC)
        CalendarWatchChannel.objects.create(
            phone_number=self.PHONE,
            token=token,
            resource_id='res1',
            expiry=expiry,
        )
        response = self._post('calendar status')
        content = response.content.decode()
        self.assertIn('2026-03-01', content)

    def test_calendar_status_shows_no_active_channel_when_none(self):
        _make_token(phone=self.PHONE)
        # No CalendarWatchChannel created
        response = self._post('calendar status')
        content = response.content.decode()
        # Should indicate no active channel (Hebrew text for no active channel)
        self.assertIn('Watch channel', content)

    @override_settings(
        TWILIO_ACCOUNT_SID='ACtest',
        TWILIO_AUTH_TOKEN='test_token',
        TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
        WEBHOOK_BASE_URL='',
    )
    def test_calendar_status_shows_webhook_not_set(self):
        _make_token(phone=self.PHONE)
        response = self._post('calendar status')
        content = response.content.decode()
        self.assertIn('not set', content)

    def test_calendar_status_no_accounts_connected(self):
        # No token
        response = self._post('calendar status')
        content = response.content.decode()
        self.assertIn('No Google accounts connected', content)

    def test_calendar_status_shows_never_synced_when_no_snapshot(self):
        _make_token(phone=self.PHONE)
        response = self._post('calendar status')
        content = response.content.decode()
        self.assertIn('never', content)


# ---------------------------------------------------------------------------
# renew_watch_channels management command tests
# ---------------------------------------------------------------------------

@override_settings(
    GOOGLE_CLIENT_ID='fake_id',
    GOOGLE_CLIENT_SECRET='fake_secret',
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
)
class RenewWatchChannelsCommandTests(TestCase):
    """Tests for python manage.py renew_watch_channels (TZA-105 Fix 4)."""

    PHONE = '+1234567890'

    def _make_token(self, phone=None, email='u@example.com'):
        phone = phone or self.PHONE
        return CalendarToken.objects.create(
            phone_number=phone,
            account_email=email,
            access_token='tok',
            refresh_token='ref',
        )

    @override_settings(WEBHOOK_BASE_URL='')
    def test_command_warns_and_exits_when_no_webhook_url(self):
        """When WEBHOOK_BASE_URL is empty, command must print an error and return."""
        self._make_token()
        out = StringIO()
        err = StringIO()
        call_command('renew_watch_channels', stdout=out, stderr=err)
        err_output = err.getvalue()
        self.assertIn('WEBHOOK_BASE_URL', err_output)

    @override_settings(WEBHOOK_BASE_URL=None)
    def test_command_warns_when_webhook_url_is_none(self):
        self._make_token()
        out = StringIO()
        err = StringIO()
        call_command('renew_watch_channels', stdout=out, stderr=err)
        err_output = err.getvalue()
        self.assertIn('WEBHOOK_BASE_URL', err_output)

    @override_settings(WEBHOOK_BASE_URL='https://example.com')
    @patch('apps.calendar_bot.management.commands.renew_watch_channels.register_watch_channel')
    def test_command_calls_register_for_each_token(self, mock_register):
        """Command must call register_watch_channel once per token."""
        mock_register.return_value = MagicMock(
            channel_id='chan-1',
            expiry=datetime.datetime(2026, 4, 1, tzinfo=pytz.UTC),
        )
        token = self._make_token()
        out = StringIO()
        err = StringIO()
        call_command('renew_watch_channels', stdout=out, stderr=err)

        mock_register.assert_called_once_with(token)
        out_text = out.getvalue()
        self.assertIn('success=1', out_text)

    @override_settings(WEBHOOK_BASE_URL='https://example.com')
    @patch('apps.calendar_bot.management.commands.renew_watch_channels.register_watch_channel')
    def test_command_handles_registration_error_gracefully(self, mock_register):
        """A single token failure must not abort the entire run."""
        mock_register.side_effect = Exception('Google 500')
        self._make_token()
        out = StringIO()
        err = StringIO()
        # Should not raise
        call_command('renew_watch_channels', stdout=out, stderr=err)
        out_text = out.getvalue()
        self.assertIn('errors=1', out_text)

    @override_settings(WEBHOOK_BASE_URL='https://example.com')
    @patch('apps.calendar_bot.management.commands.renew_watch_channels.register_watch_channel')
    def test_command_dry_run_skips_api_calls(self, mock_register):
        """--dry-run must not call register_watch_channel."""
        self._make_token()
        out = StringIO()
        err = StringIO()
        call_command('renew_watch_channels', dry_run=True, stdout=out, stderr=err)
        mock_register.assert_not_called()
        out_text = out.getvalue()
        self.assertIn('dry-run', out_text)

    @override_settings(WEBHOOK_BASE_URL='https://example.com')
    @patch('apps.calendar_bot.management.commands.renew_watch_channels.register_watch_channel')
    def test_command_phone_filter(self, mock_register):
        """--phone must limit renewal to the specified phone."""
        mock_register.return_value = MagicMock(
            channel_id='c1',
            expiry=datetime.datetime(2026, 4, 1, tzinfo=pytz.UTC),
        )
        token_a = self._make_token(phone='+11111111')
        token_b = self._make_token(phone='+22222222', email='b@example.com')
        out = StringIO()
        err = StringIO()
        call_command('renew_watch_channels', phone='+11111111', stdout=out, stderr=err)
        mock_register.assert_called_once_with(token_a)

    @override_settings(WEBHOOK_BASE_URL='https://example.com')
    def test_command_no_tokens_exits_cleanly(self):
        """When no tokens exist the command must exit without error."""
        out = StringIO()
        err = StringIO()
        call_command('renew_watch_channels', stdout=out, stderr=err)
        out_text = out.getvalue()
        self.assertIn('Nothing to do', out_text)
