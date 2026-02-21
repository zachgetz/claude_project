"""
TZA-117: Updated tests for menu and digit routing after TZA-110 Hebrew redesign.

The TZA-110 redesign introduced a fully menu-driven, Hebrew-only state machine.
These tests verify the new behaviour:

- Any input from a connected user at root level -> show Hebrew main menu
  and set state to 'main_menu'.
- Any input from an unconnected user -> onboarding greeting.
- Menu trigger words (menu / options / calendar) behave the same as any
  other root-level input for connected users (show main menu).
- Digits 1-5 in 'main_menu' state enter the corresponding submenu.
- Digit 6 in 'main_menu' state shows the Hebrew help text.
- Digit 0 in 'main_menu' state re-shows the main menu.
- Invalid input in 'main_menu' state shows INVALID_OPTION + main menu.
- Meetings submenu (digits 1-4) delegates to calendar query helpers.
- Free time submenu (digits 1-3) delegates to free-time query helpers.
- No StandupEntry records are ever created by the menu-driven UI.

The TwilioSignaturePermission is patched throughout.
"""
import datetime
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.standup.models import StandupEntry
from apps.calendar_bot.models import CalendarToken, UserMenuState
from apps.standup.views import HELP_TEXT


PATCH_PERMISSION = patch(
    'apps.standup.permissions.TwilioSignaturePermission.has_permission',
    return_value=True,
)

PHONE = 'whatsapp:+1234567890'


# ============================================================================ #
# MenuTriggerTests
# Verify that connected users always see the Hebrew main menu at root level.
# ============================================================================ #

@override_settings(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
    WEBHOOK_BASE_URL='https://example.com',
)
class MenuTriggerTests(TestCase):
    """Root-level inputs for connected users always return the Hebrew main menu."""

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')
        # Create a connected CalendarToken so the user is fully onboarded.
        CalendarToken.objects.create(
            phone_number=PHONE,
            account_email='test@example.com',
            access_token='fake_access',
            refresh_token='fake_refresh',
        )
        UserMenuState.objects.filter(phone_number=PHONE).delete()

    def _post(self, body, from_number=None):
        from_number = from_number or PHONE
        with PATCH_PERMISSION:
            return self.client.post(
                self.url,
                data={'From': from_number, 'Body': body},
                format='multipart',
            )

    # ------------------------------------------------------------------
    # Old trigger words still show main menu
    # ------------------------------------------------------------------

    def test_menu_trigger_returns_hebrew_main_menu(self):
        """Sending 'menu' returns the Hebrew main menu (tafrit rashi)."""
        response = self._post('menu')
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/xml', response['Content-Type'])
        content = response.content.decode()
        # Hebrew main menu header must appear
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8', content)  # 'תפריט'

    def test_options_trigger_returns_hebrew_main_menu(self):
        """Sending 'options' returns the Hebrew main menu."""
        response = self._post('options')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8', content)

    def test_calendar_trigger_returns_hebrew_main_menu(self):
        """Sending 'calendar' returns the Hebrew main menu."""
        response = self._post('calendar')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8', content)

    def test_menu_trigger_uppercase_returns_hebrew_main_menu(self):
        """Menu trigger words are handled (case doesn't matter for root routing)."""
        response = self._post('MENU')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8', content)

    def test_menu_trigger_with_whitespace_returns_hebrew_main_menu(self):
        """Surrounding whitespace is stripped; root still returns main menu."""
        response = self._post('  menu  ')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8', content)

    def test_any_text_returns_hebrew_main_menu(self):
        """Any arbitrary text from a connected user shows the Hebrew main menu."""
        response = self._post('hello world')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8', content)

    # ------------------------------------------------------------------
    # Menu triggers must NOT create StandupEntry records
    # ------------------------------------------------------------------

    def test_menu_trigger_does_not_create_standup_entry(self):
        """Sending 'menu' must NOT create a StandupEntry record."""
        self._post('menu')
        self.assertEqual(StandupEntry.objects.count(), 0)

    def test_options_trigger_does_not_create_standup_entry(self):
        """Sending 'options' must NOT create a StandupEntry record."""
        self._post('options')
        self.assertEqual(StandupEntry.objects.count(), 0)

    def test_calendar_trigger_does_not_create_standup_entry(self):
        """Sending 'calendar' must NOT create a StandupEntry record."""
        self._post('calendar')
        self.assertEqual(StandupEntry.objects.count(), 0)

    def test_arbitrary_text_does_not_create_standup_entry(self):
        """Any free text from a connected user must NOT create a StandupEntry."""
        self._post('Working on project today')
        self.assertEqual(StandupEntry.objects.count(), 0)

    # ------------------------------------------------------------------
    # State machine: root sets main_menu state
    # ------------------------------------------------------------------

    def test_root_text_sets_main_menu_state(self):
        """After any root-level input, state is set to 'main_menu'."""
        self._post('hello')
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'main_menu')

    # ------------------------------------------------------------------
    # Unconnected user
    # ------------------------------------------------------------------

    def test_unconnected_user_gets_onboarding_not_menu(self):
        """A user with no CalendarToken gets the Hebrew onboarding greeting."""
        CalendarToken.objects.filter(phone_number=PHONE).delete()
        response = self._post('menu')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Onboarding greeting asks for name in Hebrew
        self.assertIn('\u05d4\u05d9\u05d9', content)   # 'היי'
        self.assertIn('\u05de\u05d4 \u05e9\u05de\u05da', content)  # 'מה שמך'
        # Must not contain main menu header
        self.assertEqual(StandupEntry.objects.count(), 0)


