"""
Unit tests for calendar-bot commands handled in apps.standup.views.WhatsAppWebhookView.

Updated for TZA-112: The bot was redesigned (TZA-110) to a fully menu-driven Hebrew UI.
All old English text commands (set timezone, set digest, block, today, help, etc.) have
been replaced by numbered-digit navigation.  These tests exercise the new menu-driven
flow by injecting the appropriate UserMenuState before sending each POST request.

Tests still covered:
  - Timezone selection via Settings > Timezone submenu
  - Digest time prompt via Settings > Digest submenu
  - Day queries routed via Meetings submenu
  - Next-meeting query via Meetings submenu
  - Free-time query via Free-time submenu
  - Help text returned on main_menu digit "6"
  - Unconnected user receives onboarding greeting
  - Block text commands are no longer handled; connected users see main menu

The TwilioSignaturePermission is patched out for all tests.
Updated for TZA-78 multi-account: _make_token includes account_email.
"""
import datetime
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.calendar_bot.models import CalendarToken, PendingBlockConfirmation, UserMenuState
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


def _make_token(phone='whatsapp:+1234567890', tz='America/New_York', email='test@example.com'):
    return CalendarToken.objects.create(
        phone_number=phone,
        account_email=email,
        access_token='access_abc',
        refresh_token='refresh_xyz',
        timezone=tz,
    )


@override_settings(**TWILIO_SETTINGS)
class SetTimezoneCommandTests(TestCase):
    """Timezone is set via Settings (5) > Timezone (1) > digit 1-6 in new menu-driven UI."""

    PHONE = 'whatsapp:+1234567890'

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')
        _make_token(phone=self.PHONE)

    def _post(self, body):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url, data={'From': self.PHONE, 'Body': body}, format='multipart'
            )

    def test_valid_timezone_saved(self):
        """Selecting digit '2' in timezone_menu saves Europe/London and confirms in response."""
        _set_state(self.PHONE, 'timezone_menu', 1, {})
        response = self._post('2')  # Europe/London per TZ_MAP
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Europe/London', content)

        token = CalendarToken.objects.filter(phone_number=self.PHONE).first()
        self.assertIsNotNone(token)
        self.assertEqual(token.timezone, 'Europe/London')

    def test_invalid_digit_returns_error(self):
        """An out-of-range digit in timezone_menu returns INVALID_OPTION message."""
        _set_state(self.PHONE, 'timezone_menu', 1, {})
        response = self._post('9')  # not a valid choice (1-6 only)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # INVALID_OPTION from strings_he
        self.assertIn('\u05e2\u05e0\u05d4 \u05ea\u05e9\u05d5\u05d1\u05d4 \u05ea\u05e7\u05d9\u05e0\u05d4', content)

    def test_digit_3_saves_new_york(self):
        """Selecting digit '3' in timezone_menu saves America/New_York."""
        _set_state(self.PHONE, 'timezone_menu', 1, {})
        response = self._post('3')  # America/New_York per TZ_MAP
        self.assertEqual(response.status_code, 200)
        token = CalendarToken.objects.filter(phone_number=self.PHONE).first()
        self.assertIsNotNone(token)
        self.assertEqual(token.timezone, 'America/New_York')


@override_settings(**TWILIO_SETTINGS)
class SetDigestCommandTests(TestCase):
    """Digest time is set via Settings (5) > Digest (2) > HH:MM in new menu-driven UI."""

    PHONE = 'whatsapp:+1234567890'

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')
        _make_token(phone=self.PHONE)

    def _post(self, body):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url, data={'From': self.PHONE, 'Body': body}, format='multipart'
            )

    def test_set_digest_time_24h(self):
        """Sending '07:30' in digest_prompt state sets hour=7 minute=30 and confirms."""
        _set_state(self.PHONE, 'digest_prompt', 1, {})
        response = self._post('07:30')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('07:30', content)

        token = CalendarToken.objects.filter(phone_number=self.PHONE).first()
        self.assertEqual(token.digest_hour, 7)
        self.assertEqual(token.digest_minute, 30)

    def test_set_digest_time_pm(self):
        """Sending '14:00' in digest_prompt state sets hour=14 minute=0."""
        _set_state(self.PHONE, 'digest_prompt', 1, {})
        response = self._post('14:00')
        self.assertEqual(response.status_code, 200)
        token = CalendarToken.objects.filter(phone_number=self.PHONE).first()
        self.assertEqual(token.digest_hour, 14)
        self.assertEqual(token.digest_minute, 0)

    def test_set_digest_invalid_time_returns_error(self):
        """Sending a non-time string in digest_prompt returns the Hebrew invalid-time error."""
        _set_state(self.PHONE, 'digest_prompt', 1, {})
        response = self._post('bananas')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # DIGEST_INVALID from strings_he
        self.assertIn('\u05e9\u05e2\u05d4 \u05dc\u05d0 \u05ea\u05e7\u05d9\u05e0\u05d4', content)

    def test_digest_settings_submenu_option_2_shows_prompt(self):
        """From settings_menu state, sending '2' enters digest_prompt and shows HH:MM hint."""
        _set_state(self.PHONE, 'settings_menu', 1, {})
        response = self._post('2')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # DIGEST_PROMPT from strings_he contains 'HH:MM'
        self.assertIn('HH:MM', content)

    def test_set_digest_back_to_menu(self):
        """Sending '0' from digest_prompt returns to the main menu."""
        _set_state(self.PHONE, 'digest_prompt', 1, {})
        response = self._post('0')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)


