"""
TZA-122: Updated tests for TZA-105 features.

After TZA-110, the 'calendar status' WhatsApp command no longer exists — the bot
is fully menu-driven and Hebrew-only.  The CalendarStatusCommandTests have been
rewritten to verify equivalent functionality through the new Settings submenu:

  - Settings menu (state='settings_menu') shows calendar-related options
  - settings_menu + '3' -> connect calendar OAuth link (uses WEBHOOK_BASE_URL)
  - settings_menu + '4' -> disconnect confirmation

Model-layer tests verify that CalendarWatchChannel and connected-email data is
still stored correctly; these are not surfaced as a WhatsApp 'status' command
but remain accessible via the settings menu options.

The renew_watch_channels management command tests are unchanged.
"""
import datetime
from io import StringIO
from unittest.mock import patch, MagicMock

import pytz
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from django.urls import reverse

from apps.calendar_bot.models import CalendarToken, CalendarWatchChannel, UserMenuState
from apps.standup.views import _set_state


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
# Settings menu tests (replaces old 'calendar status' command tests, TZA-122)
# ---------------------------------------------------------------------------

@override_settings(
    **TWILIO_SETTINGS,
    WEBHOOK_BASE_URL='https://myapp.example.com',
)
class SettingsMenuTests(TestCase):
    """
    TZA-122: Settings menu and connect/disconnect calendar flows.

    These tests replace the old 'calendar status' command tests.  The new
    menu-driven design exposes calendar-connection management through the
    Settings submenu (option 5 from the main menu).
    """

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

    def test_settings_menu_returns_200(self):
        """Entering the settings menu returns a 200 response."""
        _make_token(phone=self.PHONE)
        _set_state(self.PHONE, 'settings_menu', 1, {})
        response = self._post('1')  # Timezone option
        self.assertEqual(response.status_code, 200)

    def test_settings_digit_3_returns_oauth_link_with_webhook_base_url(self):
        """Settings > option 3 returns an OAuth link containing the WEBHOOK_BASE_URL."""
        _make_token(phone=self.PHONE)
        _set_state(self.PHONE, 'settings_menu', 1, {})
        response = self._post('3')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('myapp.example.com', content)
        self.assertIn('calendar/auth/start', content)

    @override_settings(
        TWILIO_ACCOUNT_SID='ACtest',
        TWILIO_AUTH_TOKEN='test_token',
        TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
        WEBHOOK_BASE_URL='',
    )
    def test_settings_digit_3_without_webhook_base_url_falls_back_to_request(self):
        """When WEBHOOK_BASE_URL is empty, settings > 3 still returns an OAuth link."""
        _make_token(phone=self.PHONE)
        _set_state(self.PHONE, 'settings_menu', 1, {})
        response = self._post('3')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('calendar/auth/start', content)

    def test_settings_digit_3_includes_phone_in_oauth_url(self):
        """Connect calendar URL contains the user phone number."""
        _make_token(phone=self.PHONE)
        _set_state(self.PHONE, 'settings_menu', 1, {})
        response = self._post('3')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('phone', content)

    def test_settings_digit_4_shows_disconnect_confirmation(self):
        """Settings > option 4 shows the disconnect-calendar confirmation."""
        _make_token(phone=self.PHONE)
        _set_state(self.PHONE, 'settings_menu', 1, {})
        response = self._post('4')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Disconnect confirm text contains Hebrew disconnect word
        self.assertIn('\u05dc\u05e0\u05ea\u05e7', content)

    def test_unconnected_user_gets_onboarding(self):
        """A user with no CalendarToken gets onboarding, not the settings menu."""
        response = self._post('1')  # any digit
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Onboarding greeting contains '\u05d4\u05d9\u05d9' (\u05d4\u05d9\u05d9)
        self.assertIn('\u05d4\u05d9\u05d9', content)

    def test_main_menu_digit_5_enters_settings(self):
        """From main_menu state, digit '5' enters the settings submenu."""
        _make_token(phone=self.PHONE)
        _set_state(self.PHONE, 'main_menu', 1, {})
        response = self._post('5')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Settings menu header: '\u05d4\u05d2\u05d3\u05e8\u05d5\u05ea' (\u05d4\u05d2\u05d3\u05e8\u05d5\u05ea)
        self.assertIn('\u05d4\u05d2\u05d3\u05e8\u05d5\u05ea', content)

    def test_watch_channel_data_is_stored_in_model(self):
        """CalendarWatchChannel with expiry is stored correctly in the DB (model-layer test)."""
        token = _make_token(phone=self.PHONE)
        expiry = datetime.datetime(2026, 3, 1, 12, 0, 0, tzinfo=pytz.UTC)
        channel = CalendarWatchChannel.objects.create(
            phone_number=self.PHONE,
            token=token,
            resource_id='res1',
            expiry=expiry,
        )
        channel.refresh_from_db()
        self.assertEqual(
            channel.expiry.strftime('%Y-%m-%d'),
            '2026-03-01',
        )

    def test_connected_email_stored_in_token(self):
        """The connected account email is stored on the CalendarToken (model-layer test)."""
        token = _make_token(phone=self.PHONE, email='user@gmail.com')
        token.refresh_from_db()
        self.assertEqual(token.account_email, 'user@gmail.com')

    def test_watch_channel_cascade_deletes_with_token(self):
        """Deleting a CalendarToken also cascade-deletes its CalendarWatchChannels."""
        token = _make_token(phone=self.PHONE)
        CalendarWatchChannel.objects.create(phone_number=self.PHONE, token=token)
        self.assertEqual(CalendarWatchChannel.objects.filter(phone_number=self.PHONE).count(), 1)
        token.delete()
        self.assertEqual(CalendarWatchChannel.objects.filter(phone_number=self.PHONE).count(), 0)

    def test_settings_digit_0_returns_to_main_menu(self):
        """Inside the settings menu, '0' returns to the main menu."""
        _make_token(phone=self.PHONE)
        _set_state(self.PHONE, 'settings_menu', 1, {})
        response = self._post('0')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Main menu: '\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9' (\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9)
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)


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