# ============================================================================ #
# DigitRoutingTests
# Verify digit routing within the 'main_menu' state and submenus.
# ============================================================================ #

@override_settings(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
    WEBHOOK_BASE_URL='https://example.com',
)
class DigitRoutingTests(TestCase):
    """Digit routing inside the main_menu state and numbered submenus."""

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')
        # Connected user.
        CalendarToken.objects.create(
            phone_number=PHONE,
            account_email='test@example.com',
            access_token='fake_access',
            refresh_token='fake_refresh',
        )
        UserMenuState.objects.filter(phone_number=PHONE).delete()

    def _post(self, body, from_number=None):
        from_number = from_number or PHONE
        with PATCH_PERMISSION:
            return self.client.post(
                self.url,
                data={'From': from_number, 'Body': body},
                format='multipart',
            )

    def _set_state(self, action, step=1, data=None):
        UserMenuState.objects.update_or_create(
            phone_number=PHONE,
            defaults={'pending_action': action, 'pending_step': step, 'pending_data': data or {}},
        )

    # ------------------------------------------------------------------
    # main_menu state: digit 1 -> meetings submenu
    # ------------------------------------------------------------------

    def test_main_menu_digit_1_enters_meetings_submenu(self):
        """In main_menu state, digit '1' enters the meetings submenu."""
        self._set_state('main_menu')
        response = self._post('1')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Meetings submenu must appear
        self.assertIn('\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea', content)  # 'פגישות'
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'meetings_menu')

    def test_main_menu_digit_1_does_not_create_standup_entry(self):
        """Digit '1' in main_menu state must NOT create a StandupEntry."""
        self._set_state('main_menu')
        self._post('1')
        self.assertEqual(StandupEntry.objects.count(), 0)

    # ------------------------------------------------------------------
    # main_menu state: digit 2 -> free time submenu
    # ------------------------------------------------------------------

    def test_main_menu_digit_2_enters_free_time_submenu(self):
        """In main_menu state, digit '2' enters the free-time submenu."""
        self._set_state('main_menu')
        response = self._post('2')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('\u05d6\u05de\u05df \u05e4\u05e0\u05d5\u05d9', content)  # 'זמן פנוי'
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'free_time_menu')

    # ------------------------------------------------------------------
    # main_menu state: digit 6 -> Hebrew help text
    # ------------------------------------------------------------------

    def test_main_menu_digit_6_returns_hebrew_help_text(self):
        """In main_menu state, digit '6' returns the Hebrew help text constant."""
        self._set_state('main_menu')
        response = self._post('6')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The response must contain a portion of HELP_TEXT (imported from views).
        # We check for a substring common to all HELP_TEXT variants.
        first_line = HELP_TEXT.split('\n')[0]
        self.assertIn(first_line, content)

    def test_main_menu_digit_6_does_not_create_standup_entry(self):
        """Digit '6' must NOT create a StandupEntry."""
        self._set_state('main_menu')
        self._post('6')
        self.assertEqual(StandupEntry.objects.count(), 0)

    # ------------------------------------------------------------------
    # main_menu state: digit 0 -> re-show main menu
    # ------------------------------------------------------------------

    def test_main_menu_digit_0_reshows_main_menu(self):
        """In main_menu state, digit '0' re-shows the Hebrew main menu."""
        self._set_state('main_menu')
        response = self._post('0')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8', content)

    # ------------------------------------------------------------------
    # main_menu state: invalid input -> INVALID_OPTION + main menu
    # ------------------------------------------------------------------

    def test_main_menu_invalid_input_shows_error_and_menu(self):
        """In main_menu state, invalid input shows INVALID_OPTION + main menu."""
        self._set_state('main_menu')
        response = self._post('99')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Hebrew invalid-option string must appear
        self.assertIn('\u05e2\u05e0\u05d4 \u05ea\u05e9\u05d5\u05d1\u05d4 \u05ea\u05e7\u05d9\u05e0\u05d4', content)
        # Main menu must also re-appear
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8', content)

    # ------------------------------------------------------------------
    # meetings_menu state: digits 1-4 route to query helpers
    # ------------------------------------------------------------------

    def test_meetings_digit_1_routes_to_today_query(self):
        """In meetings_menu, digit '1' calls _query_meetings with 'today'."""
        self._set_state('meetings_menu')
        with patch(
            'apps.standup.views.WhatsAppWebhookView._query_meetings',
            return_value=self._make_xml('today meetings'),
        ) as mock_q:
            response = self._post('1')
            mock_q.assert_called_once_with(PHONE, 'today')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StandupEntry.objects.count(), 0)

    def test_meetings_digit_2_routes_to_tomorrow_query(self):
        """In meetings_menu, digit '2' calls _query_meetings with 'tomorrow'."""
        self._set_state('meetings_menu')
        with patch(
            'apps.standup.views.WhatsAppWebhookView._query_meetings',
            return_value=self._make_xml('tomorrow meetings'),
        ) as mock_q:
            self._post('2')
            mock_q.assert_called_once_with(PHONE, 'tomorrow')

    def test_meetings_digit_3_routes_to_week_query(self):
        """In meetings_menu, digit '3' calls _query_meetings with 'this week'."""
        self._set_state('meetings_menu')
        with patch(
            'apps.standup.views.WhatsAppWebhookView._query_meetings',
            return_value=self._make_xml('week meetings'),
        ) as mock_q:
            self._post('3')
            mock_q.assert_called_once_with(PHONE, 'this week')

    def test_meetings_digit_4_routes_to_next_meeting(self):
        """In meetings_menu, digit '4' calls _query_next_meeting."""
        self._set_state('meetings_menu')
        with patch(
            'apps.standup.views.WhatsAppWebhookView._query_next_meeting',
            return_value=self._make_xml('next meeting'),
        ) as mock_q:
            self._post('4')
            mock_q.assert_called_once_with(PHONE)

    def test_meetings_digit_0_returns_to_main_menu(self):
        """In meetings_menu, digit '0' returns to main menu state."""
        self._set_state('meetings_menu')
        response = self._post('0')
        content = response.content.decode()
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'main_menu')

    def test_meetings_invalid_input_shows_error(self):
        """In meetings_menu, invalid input shows INVALID_OPTION + meetings menu."""
        self._set_state('meetings_menu')
        response = self._post('abc')
        content = response.content.decode()
        self.assertIn('\u05e2\u05e0\u05d4 \u05ea\u05e9\u05d5\u05d1\u05d4 \u05ea\u05e7\u05d9\u05e0\u05d4', content)
        self.assertIn('\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'meetings_menu')

    # ------------------------------------------------------------------
    # free_time_menu state: digit routing
    # ------------------------------------------------------------------

    def test_free_time_digit_1_routes_to_today_free_time(self):
        """In free_time_menu, digit '1' calls _query_free_time with 'today'."""
        self._set_state('free_time_menu')
        with patch(
            'apps.standup.views.WhatsAppWebhookView._query_free_time',
            return_value=self._make_xml('free time today'),
        ) as mock_q:
            self._post('1')
            mock_q.assert_called_once_with(PHONE, 'today')

    def test_free_time_digit_0_returns_to_main_menu(self):
        """In free_time_menu, digit '0' returns to main menu state."""
        self._set_state('free_time_menu')
        response = self._post('0')
        content = response.content.decode()
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'main_menu')

    # ------------------------------------------------------------------
    # No StandupEntry is ever created by menu-driven inputs
    # ------------------------------------------------------------------

    def test_arbitrary_digits_in_main_menu_never_create_standup_entry(self):
        """Digits 7, 8, 9 in main_menu state show INVALID_OPTION, not standup."""
        for digit in ('7', '8', '9'):
            self._set_state('main_menu')
            self._post(digit)
            self.assertEqual(
                StandupEntry.objects.count(), 0,
                msg=f'Digit {digit!r} should not create a StandupEntry',
            )

    def test_multi_digit_input_in_main_menu_does_not_create_standup_entry(self):
        """Multi-digit input like '12' in main_menu shows INVALID_OPTION, not standup."""
        self._set_state('main_menu')
        self._post('12')
        self.assertEqual(StandupEntry.objects.count(), 0)

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _make_xml(text):
        """Return a minimal HttpResponse mimicking a TwiML response."""
        from django.http import HttpResponse
        from twilio.twiml.messaging_response import MessagingResponse
        resp = MessagingResponse()
        resp.message(text)
        return HttpResponse(str(resp), content_type='application/xml')