@override_settings(**TWILIO_SETTINGS)
class DayQueryTests(TestCase):
    """Tests for calendar day queries routed through the Meetings submenu."""

    PHONE = 'whatsapp:+1234567890'

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')
        _make_token(phone=self.PHONE)

    def _post(self, body):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url, data={'From': self.PHONE, 'Body': body}, format='multipart'
            )

    @patch('apps.standup.views.WhatsAppWebhookView._query_meetings')
    def test_today_query_routed(self, mock_query):
        """Meetings submenu digit '1' calls _query_meetings (today)."""
        from django.http import HttpResponse
        from twilio.twiml.messaging_response import MessagingResponse
        twiml = MessagingResponse()
        twiml.message('09:00 Standup\n1 meeting')
        mock_query.return_value = HttpResponse(str(twiml), content_type='application/xml')

        _set_state(self.PHONE, 'meetings_menu', 1, {})
        response = self._post('1')
        self.assertEqual(response.status_code, 200)
        mock_query.assert_called_once()

    @patch('apps.standup.views.WhatsAppWebhookView._query_meetings')
    def test_tomorrow_query_routed(self, mock_query):
        """Meetings submenu digit '2' calls _query_meetings (tomorrow)."""
        from django.http import HttpResponse
        from twilio.twiml.messaging_response import MessagingResponse
        twiml = MessagingResponse()
        twiml.message('14:00 Planning\n1 meeting')
        mock_query.return_value = HttpResponse(str(twiml), content_type='application/xml')

        _set_state(self.PHONE, 'meetings_menu', 1, {})
        response = self._post('2')
        self.assertEqual(response.status_code, 200)
        mock_query.assert_called_once()

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_named_day_no_token_returns_nothing_routed_to_standup(self, mock_get_svc):
        """User without CalendarToken sending any text gets a 200 response."""
        CalendarToken.objects.filter(phone_number=self.PHONE).delete()
        response = self._post('friday')
        # Without a token, user gets onboarding flow
        self.assertEqual(response.status_code, 200)


@override_settings(**TWILIO_SETTINGS)
class NextMeetingTests(TestCase):
    """Next-meeting query via Meetings submenu digit '4'."""

    PHONE = 'whatsapp:+1234567890'

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')
        _make_token(phone=self.PHONE)

    def _post(self, body):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url, data={'From': self.PHONE, 'Body': body}, format='multipart'
            )

    @patch('apps.standup.views.WhatsAppWebhookView._query_next_meeting')
    def test_next_meeting_trigger_routed(self, mock_next):
        """Meetings submenu digit '4' calls _query_next_meeting."""
        from django.http import HttpResponse
        from twilio.twiml.messaging_response import MessagingResponse
        twiml = MessagingResponse()
        twiml.message('Your next meeting: Standup at 09:00 (in 30 minutes)')
        mock_next.return_value = HttpResponse(str(twiml), content_type='application/xml')

        _set_state(self.PHONE, 'meetings_menu', 1, {})
        response = self._post('4')
        self.assertEqual(response.status_code, 200)
        mock_next.assert_called_once()

    @patch('apps.standup.views.WhatsAppWebhookView._query_meetings')
    def test_week_query_routed(self, mock_query):
        """Meetings submenu digit '3' calls _query_meetings (this week)."""
        from django.http import HttpResponse
        from twilio.twiml.messaging_response import MessagingResponse
        twiml = MessagingResponse()
        twiml.message('No more meetings this week.')
        mock_query.return_value = HttpResponse(str(twiml), content_type='application/xml')

        _set_state(self.PHONE, 'meetings_menu', 1, {})
        response = self._post('3')
        self.assertEqual(response.status_code, 200)
        mock_query.assert_called_once()


