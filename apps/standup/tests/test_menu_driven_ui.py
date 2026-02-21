"""
TZA-110: Tests for the fully menu-driven WhatsApp bot.
TZA-126: Verified that schedule cancel/confirm tests pass after TZA-120 fix.

Covers:
  - Root level: any text from connected user -> main menu
  - Root level: any text from unconnected user -> onboarding
  - Numbered submenu: invalid digit -> INVALID_OPTION + re-show menu
  - Numbered submenu: 0 -> return to main menu state
  - Schedule flow: date validation
  - Schedule flow: time validation (HH:MM only)
  - Schedule flow: title empty check
  - Schedule flow: cancel at any step with '0' or 'batel'
  - Schedule flow: happy path (mocked create_event)
  - Settings: timezone selection
  - Settings: digest time setting
"""
import datetime
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.calendar_bot.models import CalendarToken, UserMenuState

PATCH_PERMISSION = patch(
    'apps.standup.permissions.TwilioSignaturePermission.has_permission',
    return_value=True,
)

PHONE = 'whatsapp:+972501234567'


@override_settings(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
    WEBHOOK_BASE_URL='https://example.com',
)
class MenuDrivenUITests(TestCase):
    """
    Base class: creates a connected user (CalendarToken) and clears state.
    """

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')
        # Create a connected CalendarToken
        self.token = CalendarToken.objects.create(
            phone_number=PHONE,
            account_email='test@example.com',
            access_token='fake_access',
            refresh_token='fake_refresh',
            timezone='Asia/Jerusalem',
        )
        # Ensure no leftover state
        UserMenuState.objects.filter(phone_number=PHONE).delete()

    def _post(self, body, phone=PHONE):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url,
                data={'From': phone, 'Body': body},
                format='multipart',
            )

    def _content(self, response):
        return response.content.decode('utf-8')

    # ----------------------------------------------------------------------- #
    # Root level tests
    # ----------------------------------------------------------------------- #

    def test_root_any_text_returns_main_menu(self):
        """Connected user sending any text at root -> main menu."""
        response = self._post('\u05e9\u05dc\u05d5\u05dd')
        self.assertEqual(response.status_code, 200)
        content = self._content(response)
        # Main menu contains the Hebrew menu header
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)

    def test_root_english_text_returns_main_menu(self):
        """Connected user sending English -> main menu (no English error)."""
        response = self._post('hello world')
        self.assertEqual(response.status_code, 200)
        content = self._content(response)
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)

    def test_root_random_digits_returns_main_menu(self):
        """Unrecognised digits at root show main menu."""
        response = self._post('999')
        self.assertEqual(response.status_code, 200)
        content = self._content(response)
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)

    def test_root_sets_main_menu_state(self):
        """After root shows main menu, state is set to 'main_menu'."""
        self._post('\u05e9\u05dc\u05d5\u05dd')
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'main_menu')

    def test_main_menu_digit_1_enters_meetings_submenu(self):
        """After seeing main menu, digit '1' enters meetings submenu."""
        # Set state to main_menu as if user just saw the main menu
        UserMenuState.objects.create(
            phone_number=PHONE, pending_action='main_menu', pending_step=1, pending_data={}
        )
        response = self._post('1')
        content = self._content(response)
        self.assertEqual(response.status_code, 200)
        self.assertIn('\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea', content)  # meetings menu
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'meetings_menu')

    def test_main_menu_digit_3_enters_schedule_flow(self):
        """After main menu, digit '3' enters schedule flow."""
        UserMenuState.objects.create(
            phone_number=PHONE, pending_action='main_menu', pending_step=1, pending_data={}
        )
        response = self._post('3')
        content = self._content(response)
        self.assertEqual(response.status_code, 200)
        # Should show the date prompt
        self.assertIn('\u05de\u05ea\u05d9', content)  # 'when?' prompt
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'schedule')
        self.assertEqual(state.pending_step, 1)

    def test_main_menu_digit_5_enters_settings(self):
        """After main menu, digit '5' enters settings."""
        UserMenuState.objects.create(
            phone_number=PHONE, pending_action='main_menu', pending_step=1, pending_data={}
        )
        response = self._post('5')
        content = self._content(response)
        self.assertIn('\u05d4\u05d2\u05d3\u05e8\u05d5\u05ea', content)  # settings
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'settings_menu')

    # ----------------------------------------------------------------------- #
    # Meetings submenu tests
    # ----------------------------------------------------------------------- #

    def test_meetings_submenu_invalid_input_shows_error_and_menu(self):
        """Inside meetings submenu, invalid input -> INVALID_OPTION + re-show menu."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='meetings_menu',
            pending_step=1,
            pending_data={},
        )
        response = self._post('abc')
        content = self._content(response)
        self.assertEqual(response.status_code, 200)
        self.assertIn('\u05e2\u05e0\u05d4 \u05ea\u05e9\u05d5\u05d1\u05d4 \u05ea\u05e7\u05d9\u05e0\u05d4', content)
        self.assertIn('\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea', content)  # meetings menu re-shown
        # State must still be meetings_menu
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'meetings_menu')

    def test_meetings_submenu_digit_0_returns_to_main_menu_state(self):
        """Inside meetings submenu, '0' returns to main menu state."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='meetings_menu',
            pending_step=1,
            pending_data={},
        )
        response = self._post('0')
        content = self._content(response)
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)
        # State should be main_menu now
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'main_menu')

    def test_meetings_submenu_digit_1_queries_today(self):
        """Meetings submenu '1' calls _query_meetings_msg with 'today'."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='meetings_menu',
            pending_step=1,
            pending_data={},
        )
        with patch.object(
            __import__('apps.standup.views', fromlist=['WhatsAppWebhookView']).WhatsAppWebhookView,
            '_query_meetings_msg',
            return_value='today meetings',
        ) as mock_q:
            response = self._post('1')
            mock_q.assert_called_once_with(PHONE, 'today')
        self.assertEqual(response.status_code, 200)

    def test_meetings_submenu_digit_4_queries_next_meeting(self):
        """Meetings submenu '4' calls _query_next_meeting_msg."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='meetings_menu',
            pending_step=1,
            pending_data={},
        )
        with patch.object(
            __import__('apps.standup.views', fromlist=['WhatsAppWebhookView']).WhatsAppWebhookView,
            '_query_next_meeting_msg',
            return_value='next meeting',
        ) as mock_q:
            response = self._post('4')
            mock_q.assert_called_once_with(PHONE)
        self.assertEqual(response.status_code, 200)

    # ----------------------------------------------------------------------- #
    # Schedule flow tests
    # ----------------------------------------------------------------------- #

    def test_schedule_invalid_date_reprompts(self):
        """Schedule step 1: invalid date -> INVALID_OPTION + re-prompt."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='schedule',
            pending_step=1,
            pending_data={},
        )
        response = self._post('not-a-date')
        content = self._content(response)
        self.assertIn('\u05e2\u05e0\u05d4 \u05ea\u05e9\u05d5\u05d1\u05d4 \u05ea\u05e7\u05d9\u05e0\u05d4', content)
        # Still on step 1
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_step, 1)

    def test_schedule_valid_date_today_advances(self):
        """Schedule step 1: Hebrew 'today' is valid -> advance to step 2."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='schedule',
            pending_step=1,
            pending_data={},
        )
        response = self._post('\u05d4\u05d9\u05d5\u05dd')  # 'today' in Hebrew
        content = self._content(response)
        self.assertIn('HH:MM', content)  # step 2 prompt
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_step, 2)

    def test_schedule_valid_date_ddmm_advances(self):
        """Schedule step 1: DD/MM format is valid."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='schedule',
            pending_step=1,
            pending_data={},
        )
        response = self._post('15/08')
        content = self._content(response)
        self.assertIn('HH:MM', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_step, 2)

    def test_schedule_invalid_start_time_reprompts(self):
        """Schedule step 2: invalid time -> INVALID_OPTION + re-prompt."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='schedule',
            pending_step=2,
            pending_data={'date': '2026-08-15'},
        )
        response = self._post('25:99')  # invalid
        content = self._content(response)
        self.assertIn('\u05e2\u05e0\u05d4 \u05ea\u05e9\u05d5\u05d1\u05d4 \u05ea\u05e7\u05d9\u05e0\u05d4', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_step, 2)

    def test_schedule_valid_start_time_advances(self):
        """Schedule step 2: valid HH:MM -> advance to step 3."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='schedule',
            pending_step=2,
            pending_data={'date': '2026-08-15'},
        )
        response = self._post('09:30')
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_step, 3)
        self.assertEqual(state.pending_data['start'], '09:30')

    def test_schedule_end_time_before_start_reprompts(self):
        """Schedule step 3: end <= start -> INVALID_OPTION + re-prompt."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='schedule',
            pending_step=3,
            pending_data={'date': '2026-08-15', 'start': '10:00'},
        )
        response = self._post('09:00')  # before start
        content = self._content(response)
        self.assertIn('\u05e2\u05e0\u05d4 \u05ea\u05e9\u05d5\u05d1\u05d4 \u05ea\u05e7\u05d9\u05e0\u05d4', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_step, 3)

    def test_schedule_empty_title_reprompts(self):
        """Schedule step 4: empty title -> INVALID_OPTION + re-prompt."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='schedule',
            pending_step=4,
            pending_data={'date': '2026-08-15', 'start': '09:00', 'end': '10:00'},
        )
        response = self._post('   ')  # whitespace only
        content = self._content(response)
        self.assertIn('\u05e2\u05e0\u05d4 \u05ea\u05e9\u05d5\u05d1\u05d4 \u05ea\u05e7\u05d9\u05e0\u05d4', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_step, 4)

    def test_schedule_valid_title_advances(self):
        """Schedule step 4: non-empty title -> advance to step 5."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='schedule',
            pending_step=4,
            pending_data={'date': '2026-08-15', 'start': '09:00', 'end': '10:00'},
        )
        response = self._post('\u05e4\u05d2\u05d9\u05e9\u05ea \u05e6\u05d5\u05d5\u05ea')
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_step, 5)
        self.assertEqual(state.pending_data['title'], '\u05e4\u05d2\u05d9\u05e9\u05ea \u05e6\u05d5\u05d5\u05ea')

    def test_schedule_skip_description(self):
        """Step 5: 'daleg' skips description."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='schedule',
            pending_step=5,
            pending_data={'date': '2026-08-15', 'start': '09:00', 'end': '10:00', 'title': 'T'},
        )
        response = self._post('\u05d3\u05dc\u05d2')  # skip
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_step, 6)
        self.assertIsNone(state.pending_data.get('description'))

    def test_schedule_skip_location(self):
        """Step 6: 'daleg' skips location and shows confirmation."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='schedule',
            pending_step=6,
            pending_data={
                'date': '2026-08-15', 'start': '09:00', 'end': '10:00',
                'title': 'T', 'description': None,
            },
        )
        response = self._post('\u05d3\u05dc\u05d2')  # skip
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_step, 7)
        content = self._content(response)
        # Summary should include the confirm/cancel prompts
        self.assertIn('\u05d0\u05e9\u05e8', content)
        self.assertIn('\u05d1\u05d8\u05dc', content)

    def test_schedule_cancel_at_step_1_with_0(self):
        """'0' at any schedule step -> cancel, return MAIN_MENU_TEXT, state='main_menu'.

        TZA-120 fix (verified by TZA-126): state must be set to 'main_menu' (not
        deleted) so that the very next inbound message is routed via
        _handle_main_menu_pick and the bot remains fully responsive.
        """
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='schedule',
            pending_step=1,
            pending_data={},
        )
        response = self._post('0')
        content = self._content(response)
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)
        # State row must exist with pending_action='main_menu'
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'main_menu')

    def test_schedule_cancel_at_step_4_with_batel(self):
        """'batel' at step 4 -> cancel, return MAIN_MENU_TEXT, state='main_menu'.

        TZA-120 fix (verified by TZA-126): state must be 'main_menu', not deleted.
        """
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='schedule',
            pending_step=4,
            pending_data={'date': '2026-08-15', 'start': '09:00', 'end': '10:00'},
        )
        response = self._post('\u05d1\u05d8\u05dc')  # batel
        content = self._content(response)
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)
        # State row must exist with pending_action='main_menu'
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'main_menu')

    def test_schedule_happy_path_confirm(self):
        """Full schedule flow: 'asher' creates event, returns success, state='main_menu'.

        TZA-120 fix (verified by TZA-126): after a successful event creation the
        state is set to 'main_menu' (not deleted) so the bot stays responsive.
        """
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='schedule',
            pending_step=7,
            pending_data={
                'date': '2026-08-15',
                'start': '09:00',
                'end': '10:00',
                'title': '\u05e4\u05d2\u05d9\u05e9\u05ea \u05e6\u05d5\u05d5\u05ea',
                'description': None,
                'location': None,
            },
        )
        with patch(
            'apps.calendar_bot.calendar_service.create_event',
            return_value=(True, 'fake_event_id'),
        ):
            response = self._post('\u05d0\u05e9\u05e8')  # asher
        content = self._content(response)
        self.assertEqual(response.status_code, 200)
        self.assertIn('\u05d4\u05e4\u05d2\u05d9\u05e9\u05d4 \u05e0\u05e7\u05d1\u05e2\u05d4 \u05d1\u05d4\u05e6\u05dc\u05d7\u05d4', content)
        # State row must exist with pending_action='main_menu'
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'main_menu')

    def test_schedule_api_error_returns_error_message(self):
        """Schedule flow: API error -> Hebrew error message + main menu, state='main_menu'.

        TZA-120 fix (verified by TZA-126): state is 'main_menu', not deleted.
        """
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='schedule',
            pending_step=7,
            pending_data={
                'date': '2026-08-15',
                'start': '09:00',
                'end': '10:00',
                'title': '\u05e4\u05d2\u05d9\u05e9\u05d4',
                'description': None,
                'location': None,
            },
        )
        with patch(
            'apps.calendar_bot.calendar_service.create_event',
            return_value=(False, 'api_error'),
        ):
            response = self._post('\u05d0\u05e9\u05e8')  # asher
        content = self._content(response)
        self.assertIn('\u05e9\u05d2\u05d9\u05d0\u05d4', content)
        # State row must exist with pending_action='main_menu'
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'main_menu')

    # ----------------------------------------------------------------------- #
    # Settings: timezone
    # ----------------------------------------------------------------------- #

    def test_settings_timezone_selection_sets_tz(self):
        """Settings > Timezone: digit 1 sets Asia/Jerusalem."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='timezone_menu',
            pending_step=1,
            pending_data={},
        )
        response = self._post('1')
        content = self._content(response)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Asia/Jerusalem', content)
        self.token.refresh_from_db()
        self.assertEqual(self.token.timezone, 'Asia/Jerusalem')

    def test_settings_timezone_invalid_option(self):
        """Settings > Timezone: invalid digit -> INVALID_OPTION + re-show menu."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='timezone_menu',
            pending_step=1,
            pending_data={},
        )
        response = self._post('9')
        content = self._content(response)
        self.assertIn('\u05e2\u05e0\u05d4 \u05ea\u05e9\u05d5\u05d1\u05d4 \u05ea\u05e7\u05d9\u05e0\u05d4', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'timezone_menu')

    def test_settings_timezone_0_returns_to_settings(self):
        """Settings > Timezone: '0' returns to settings menu."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='timezone_menu',
            pending_step=1,
            pending_data={},
        )
        response = self._post('0')
        content = self._content(response)
        self.assertIn('\u05d4\u05d2\u05d3\u05e8\u05d5\u05ea', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'settings_menu')

    # ----------------------------------------------------------------------- #
    # Settings: digest time
    # ----------------------------------------------------------------------- #

    def test_settings_digest_valid_time_sets_digest(self):
        """Settings > Digest: valid HH:MM sets digest time."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='digest_prompt',
            pending_step=1,
            pending_data={},
        )
        response = self._post('07:30')
        content = self._content(response)
        self.assertIn('07:30', content)
        self.token.refresh_from_db()
        self.assertEqual(self.token.digest_hour, 7)
        self.assertEqual(self.token.digest_minute, 30)

    def test_settings_digest_invalid_time_reprompts(self):
        """Settings > Digest: invalid time -> error + re-prompt."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='digest_prompt',
            pending_step=1,
            pending_data={},
        )
        response = self._post('25:00')
        content = self._content(response)
        self.assertIn('\u05e9\u05e2\u05d4 \u05dc\u05d0 \u05ea\u05e7\u05d9\u05e0\u05d4', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'digest_prompt')

    # ----------------------------------------------------------------------- #
    # Free time submenu
    # ----------------------------------------------------------------------- #

    def test_free_time_submenu_invalid_option(self):
        """Free time submenu: invalid input -> INVALID_OPTION + re-show menu."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='free_time_menu',
            pending_step=1,
            pending_data={},
        )
        response = self._post('x')
        content = self._content(response)
        self.assertIn('\u05e2\u05e0\u05d4 \u05ea\u05e9\u05d5\u05d1\u05d4 \u05ea\u05e7\u05d9\u05e0\u05d4', content)
        self.assertIn('\u05d6\u05de\u05df \u05e4\u05e0\u05d5\u05d9', content)

    def test_free_time_submenu_0_returns_main_menu_state(self):
        """Free time submenu: '0' returns to main_menu state."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='free_time_menu',
            pending_step=1,
            pending_data={},
        )
        response = self._post('0')
        content = self._content(response)
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, 'main_menu')

    # ----------------------------------------------------------------------- #
    # Birthdays submenu
    # ----------------------------------------------------------------------- #

    def test_birthdays_submenu_invalid_option(self):
        """Birthdays submenu: invalid input -> error + re-show menu."""
        UserMenuState.objects.create(
            phone_number=PHONE,
            pending_action='birthdays_menu',
            pending_step=1,
            pending_data={},
        )
        response = self._post('5')
        content = self._content(response)
        self.assertIn('\u05e2\u05e0\u05d4 \u05ea\u05e9\u05d5\u05d1\u05d4 \u05ea\u05e7\u05d9\u05e0\u05d4', content)
        self.assertIn('\u05d9\u05de\u05d9 \u05d4\u05d5\u05dc\u05d3\u05ea', content)

    # ----------------------------------------------------------------------- #
    # Unconnected user
    # ----------------------------------------------------------------------- #

    def test_unconnected_user_gets_onboarding(self):
        """User with no connected calendar gets onboarding greeting."""
        CalendarToken.objects.filter(phone_number=PHONE).delete()
        response = self._post('\u05e9\u05dc\u05d5\u05dd')
        content = self._content(response)
        self.assertEqual(response.status_code, 200)
        # Should get the Hebrew greeting asking for name
        self.assertIn('\u05d4\u05d9\u05d9', content)
        self.assertIn('\u05de\u05d4 \u05e9\u05de\u05da', content)

    # ----------------------------------------------------------------------- #
    # Helper
    # ----------------------------------------------------------------------- #

    @staticmethod
    def _make_xml(text):
        from django.http import HttpResponse
        from twilio.twiml.messaging_response import MessagingResponse
        resp = MessagingResponse()
        resp.message(text)
        return HttpResponse(str(resp), content_type='application/xml')


@override_settings(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
)
class DateTimeValidationTests(TestCase):
    """Unit tests for date/time parsing helpers."""

    def test_parse_date_today(self):
        import pytz
        from apps.standup.views import _parse_date_input
        tz = pytz.timezone('Asia/Jerusalem')
        today = datetime.datetime.now(tz=tz).date()
        self.assertEqual(_parse_date_input('\u05d4\u05d9\u05d5\u05dd', tz), today)

    def test_parse_date_tomorrow(self):
        import pytz
        from apps.standup.views import _parse_date_input
        tz = pytz.timezone('Asia/Jerusalem')
        today = datetime.datetime.now(tz=tz).date()
        self.assertEqual(_parse_date_input('\u05de\u05d7\u05e8', tz), today + datetime.timedelta(days=1))

    def test_parse_date_ddmm(self):
        import pytz
        from apps.standup.views import _parse_date_input
        tz = pytz.timezone('Asia/Jerusalem')
        d = _parse_date_input('15/08', tz)
        self.assertIsNotNone(d)
        self.assertEqual(d.day, 15)
        self.assertEqual(d.month, 8)

    def test_parse_date_ddmmyyyy(self):
        import pytz
        from apps.standup.views import _parse_date_input
        tz = pytz.timezone('Asia/Jerusalem')
        d = _parse_date_input('15/08/2027', tz)
        self.assertEqual(d, datetime.date(2027, 8, 15))

    def test_parse_date_invalid(self):
        import pytz
        from apps.standup.views import _parse_date_input
        tz = pytz.timezone('Asia/Jerusalem')
        self.assertIsNone(_parse_date_input('not-a-date', tz))
        self.assertIsNone(_parse_date_input('32/01', tz))
        self.assertIsNone(_parse_date_input('', tz))

    def test_parse_time_valid(self):
        from apps.standup.views import _parse_time_hhmm
        self.assertEqual(_parse_time_hhmm('09:30'), (9, 30))
        self.assertEqual(_parse_time_hhmm('9:30'), (9, 30))  # single digit hour ok
        self.assertEqual(_parse_time_hhmm('00:00'), (0, 0))
        self.assertEqual(_parse_time_hhmm('23:59'), (23, 59))

    def test_parse_time_invalid(self):
        from apps.standup.views import _parse_time_hhmm
        self.assertIsNone(_parse_time_hhmm('24:00'))
        self.assertIsNone(_parse_time_hhmm('9:30am'))  # must be 24h HH:MM format
        self.assertIsNone(_parse_time_hhmm('abc'))
        self.assertIsNone(_parse_time_hhmm(''))
        self.assertIsNone(_parse_time_hhmm('25:99'))
