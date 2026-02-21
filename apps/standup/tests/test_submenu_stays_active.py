"""
TZA-121: Tests for submenu-stays-active behaviour.

After a valid selection inside a query submenu (meetings, free time, birthdays),
the bot should:
  1. Return the query result.
  2. Re-append the submenu options to the response.
  3. Keep pending_action set to the current submenu state.

Only '0' (or \u05d1\u05d8\u05dc for digest) should clear submenu state back to main_menu.
Invalid input while in submenu still shows INVALID_OPTION + submenu (unchanged from TZA-110).

The TwilioSignaturePermission is patched throughout.
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.calendar_bot.models import CalendarToken, UserMenuState

PATCH_PERMISSION = patch(
    'apps.standup.permissions.TwilioSignaturePermission.has_permission',
    return_value=True,
)

PHONE = 'whatsapp:+972509876543'


@override_settings(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
    WEBHOOK_BASE_URL='https://example.com',
)
class SubmenuStaysActiveTests(TestCase):
    """
    Verify that after a valid query-submenu selection the bot re-shows the
    submenu and keeps state set to that submenu.
    """

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')
        self.token = CalendarToken.objects.create(
            phone_number=PHONE,
            account_email='test@example.com',
            access_token='fake_access',
            refresh_token='fake_refresh',
            timezone='Asia/Jerusalem',
        )
        UserMenuState.objects.filter(phone_number=PHONE).delete()

    def _post(self, body):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url,
                data={'From': PHONE, 'Body': body},
                format='multipart',
            )

    def _set_state(self, action, step=1, data=None):
        UserMenuState.objects.update_or_create(
            phone_number=PHONE,
            defaults={
                'pending_action': action,
                'pending_step': step,
                'pending_data': data or {},
            },
        )

    def _content(self, response):
        return response.content.decode('utf-8')

    # ------------------------------------------------------------------ #
    # Meetings submenu: valid selections keep state and re-show submenu
    # ------------------------------------------------------------------ #

    def test_meetings_digit_1_keeps_state_and_shows_submenu(self):
        """Digit 1 in meetings_menu: result shown + submenu re-displayed + state kept."""
        self._set_state('meetings_menu')
        with patch(
            'apps.standup.views.WhatsAppWebhookView._query_meetings_msg',
            return_value='no meetings today',
        ):
            response = self._post('1')
        content = self._content(response)
        self.assertEqual(response.status_code, 200)
        # Query result must appear
        self.assertIn('no meetings today', content)
        # Submenu must be re-shown (פגישות header)
        self.assertIn('\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea', content)
        # State must still be meetings_menu
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'meetings_menu')

    def test_meetings_digit_2_keeps_state_and_shows_submenu(self):
        """Digit 2 in meetings_menu: result shown + submenu re-displayed + state kept."""
        self._set_state('meetings_menu')
        with patch(
            'apps.standup.views.WhatsAppWebhookView._query_meetings_msg',
            return_value='tomorrow meetings result',
        ):
            response = self._post('2')
        content = self._content(response)
        self.assertIn('tomorrow meetings result', content)
        self.assertIn('\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'meetings_menu')

    def test_meetings_digit_3_keeps_state_and_shows_submenu(self):
        """Digit 3 in meetings_menu: result shown + submenu re-displayed + state kept."""
        self._set_state('meetings_menu')
        with patch(
            'apps.standup.views.WhatsAppWebhookView._query_meetings_msg',
            return_value='week meetings result',
        ):
            response = self._post('3')
        content = self._content(response)
        self.assertIn('week meetings result', content)
        self.assertIn('\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'meetings_menu')

    def test_meetings_digit_4_keeps_state_and_shows_submenu(self):
        """Digit 4 in meetings_menu (next meeting): result shown + submenu re-displayed."""
        self._set_state('meetings_menu')
        with patch(
            'apps.standup.views.WhatsAppWebhookView._query_next_meeting_msg',
            return_value='next meeting result',
        ):
            response = self._post('4')
        content = self._content(response)
        self.assertIn('next meeting result', content)
        self.assertIn('\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'meetings_menu')

    def test_meetings_digit_0_returns_to_main_menu(self):
        """Digit 0 in meetings_menu: state goes to main_menu (not meetings_menu)."""
        self._set_state('meetings_menu')
        response = self._post('0')
        content = self._content(response)
        # Main menu header must appear
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'main_menu')

    def test_meetings_invalid_input_shows_error_and_submenu_state_unchanged(self):
        """Invalid input in meetings_menu: INVALID_OPTION + submenu, state unchanged."""
        self._set_state('meetings_menu')
        response = self._post('xyz')
        content = self._content(response)
        # Hebrew invalid-option string
        self.assertIn('\u05e2\u05e0\u05d4 \u05ea\u05e9\u05d5\u05d1\u05d4 \u05ea\u05e7\u05d9\u05e0\u05d4', content)
        # Submenu still shown
        self.assertIn('\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea', content)
        # State still meetings_menu
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'meetings_menu')

    # ------------------------------------------------------------------ #
    # Free-time submenu: valid selections keep state and re-show submenu
    # ------------------------------------------------------------------ #

    def test_free_time_digit_1_keeps_state_and_shows_submenu(self):
        """Digit 1 in free_time_menu: result + submenu re-shown + state kept."""
        self._set_state('free_time_menu')
        with patch(
            'apps.standup.views.WhatsAppWebhookView._query_free_time_msg',
            return_value='free slots today',
        ):
            response = self._post('1')
        content = self._content(response)
        self.assertIn('free slots today', content)
        # Free-time submenu header (זמן פנוי)
        self.assertIn('\u05d6\u05de\u05df \u05e4\u05e0\u05d5\u05d9', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'free_time_menu')

    def test_free_time_digit_2_keeps_state_and_shows_submenu(self):
        """Digit 2 in free_time_menu: result + submenu re-shown + state kept."""
        self._set_state('free_time_menu')
        with patch(
            'apps.standup.views.WhatsAppWebhookView._query_free_time_msg',
            return_value='free slots tomorrow',
        ):
            response = self._post('2')
        content = self._content(response)
        self.assertIn('free slots tomorrow', content)
        self.assertIn('\u05d6\u05de\u05df \u05e4\u05e0\u05d5\u05d9', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'free_time_menu')

    def test_free_time_digit_3_keeps_state_and_shows_submenu(self):
        """Digit 3 in free_time_menu: result + submenu re-shown + state kept."""
        self._set_state('free_time_menu')
        with patch(
            'apps.standup.views.WhatsAppWebhookView._query_free_time_msg',
            return_value='free slots week',
        ):
            response = self._post('3')
        content = self._content(response)
        self.assertIn('free slots week', content)
        self.assertIn('\u05d6\u05de\u05df \u05e4\u05e0\u05d5\u05d9', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'free_time_menu')

    def test_free_time_digit_0_returns_to_main_menu(self):
        """Digit 0 in free_time_menu: state goes to main_menu."""
        self._set_state('free_time_menu')
        response = self._post('0')
        content = self._content(response)
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'main_menu')

    def test_free_time_invalid_input_shows_error_and_submenu_state_unchanged(self):
        """Invalid input in free_time_menu: INVALID_OPTION + submenu, state unchanged."""
        self._set_state('free_time_menu')
        response = self._post('9')
        content = self._content(response)
        self.assertIn('\u05e2\u05e0\u05d4 \u05ea\u05e9\u05d5\u05d1\u05d4 \u05ea\u05e7\u05d9\u05e0\u05d4', content)
        self.assertIn('\u05d6\u05de\u05df \u05e4\u05e0\u05d5\u05d9', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'free_time_menu')

    # ------------------------------------------------------------------ #
    # Birthdays submenu: valid selections keep state and re-show submenu
    # ------------------------------------------------------------------ #

    def test_birthdays_digit_1_keeps_state_and_shows_submenu(self):
        """Digit 1 in birthdays_menu: result + submenu re-shown + state kept."""
        self._set_state('birthdays_menu')
        with patch(
            'apps.standup.views.WhatsAppWebhookView._query_birthdays_msg',
            return_value='birthdays this week',
        ):
            response = self._post('1')
        content = self._content(response)
        self.assertIn('birthdays this week', content)
        # Birthdays submenu header (ימי הולדת)
        self.assertIn('\u05d9\u05de\u05d9 \u05d4\u05d5\u05dc\u05d3\u05ea', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'birthdays_menu')

    def test_birthdays_digit_2_keeps_state_and_shows_submenu(self):
        """Digit 2 in birthdays_menu: result + submenu re-shown + state kept."""
        self._set_state('birthdays_menu')
        with patch(
            'apps.standup.views.WhatsAppWebhookView._query_birthdays_msg',
            return_value='birthdays this month',
        ):
            response = self._post('2')
        content = self._content(response)
        self.assertIn('birthdays this month', content)
        self.assertIn('\u05d9\u05de\u05d9 \u05d4\u05d5\u05dc\u05d3\u05ea', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'birthdays_menu')

    def test_birthdays_digit_0_returns_to_main_menu(self):
        """Digit 0 in birthdays_menu: state goes to main_menu."""
        self._set_state('birthdays_menu')
        response = self._post('0')
        content = self._content(response)
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'main_menu')

    def test_birthdays_invalid_input_shows_error_and_submenu_state_unchanged(self):
        """Invalid input in birthdays_menu: INVALID_OPTION + submenu, state unchanged."""
        self._set_state('birthdays_menu')
        response = self._post('5')
        content = self._content(response)
        self.assertIn('\u05e2\u05e0\u05d4 \u05ea\u05e9\u05d5\u05d1\u05d4 \u05ea\u05e7\u05d9\u05e0\u05d4', content)
        self.assertIn('\u05d9\u05de\u05d9 \u05d4\u05d5\u05dc\u05d3\u05ea', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'birthdays_menu')

    # ------------------------------------------------------------------ #
    # Multi-turn flow: user can make multiple selections without leaving
    # ------------------------------------------------------------------ #

    def test_meetings_multi_turn_stays_in_submenu(self):
        """
        Simulate multiple back-to-back selections in meetings_menu.
        After each selection the state must remain meetings_menu.
        """
        self._set_state('meetings_menu')
        for digit, period in [('1', 'today'), ('2', 'tomorrow'), ('3', 'this week')]:
            with patch(
                'apps.standup.views.WhatsAppWebhookView._query_meetings_msg',
                return_value=f'result for {period}',
            ):
                response = self._post(digit)
            self.assertEqual(response.status_code, 200)
            state = UserMenuState.objects.get(phone_number=PHONE)
            self.assertEqual(
                state.pending_action,
                'meetings_menu',
                msg=f'After digit {digit!r} state should still be meetings_menu',
            )

    def test_meetings_then_zero_exits_submenu(self):
        """
        After one valid selection (stays in submenu), sending 0 exits to main_menu.
        """
        self._set_state('meetings_menu')
        # First valid selection
        with patch(
            'apps.standup.views.WhatsAppWebhookView._query_meetings_msg',
            return_value='result',
        ):
            self._post('1')
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'meetings_menu')

        # Now send 0 to exit
        response = self._post('0')
        content = self._content(response)
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'main_menu')
