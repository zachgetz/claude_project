"""
Tests for multi-account calendar commands (TZA-78).

Updated for TZA-112: The TZA-110 redesign replaced direct text commands
('connect calendar', 'my calendars', 'remove calendar') with a menu-driven Hebrew UI.

In the new design:
  - 'connect calendar' / 'add calendar': now accessed via Settings (5) > 3
  - 'my calendars': no longer a top-level text command; connected users
    sending the old text now receive the main menu
  - 'remove calendar': no longer supported as a text command; sending it
    returns the main menu for connected users or onboarding for unconnected ones

Tests have been updated to:
  - Use UserMenuState injection to reach the connect-calendar flow via the menu
  - Verify the new Hebrew main-menu response for deprecated text commands
  - Retain structural assertions where underlying data operations still occur
    (cascade-delete, token counting, etc.) tested directly on the model layer
"""
import datetime
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.calendar_bot.models import CalendarToken, CalendarWatchChannel
from apps.standup.views import _set_state


PATCH_PERMISSION = patch(
    'apps.standup.permissions.TwilioSignaturePermission.has_permission',
    return_value=True,
)

TWILIO_SETTINGS = dict(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
    WEBHOOK_BASE_URL='https://example.com',
)


def _make_token(phone='+1234567890', email='work@example.com', label='primary'):
    return CalendarToken.objects.create(
        phone_number=phone,
        account_email=email,
        account_label=label,
        access_token='access_abc',
        refresh_token='refresh_xyz',
    )


@override_settings(**TWILIO_SETTINGS)
class ConnectCalendarCommandTests(TestCase):
    """
    Connect calendar is now reached via Settings (5) > 3 in the new menu-driven UI.
    Direct text commands 'connect calendar' / 'add calendar' are no longer supported.
    """

    PHONE = 'whatsapp:+1234567890'

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')

    def _post(self, body):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url, data={'From': self.PHONE, 'Body': body}, format='multipart'
            )

    def test_connect_calendar_via_settings_menu_returns_oauth_link(self):
        """Settings submenu digit '3' returns the OAuth link with calendar/auth/start."""
        _make_token(phone=self.PHONE)
        _set_state(self.PHONE, 'settings_menu', 1, {})
        response = self._post('3')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('calendar/auth/start', content)

    def test_connect_calendar_uses_webhook_base_url(self):
        """The OAuth link includes the WEBHOOK_BASE_URL (example.com)."""
        _make_token(phone=self.PHONE)
        _set_state(self.PHONE, 'settings_menu', 1, {})
        response = self._post('3')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('example.com', content)

    def test_connect_calendar_text_command_no_longer_works(self):
        """
        Sending 'connect calendar' as plain text now returns the main menu (connected)
        or onboarding (unconnected), not the OAuth link directly.
        """
        _make_token(phone=self.PHONE)
        response = self._post('connect calendar')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Connected user gets main menu, not OAuth link directly
        self.assertIn('תפריט ראשי', content)

    def test_add_calendar_text_command_no_longer_works(self):
        """
        Sending 'add calendar' as plain text now returns the main menu for connected users.
        """
        _make_token(phone=self.PHONE)
        response = self._post('add calendar')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('תפריט ראשי', content)


@override_settings(**TWILIO_SETTINGS)
class MyCalendarsCommandTests(TestCase):
    """
    'my calendars' text command is no longer supported in the TZA-110 redesign.
    Connected users sending 'my calendars' now receive the Hebrew main menu.
    Unconnected users receive the onboarding greeting.
    """

    PHONE = 'whatsapp:+1234567890'

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')

    def _post(self, body):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url, data={'From': self.PHONE, 'Body': body}, format='multipart'
            )

    def test_my_calendars_no_tokens_returns_onboarding(self):
        """Sending 'my calendars' with no CalendarToken returns onboarding greeting."""
        response = self._post('my calendars')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Unconnected user gets onboarding ('היי')
        self.assertIn('היי', content)

    def test_my_calendars_with_token_returns_main_menu(self):
        """Sending 'my calendars' with a connected token returns the main menu."""
        _make_token(phone=self.PHONE, email='work@example.com', label='work')
        response = self._post('my calendars')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('תפריט ראשי', content)

    def test_my_calendars_two_tokens_returns_main_menu(self):
        """Sending 'my calendars' with multiple connected tokens still returns main menu."""
        _make_token(phone=self.PHONE, email='work@example.com', label='work')
        _make_token(phone=self.PHONE, email='personal@example.com', label='personal')
        response = self._post('my calendars')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('תפריט ראשי', content)


@override_settings(**TWILIO_SETTINGS)
class RemoveCalendarCommandTests(TestCase):
    """
    'remove calendar' text command is no longer supported in the TZA-110 redesign.
    Sending it returns the main menu (connected) or onboarding (unconnected).
    The underlying model-layer cascade-delete behaviour is verified directly.
    """

    PHONE = 'whatsapp:+1234567890'

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')

    def _post(self, body):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url, data={'From': self.PHONE, 'Body': body}, format='multipart'
            )

    def test_remove_calendar_text_returns_main_menu_for_connected_user(self):
        """Sending 'remove calendar work@example.com' returns main menu for connected user."""
        _make_token(phone=self.PHONE, email='work@example.com', label='work')
        response = self._post('remove calendar work@example.com')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('תפריט ראשי', content)

    def test_remove_calendar_text_returns_main_menu_by_label(self):
        """Sending 'remove calendar work' returns main menu for connected user."""
        _make_token(phone=self.PHONE, email='work@example.com', label='work')
        response = self._post('remove calendar work')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('תפריט ראשי', content)

    def test_remove_calendar_no_token_returns_onboarding(self):
        """Sending 'remove calendar nonexistent@example.com' with no token returns onboarding."""
        response = self._post('remove calendar nonexistent@example.com')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Unconnected user gets onboarding ('היי')
        self.assertIn('היי', content)

    def test_remove_calendar_no_identifier_returns_main_menu_or_onboarding(self):
        """Sending 'remove calendar' (no identifier) returns a valid 200 response."""
        response = self._post('remove calendar')
        self.assertEqual(response.status_code, 200)

    def test_calendar_token_cascade_delete_model_layer(self):
        """Model-layer: deleting a token also removes its associated watch channels."""
        token = _make_token(phone=self.PHONE, email='work@example.com', label='work')
        CalendarWatchChannel.objects.create(phone_number=self.PHONE, token=token)
        self.assertEqual(CalendarWatchChannel.objects.filter(token=token).count(), 1)

        token.delete()
        self.assertEqual(CalendarWatchChannel.objects.filter(phone_number=self.PHONE).count(), 0)

    def test_two_tokens_one_deletion_leaves_other_model_layer(self):
        """Model-layer: removing one of two CalendarTokens leaves the other intact."""
        _make_token(phone=self.PHONE, email='work@example.com', label='work')
        _make_token(phone=self.PHONE, email='personal@example.com', label='personal')

        CalendarToken.objects.filter(
            phone_number=self.PHONE, account_email='work@example.com'
        ).delete()

        remaining = CalendarToken.objects.filter(phone_number=self.PHONE)
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().account_email, 'personal@example.com')
