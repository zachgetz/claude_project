"""
TZA-120: Bot becomes unresponsive after pressing 0 to return to main menu.

These tests verify the complete round-trip:
  1. Enter a submenu (or schedule flow)
  2. Press 0 (or batel) to return
  3. Immediately send ANOTHER message and verify the bot responds correctly
     (shows the correct submenu or processes the digit).

The key invariant being tested: after any cancel/back action, the state
must be set to 'main_menu' (not cleared entirely), so the very next inbound
message is routed by _handle_main_menu_pick and the bot stays fully responsive.
"""
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.calendar_bot.models import CalendarToken, UserMenuState

PATCH_PERMISSION = patch(
    'apps.standup.permissions.TwilioSignaturePermission.has_permission',
    return_value=True,
)

PHONE = 'whatsapp:+972509999001'


@override_settings(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
    WEBHOOK_BASE_URL='https://example.com',
)
class ReturnToMenuAfterZeroTests(TestCase):
    """
    Verifies that after pressing 0 from any submenu, the bot remains
    fully responsive and correctly processes the next inbound message.
    """

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')
        CalendarToken.objects.create(
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

    def _content(self, response):
        return response.content.decode('utf-8')

    def _assert_state(self, expected_action):
        state = UserMenuState.objects.get(phone_number=PHONE)
        self.assertEqual(state.pending_action, expected_action)

    # ----------------------------------------------------------------------- #
    # meetings_menu -> 0 -> next message is processed from main_menu state
    # ----------------------------------------------------------------------- #

    def test_meetings_menu_zero_then_digit_shows_submenu(self):
        """After pressing 0 from meetings_menu, pressing 1 shows meetings submenu."""
        UserMenuState.objects.update_or_create(
            phone_number=PHONE,
            defaults={'pending_action': 'meetings_menu', 'pending_step': 1, 'pending_data': {}},
        )
        # Press 0 -> main menu shown
        r = self._post('0')
        self.assertEqual(r.status_code, 200)
        self._assert_state('main_menu')

        # Immediately send 1 -> should enter meetings submenu (not show main menu again)
        r2 = self._post('1')
        self.assertEqual(r2.status_code, 200)
        content = self._content(r2)
        # The meetings submenu must be shown (Hebrew: \u05e4\u05d2\u05d9\u05e9\u05d5\u05ea)
        self.assertIn('\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea', content)
        self._assert_state('meetings_menu')

    def test_meetings_menu_zero_state_is_main_menu(self):
        """After pressing 0 from meetings_menu, state.pending_action == 'main_menu'."""
        UserMenuState.objects.update_or_create(
            phone_number=PHONE,
            defaults={'pending_action': 'meetings_menu', 'pending_step': 1, 'pending_data': {}},
        )
        self._post('0')
        self._assert_state('main_menu')

    # ----------------------------------------------------------------------- #
    # free_time_menu -> 0 -> next message is processed from main_menu state
    # ----------------------------------------------------------------------- #

    def test_free_time_menu_zero_then_digit_shows_submenu(self):
        """After pressing 0 from free_time_menu, pressing 2 shows free-time submenu."""
        UserMenuState.objects.update_or_create(
            phone_number=PHONE,
            defaults={'pending_action': 'free_time_menu', 'pending_step': 1, 'pending_data': {}},
        )
        self._post('0')
        self._assert_state('main_menu')

        r2 = self._post('2')
        self.assertEqual(r2.status_code, 200)
        content = self._content(r2)
        # Free time submenu must be shown (Hebrew: \u05d6\u05de\u05df \u05e4\u05e0\u05d5\u05d9)
        self.assertIn('\u05d6\u05de\u05df \u05e4\u05e0\u05d5\u05d9', content)
        self._assert_state('free_time_menu')

    # ----------------------------------------------------------------------- #
    # birthdays_menu -> 0 -> next message is processed from main_menu state
    # ----------------------------------------------------------------------- #

    def test_birthdays_menu_zero_then_digit_shows_submenu(self):
        """After pressing 0 from birthdays_menu, pressing 4 shows birthdays submenu."""
        UserMenuState.objects.update_or_create(
            phone_number=PHONE,
            defaults={'pending_action': 'birthdays_menu', 'pending_step': 1, 'pending_data': {}},
        )
        self._post('0')
        self._assert_state('main_menu')

        r2 = self._post('4')
        self.assertEqual(r2.status_code, 200)
        content = self._content(r2)
        # Birthdays submenu must be shown (Hebrew: \u05d9\u05de\u05d9 \u05d4\u05d5\u05dc\u05d3\u05ea)
        self.assertIn('\u05d9\u05de\u05d9 \u05d4\u05d5\u05dc\u05d3\u05ea', content)
        self._assert_state('birthdays_menu')

    # ----------------------------------------------------------------------- #
    # settings_menu -> 0 -> next message is processed from main_menu state
    # ----------------------------------------------------------------------- #

    def test_settings_menu_zero_then_digit_shows_submenu(self):
        """After pressing 0 from settings_menu, pressing 5 shows settings submenu."""
        UserMenuState.objects.update_or_create(
            phone_number=PHONE,
            defaults={'pending_action': 'settings_menu', 'pending_step': 1, 'pending_data': {}},
        )
        self._post('0')
        self._assert_state('main_menu')

        r2 = self._post('5')
        self.assertEqual(r2.status_code, 200)
        content = self._content(r2)
        # Settings submenu must be shown (Hebrew: \u05d4\u05d2\u05d3\u05e8\u05d5\u05ea)
        self.assertIn('\u05d4\u05d2\u05d3\u05e8\u05d5\u05ea', content)
        self._assert_state('settings_menu')

    # ----------------------------------------------------------------------- #
    # Schedule flow: cancel with 0 at step 1
    # ----------------------------------------------------------------------- #

    def test_schedule_cancel_step1_with_0_then_digit_shows_submenu(self):
        """Cancel schedule at step 1 with 0 -> state main_menu -> next digit works."""
        UserMenuState.objects.update_or_create(
            phone_number=PHONE,
            defaults={'pending_action': 'schedule', 'pending_step': 1, 'pending_data': {}},
        )
        r = self._post('0')
        self.assertEqual(r.status_code, 200)
        # State must be main_menu (not deleted)
        self._assert_state('main_menu')

        # Next message: pick option 1 (meetings)
        r2 = self._post('1')
        content = self._content(r2)
        self.assertIn('\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea', content)
        self._assert_state('meetings_menu')

    def test_schedule_cancel_step1_with_0_state_is_main_menu(self):
        """Cancel schedule (step 1) with 0: state row exists with action='main_menu'."""
        UserMenuState.objects.update_or_create(
            phone_number=PHONE,
            defaults={'pending_action': 'schedule', 'pending_step': 1, 'pending_data': {}},
        )
        self._post('0')
        # Row must still exist (not be deleted)
        self.assertTrue(UserMenuState.objects.filter(phone_number=PHONE).exists())
        self._assert_state('main_menu')

    # ----------------------------------------------------------------------- #
    # Schedule flow: cancel with batel at step 3
    # ----------------------------------------------------------------------- #

    def test_schedule_cancel_step3_with_batel_state_is_main_menu(self):
        """Cancel schedule (step 3) with batel: state is 'main_menu'."""
        UserMenuState.objects.update_or_create(
            phone_number=PHONE,
            defaults={
                'pending_action': 'schedule',
                'pending_step': 3,
                'pending_data': {'date': '2026-08-15', 'start': '09:00'},
            },
        )
        self._post('\u05d1\u05d8\u05dc')  # batel
        self.assertTrue(UserMenuState.objects.filter(phone_number=PHONE).exists())
        self._assert_state('main_menu')

    def test_schedule_cancel_step3_then_digit_shows_submenu(self):
        """Cancel schedule (step 3) with batel -> next digit 1 shows meetings."""
        UserMenuState.objects.update_or_create(
            phone_number=PHONE,
            defaults={
                'pending_action': 'schedule',
                'pending_step': 3,
                'pending_data': {'date': '2026-08-15', 'start': '09:00'},
            },
        )
        self._post('\u05d1\u05d8\u05dc')  # batel
        r2 = self._post('1')
        content = self._content(r2)
        self.assertIn('\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea', content)
        self._assert_state('meetings_menu')

    # ----------------------------------------------------------------------- #
    # Schedule flow: step 7 batel -> state is main_menu
    # ----------------------------------------------------------------------- #

    def test_schedule_step7_batel_state_is_main_menu(self):
        """At confirm step (7), pressing batel sets state to main_menu."""
        UserMenuState.objects.update_or_create(
            phone_number=PHONE,
            defaults={
                'pending_action': 'schedule',
                'pending_step': 7,
                'pending_data': {
                    'date': '2026-08-15', 'start': '09:00', 'end': '10:00',
                    'title': 'Test', 'description': None, 'location': None,
                },
            },
        )
        self._post('\u05d1\u05d8\u05dc')  # batel
        self.assertTrue(UserMenuState.objects.filter(phone_number=PHONE).exists())
        self._assert_state('main_menu')

    def test_schedule_step7_batel_then_digit_shows_submenu(self):
        """After step-7 batel, pressing 1 shows meetings submenu (bot responsive)."""
        UserMenuState.objects.update_or_create(
            phone_number=PHONE,
            defaults={
                'pending_action': 'schedule',
                'pending_step': 7,
                'pending_data': {
                    'date': '2026-08-15', 'start': '09:00', 'end': '10:00',
                    'title': 'Test', 'description': None, 'location': None,
                },
            },
        )
        self._post('\u05d1\u05d8\u05dc')  # batel
        r2 = self._post('1')
        content = self._content(r2)
        self.assertIn('\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea', content)
        self._assert_state('meetings_menu')

    # ----------------------------------------------------------------------- #
    # Schedule flow: step 7 asher (success) -> state is main_menu
    # ----------------------------------------------------------------------- #

    def test_schedule_step7_asher_success_state_is_main_menu(self):
        """After successful schedule creation (asher), state is 'main_menu'."""
        UserMenuState.objects.update_or_create(
            phone_number=PHONE,
            defaults={
                'pending_action': 'schedule',
                'pending_step': 7,
                'pending_data': {
                    'date': '2026-08-15', 'start': '09:00', 'end': '10:00',
                    'title': 'Test meeting', 'description': None, 'location': None,
                },
            },
        )
        with patch(
            'apps.calendar_bot.calendar_service.create_event',
            return_value=(True, 'fake_event_id'),
        ):
            self._post('\u05d0\u05e9\u05e8')  # asher
        self.assertTrue(UserMenuState.objects.filter(phone_number=PHONE).exists())
        self._assert_state('main_menu')

    def test_schedule_step7_asher_success_then_digit_shows_submenu(self):
        """After successful schedule creation, next digit 1 shows meetings submenu."""
        UserMenuState.objects.update_or_create(
            phone_number=PHONE,
            defaults={
                'pending_action': 'schedule',
                'pending_step': 7,
                'pending_data': {
                    'date': '2026-08-15', 'start': '09:00', 'end': '10:00',
                    'title': 'Test meeting', 'description': None, 'location': None,
                },
            },
        )
        with patch(
            'apps.calendar_bot.calendar_service.create_event',
            return_value=(True, 'fake_event_id'),
        ):
            self._post('\u05d0\u05e9\u05e8')  # asher
        r2 = self._post('1')
        content = self._content(r2)
        self.assertIn('\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea', content)
        self._assert_state('meetings_menu')

    # ----------------------------------------------------------------------- #
    # Schedule flow: step 7 asher (api error) -> state is main_menu
    # ----------------------------------------------------------------------- #

    def test_schedule_step7_asher_api_error_state_is_main_menu(self):
        """After schedule creation API error (asher), state is 'main_menu'."""
        UserMenuState.objects.update_or_create(
            phone_number=PHONE,
            defaults={
                'pending_action': 'schedule',
                'pending_step': 7,
                'pending_data': {
                    'date': '2026-08-15', 'start': '09:00', 'end': '10:00',
                    'title': 'Test meeting', 'description': None, 'location': None,
                },
            },
        )
        with patch(
            'apps.calendar_bot.calendar_service.create_event',
            return_value=(False, 'api_error'),
        ):
            self._post('\u05d0\u05e9\u05e8')  # asher
        self.assertTrue(UserMenuState.objects.filter(phone_number=PHONE).exists())
        self._assert_state('main_menu')

    # ----------------------------------------------------------------------- #
    # Full end-to-end scenario: menu -> submenu -> 0 -> next pick works
    # ----------------------------------------------------------------------- #

    def test_full_flow_root_to_submenu_to_zero_to_submenu(self):
        """
        Full scenario mirroring the bug report:
        1. Send any message -> main menu
        2. Press 1 -> meetings submenu
        3. Press 0 -> main menu (state = main_menu)
        4. Press 1 -> meetings submenu shown (NOT main menu again)
        """
        # Step 1: root message -> main menu
        r1 = self._post('\u05e9\u05dc\u05d5\u05dd')  # shalom
        self.assertEqual(r1.status_code, 200)
        self._assert_state('main_menu')

        # Step 2: press 1 -> meetings submenu
        r2 = self._post('1')
        self.assertEqual(r2.status_code, 200)
        self._assert_state('meetings_menu')

        # Step 3: press 0 -> back to main menu
        r3 = self._post('0')
        self.assertEqual(r3.status_code, 200)
        self._assert_state('main_menu')

        # Step 4: press 1 -> should immediately show meetings submenu
        r4 = self._post('1')
        self.assertEqual(r4.status_code, 200)
        content = self._content(r4)
        self.assertIn('\u05e4\u05d2\u05d9\u05e9\u05d5\u05ea', content)
        self._assert_state('meetings_menu')
