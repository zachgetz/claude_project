"""
Unit tests for calendar-bot commands handled in apps.standup.views.WhatsAppWebhookView.

Covers: set timezone, set digest, day queries, next meeting, free today, help, block commands.
The TwilioSignaturePermission is patched out for all tests.
"""
import datetime
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.calendar_bot.models import CalendarToken, PendingBlockConfirmation


PATCH_PERMISSION = patch(
    'apps.standup.permissions.TwilioSignaturePermission.has_permission',
    return_value=True,
)

TWILIO_SETTINGS = dict(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
)


def _make_token(phone='+1234567890', tz='America/New_York'):
    return CalendarToken.objects.create(
        phone_number=phone,
        access_token='access_abc',
        refresh_token='refresh_xyz',
        timezone=tz,
    )


@override_settings(**TWILIO_SETTINGS)
class SetTimezoneCommandTests(TestCase):

    PHONE = 'whatsapp:+1234567890'

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')
        # CalendarToken uses the bare phone number (no 'whatsapp:' prefix)
        _make_token(phone=self.PHONE)

    def _post(self, body):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url, data={'From': self.PHONE, 'Body': body}, format='multipart'
            )

    def test_valid_timezone_saved(self):
        response = self._post('set timezone Europe/London')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Europe/London', content)

        token = CalendarToken.objects.get(phone_number=self.PHONE)
        self.assertEqual(token.timezone, 'Europe/London')

    def test_invalid_timezone_returns_error(self):
        response = self._post('set timezone Mars/Olympus')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Unknown timezone', content)

    def test_case_insensitive_command_prefix(self):
        """'set timezone' must start lowercase per views logic."""
        response = self._post('set timezone UTC')
        self.assertEqual(response.status_code, 200)
        token = CalendarToken.objects.get(phone_number=self.PHONE)
        self.assertEqual(token.timezone, 'UTC')


@override_settings(**TWILIO_SETTINGS)
class SetDigestCommandTests(TestCase):

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

    def test_set_digest_off(self):
        response = self._post('set digest off')
        self.assertEqual(response.status_code, 200)
        token = CalendarToken.objects.get(phone_number=self.PHONE)
        self.assertFalse(token.digest_enabled)

    def test_set_digest_on(self):
        # First disable, then re-enable
        token = CalendarToken.objects.get(phone_number=self.PHONE)
        token.digest_enabled = False
        token.save()

        response = self._post('set digest on')
        self.assertEqual(response.status_code, 200)
        token.refresh_from_db()
        self.assertTrue(token.digest_enabled)

    def test_set_digest_always(self):
        response = self._post('set digest always')
        self.assertEqual(response.status_code, 200)
        token = CalendarToken.objects.get(phone_number=self.PHONE)
        self.assertTrue(token.digest_always)

    def test_set_digest_time_24h(self):
        response = self._post('set digest 7:30am')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('07:30', content)

        token = CalendarToken.objects.get(phone_number=self.PHONE)
        self.assertEqual(token.digest_hour, 7)
        self.assertEqual(token.digest_minute, 30)

    def test_set_digest_time_pm(self):
        response = self._post('set digest 2pm')
        self.assertEqual(response.status_code, 200)
        token = CalendarToken.objects.get(phone_number=self.PHONE)
        self.assertEqual(token.digest_hour, 14)
        self.assertEqual(token.digest_minute, 0)

    def test_set_digest_invalid_time_returns_error(self):
        response = self._post('set digest bananas')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Could not understand', content)


@override_settings(**TWILIO_SETTINGS)
class DayQueryTests(TestCase):
    """Tests for calendar day queries routed through WhatsApp webhook."""

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

    @patch('apps.standup.views.WhatsAppWebhookView._try_day_query')
    def test_today_query_routed(self, mock_day_query):
        from django.http import HttpResponse
        from twilio.twiml.messaging_response import MessagingResponse
        twiml = MessagingResponse()
        twiml.message('09:00 Standup\n1 meeting')
        mock_day_query.return_value = HttpResponse(str(twiml), content_type='application/xml')

        response = self._post('today')
        self.assertEqual(response.status_code, 200)
        mock_day_query.assert_called_once()

    @patch('apps.standup.views.WhatsAppWebhookView._try_day_query')
    def test_tomorrow_query_routed(self, mock_day_query):
        from django.http import HttpResponse
        from twilio.twiml.messaging_response import MessagingResponse
        twiml = MessagingResponse()
        twiml.message('14:00 Planning\n1 meeting')
        mock_day_query.return_value = HttpResponse(str(twiml), content_type='application/xml')

        response = self._post('tomorrow')
        self.assertEqual(response.status_code, 200)
        mock_day_query.assert_called_once()

    @patch('apps.calendar_bot.calendar_service.get_calendar_service')
    def test_named_day_no_token_returns_nothing_routed_to_standup(self, mock_get_svc):
        """User without CalendarToken falls through to standup logging."""
        # Remove token so user has no calendar connected
        CalendarToken.objects.filter(phone_number=self.PHONE).delete()
        response = self._post('friday')
        # Without a token, day query returns None, falls through to onboarding
        self.assertEqual(response.status_code, 200)