@override_settings(**TWILIO_SETTINGS)
class FreeTodayTests(TestCase):
    """Free-time queries via Free-time submenu."""

    PHONE = 'whatsapp:+1234567890'

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')
        _make_token(phone=self.PHONE)

    def _post(self, body):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url, data={'From': self.PHONE, 'Body': body}, format='multipart'
            )

    @patch('apps.standup.views.WhatsAppWebhookView._query_free_time')
    def test_free_today_trigger_routed(self, mock_free):
        """Free-time submenu digit '1' calls _query_free_time for today."""
        from django.http import HttpResponse
        from twilio.twiml.messaging_response import MessagingResponse
        twiml = MessagingResponse()
        twiml.message("You're completely free today.")
        mock_free.return_value = HttpResponse(str(twiml), content_type='application/xml')

        _set_state(self.PHONE, 'free_time_menu', 1, {})
        response = self._post('1')
        self.assertEqual(response.status_code, 200)
        mock_free.assert_called_once()

    @patch('apps.standup.views.WhatsAppWebhookView._query_free_time')
    def test_free_tomorrow_trigger_routed(self, mock_free):
        """Free-time submenu digit '2' calls _query_free_time for tomorrow."""
        from django.http import HttpResponse
        from twilio.twiml.messaging_response import MessagingResponse
        twiml = MessagingResponse()
        twiml.message('Free slots today:\n\u2022 08:00\u201309:00 (1 hr)')
        mock_free.return_value = HttpResponse(str(twiml), content_type='application/xml')

        _set_state(self.PHONE, 'free_time_menu', 1, {})
        response = self._post('2')
        self.assertEqual(response.status_code, 200)
        mock_free.assert_called_once()


@override_settings(**TWILIO_SETTINGS)
class HelpCommandTests(TestCase):
    """
    Help text is returned when user selects digit '6' from the main_menu state.
    The '?' shortcut and 'help' text command are no longer recognised in the TZA-110 redesign.
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

    def test_help_returns_command_list(self):
        """Sending '6' from main_menu state returns the Hebrew help/instructions text."""
        _make_token(phone=self.PHONE)
        _set_state(self.PHONE, 'main_menu', 1, {})
        response = self._post('6')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # HELP_TEXT from strings_he mentions 'העוזר' (the assistant)
        self.assertIn('\u05d4\u05e2\u05d5\u05d6\u05e8', content)

    def test_main_menu_zero_returns_main_menu(self):
        """Sending '0' from main_menu state re-shows the main menu."""
        _make_token(phone=self.PHONE)
        _set_state(self.PHONE, 'main_menu', 1, {})
        response = self._post('0')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)

    def test_unconnected_user_gets_onboarding(self):
        """
        User with no CalendarToken sending any message starts the onboarding flow.

        TZA-110 replaced the old English standup-recording with a Hebrew onboarding flow.
        Unrecognised messages from unconnected users now trigger onboarding rather than
        logging a standup entry.
        """
        response = self._post('hello world')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # ONBOARDING_GREETING from strings_he contains '\u05d4\u05d9\u05d9' (היי)
        self.assertIn('\u05d4\u05d9\u05d9', content)


@override_settings(**TWILIO_SETTINGS)
class BlockCommandTests(TestCase):
    """
    Block commands are no longer supported as text commands in the TZA-110 redesign.
    Connected users sending 'block ...' text now receive the Hebrew main menu.
    Unconnected users sending 'block ...' text receive the onboarding greeting.
    The YES confirmation path is also no longer handled; connected users get the main menu.
    """

    PHONE = 'whatsapp:+1234567890'

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')
        _make_token(phone=self.PHONE)

    def _post(self, body):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url, data={'From': self.PHONE, 'Body': body}, format='multipart'
            )

    def test_block_text_returns_main_menu_for_connected_user(self):
        """Connected user sending 'block tomorrow 2-4pm Focus' receives the main menu."""
        response = self._post('block tomorrow 2-4pm Focus')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)

    def test_block_no_token_returns_onboarding(self):
        """User without a CalendarToken sending 'block' receives the onboarding greeting."""
        CalendarToken.objects.filter(phone_number=self.PHONE).delete()
        response = self._post('block tomorrow 2-4pm')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Onboarding greeting: '\u05d4\u05d9\u05d9' (היי)
        self.assertIn('\u05d4\u05d9\u05d9', content)

    def test_block_conflict_text_returns_main_menu(self):
        """Connected user sending 'block tomorrow 10-11am Deep Work' gets main menu."""
        response = self._post('block tomorrow 10-11am Deep Work')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)

    def test_yes_with_pending_block_returns_main_menu(self):
        """
        'YES' is no longer processed as a block confirmation in the TZA-110 redesign.
        Connected users sending 'YES' receive the main menu regardless of pending blocks.
        """
        PendingBlockConfirmation.objects.create(
            phone_number=self.PHONE,
            event_data={
                'date': '2026-02-21',
                'start': '2026-02-21T10:00:00+00:00',
                'end': '2026-02-21T11:00:00+00:00',
                'title': 'Deep Work',
            },
        )

        response = self._post('YES')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # New design: connected user gets main menu, not block confirmation
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9', content)

    def test_yes_with_no_pending_falls_through(self):
        """YES with no pending block should not return a 'Blocked:' confirmation."""
        response = self._post('YES')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn('Blocked:', content)