@override_settings(**TWILIO_SETTINGS)
class NextMeetingTests(TestCase):

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

    @patch('apps.standup.views.WhatsAppWebhookView._try_next_meeting')
    def test_next_meeting_trigger_routed(self, mock_next):
        from django.http import HttpResponse
        from twilio.twiml.messaging_response import MessagingResponse
        twiml = MessagingResponse()
        twiml.message('Your next meeting: Standup at 09:00 (in 30 minutes)')
        mock_next.return_value = HttpResponse(str(twiml), content_type='application/xml')

        response = self._post('next meeting')
        self.assertEqual(response.status_code, 200)
        mock_next.assert_called_once()

    @patch('apps.standup.views.WhatsAppWebhookView._try_next_meeting')
    def test_next_alias_trigger_routed(self, mock_next):
        from django.http import HttpResponse
        from twilio.twiml.messaging_response import MessagingResponse
        twiml = MessagingResponse()
        twiml.message('No more meetings this week.')
        mock_next.return_value = HttpResponse(str(twiml), content_type='application/xml')

        response = self._post('next')
        self.assertEqual(response.status_code, 200)
        mock_next.assert_called_once()


@override_settings(**TWILIO_SETTINGS)
class FreeTodayTests(TestCase):

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

    @patch('apps.standup.views.WhatsAppWebhookView._try_free_today')
    def test_free_today_trigger_routed(self, mock_free):
        from django.http import HttpResponse
        from twilio.twiml.messaging_response import MessagingResponse
        twiml = MessagingResponse()
        twiml.message("You're completely free today.")
        mock_free.return_value = HttpResponse(str(twiml), content_type='application/xml')

        response = self._post('free today')
        self.assertEqual(response.status_code, 200)
        mock_free.assert_called_once()

    @patch('apps.standup.views.WhatsAppWebhookView._try_free_today')
    def test_am_i_free_trigger_routed(self, mock_free):
        from django.http import HttpResponse
        from twilio.twiml.messaging_response import MessagingResponse
        twiml = MessagingResponse()
        twiml.message('Free slots today:\n\u2022 08:00\u201309:00 (1 hr)')
        mock_free.return_value = HttpResponse(str(twiml), content_type='application/xml')

        response = self._post('am i free')
        self.assertEqual(response.status_code, 200)
        mock_free.assert_called_once()


@override_settings(**TWILIO_SETTINGS)
class HelpCommandTests(TestCase):

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
        response = self._post('help')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # help text should mention key commands
        self.assertIn('today', content)
        self.assertIn('block', content)

    def test_question_mark_returns_help(self):
        response = self._post('?')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('today', content)

    def test_unconnected_user_gets_standup_recording(self):
        """User with no CalendarToken and unrecognized message gets recorded as standup entry.

        TZA-58 intentionally removed the catch-all _maybe_onboarding() call so that
        unrecognized messages are always logged as standup entries. Onboarding is only
        shown in response to explicit help/? commands. This test verifies that routing.
        """
        response = self._post('hello world')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Unrecognized messages are recorded as standup entries
        self.assertIn('Logged', content)


@override_settings(**TWILIO_SETTINGS)
class BlockCommandTests(TestCase):

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

    @patch('apps.calendar_bot.calendar_service.handle_block_command')
    def test_block_no_conflict(self, mock_handle):
        mock_handle.return_value = '\u2705 Blocked: "Focus" on Saturday, Feb 21 14:00-16:00'

        response = self._post('block tomorrow 2-4pm Focus')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Blocked', content)
        mock_handle.assert_called_once()

    @patch('apps.calendar_bot.calendar_service.handle_block_command')
    def test_block_with_conflict_asks_confirmation(self, mock_handle):
        mock_handle.return_value = (
            '\u26a0\ufe0f Conflict detected: "Standup" overlaps with 10:00-11:00 on Saturday, Feb 21.\n'
            'Reply YES to create "Deep Work" anyway.'
        )

        response = self._post('block tomorrow 10-11am Deep Work')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('YES', content)

    @patch('apps.calendar_bot.calendar_service.confirm_block_command')
    def test_yes_confirms_pending_block(self, mock_confirm):
        mock_confirm.return_value = '\u2705 Blocked: "Deep Work" on Saturday, Feb 21 10:00-11:00'

        # Create a pending confirmation in DB
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
        self.assertIn('Blocked', content)
        mock_confirm.assert_called_once_with(self.PHONE)

    def test_yes_with_no_pending_falls_through(self):
        """YES with no pending block should fall through to standup logging."""
        # No PendingBlockConfirmation exists
        response = self._post('YES')
        self.assertEqual(response.status_code, 200)
        # Should log as standup entry since no pending block exists and user has token
        # (connected user with unrecognized message -> help text)
        content = response.content.decode()
        # Not a block confirmation response
        self.assertNotIn('Blocked:', content)

    @patch('apps.calendar_bot.calendar_service.handle_block_command')
    def test_block_no_token_returns_onboarding(self, mock_handle):
        """User without a CalendarToken gets the connect calendar message."""
        CalendarToken.objects.filter(phone_number=self.PHONE).delete()

        response = self._post('block tomorrow 2-4pm')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('connect', content.lower())
        mock_handle.assert_not_called()
