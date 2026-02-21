"""
Tests for the numbered calendar menu (TZA-64) and digit routing (TZA-65).

Covers:
- Menu trigger words (menu / options / calendar) return MENU_TEXT
- Menu triggers do NOT create StandupEntry records
- Digit 6 always routes to help text (no calendar required)
- Digits 1-5 route to correct calendar handlers when a calendar IS linked
- Digits 1-5 fall through to standup entry when no calendar is linked
- Digits 7, 8, 9 fall through to standup entry (logged)
- Multi-digit input (e.g. '12') falls through to standup entry (logged)

The TwilioSignaturePermission is patched out throughout so that we can
focus on view logic without needing a real Twilio signature.
"""
import datetime
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.standup.models import StandupEntry
from apps.standup.views import MENU_TEXT, MENU_TRIGGERS, HELP_TEXT


PATCH_PERMISSION = patch(
    'apps.standup.permissions.TwilioSignaturePermission.has_permission',
    return_value=True,
)


@override_settings(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
)
class MenuTriggerTests(TestCase):
    """Tests for MENU_TRIGGERS: 'menu', 'options', 'calendar'."""

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')
        self.phone = 'whatsapp:+1234567890'

    def _post(self, body, from_number=None):
        from_number = from_number or self.phone
        with PATCH_PERMISSION:
            return self.client.post(
                self.url,
                data={'From': from_number, 'Body': body},
                format='multipart',
            )

    def test_menu_trigger_returns_menu_text(self):
        """Sending 'menu' should return MENU_TEXT in the TwiML response."""
        response = self._post('menu')
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/xml', response['Content-Type'])
        content = response.content.decode()
        # Check a distinctive portion of MENU_TEXT appears in XML
        self.assertIn('Calendar Menu', content)
        self.assertIn('1.', content)
        self.assertIn('6.', content)

    def test_options_trigger_returns_menu_text(self):
        """Sending 'options' should return MENU_TEXT."""
        response = self._post('options')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Calendar Menu', content)

    def test_calendar_trigger_returns_menu_text(self):
        """Sending 'calendar' should return MENU_TEXT."""
        response = self._post('calendar')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Calendar Menu', content)

    def test_menu_trigger_uppercase_returns_menu_text(self):
        """Menu trigger words should be case-insensitive."""
        response = self._post('MENU')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Calendar Menu', content)

    def test_menu_trigger_with_whitespace_returns_menu_text(self):
        """Surrounding whitespace should be stripped before matching."""
        response = self._post('  menu  ')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Calendar Menu', content)

    def test_menu_trigger_does_not_create_standup_entry(self):
        """Menu trigger must NOT create a StandupEntry record."""
        self._post('menu')
        self.assertEqual(StandupEntry.objects.count(), 0)

    def test_options_trigger_does_not_create_standup_entry(self):
        """'options' trigger must NOT create a StandupEntry record."""
        self._post('options')
        self.assertEqual(StandupEntry.objects.count(), 0)

    def test_calendar_trigger_does_not_create_standup_entry(self):
        """'calendar' trigger must NOT create a StandupEntry record."""
        self._post('calendar')
        self.assertEqual(StandupEntry.objects.count(), 0)

    def test_menu_text_constant_in_response(self):
        """The response body must contain the literal 'Reply with a number' from MENU_TEXT."""
        response = self._post('menu')
        content = response.content.decode()
        self.assertIn('Reply with a number', content)


@override_settings(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
)
class DigitRoutingTests(TestCase):
    """Tests for single-digit (1-9) routing."""

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')
        self.phone = 'whatsapp:+1234567890'

    def _post(self, body, from_number=None):
        from_number = from_number or self.phone
        with PATCH_PERMISSION:
            return self.client.post(
                self.url,
                data={'From': from_number, 'Body': body},
                format='multipart',
            )

    # ------------------------------------------------------------------
    # Digit 6 -> help (always works, no calendar required)
    # ------------------------------------------------------------------

    def test_digit_6_returns_help_text(self):
        """Sending '6' should return the HELP_TEXT regardless of calendar status."""
        response = self._post('6')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('calendar assistant', content)

    def test_digit_6_does_not_create_standup_entry(self):
        """Sending '6' must NOT create a standup entry."""
        self._post('6')
        self.assertEqual(StandupEntry.objects.count(), 0)

    # ------------------------------------------------------------------
    # Digits 1-5 with calendar connected -> route to handlers
    # ------------------------------------------------------------------

    def test_digit_1_routes_to_today_handler_with_calendar(self):
        """Digit '1' with calendar linked calls _try_day_query with 'today'."""
        mock_response_text = 'Today: standup at 09:00'
        with patch.object(
            self.client.__class__,
            'post',
            wraps=self.client.post,
        ):
            with PATCH_PERMISSION:
                with patch(
                    'apps.standup.views.WhatsAppWebhookView._try_day_query',
                    return_value=self._make_xml_response(mock_response_text),
                ) as mock_day:
                    response = self.client.post(
                        self.url,
                        data={'From': self.phone, 'Body': '1'},
                        format='multipart',
                    )
                    mock_day.assert_called_once_with(self.phone, 'today')
        self.assertEqual(StandupEntry.objects.count(), 0)

    def test_digit_2_routes_to_tomorrow_handler_with_calendar(self):
        """Digit '2' with calendar linked calls _try_day_query with 'tomorrow'."""
        with PATCH_PERMISSION:
            with patch(
                'apps.standup.views.WhatsAppWebhookView._try_day_query',
                return_value=self._make_xml_response('Tomorrow events'),
            ) as mock_day:
                self.client.post(
                    self.url,
                    data={'From': self.phone, 'Body': '2'},
                    format='multipart',
                )
                mock_day.assert_called_once_with(self.phone, 'tomorrow')

    def test_digit_3_routes_to_this_week_handler_with_calendar(self):
        """Digit '3' with calendar linked calls _try_day_query with 'this week'."""
        with PATCH_PERMISSION:
            with patch(
                'apps.standup.views.WhatsAppWebhookView._try_day_query',
                return_value=self._make_xml_response('This week events'),
            ) as mock_day:
                self.client.post(
                    self.url,
                    data={'From': self.phone, 'Body': '3'},
                    format='multipart',
                )
                mock_day.assert_called_once_with(self.phone, 'this week')

    def test_digit_4_routes_to_next_meeting_handler_with_calendar(self):
        """Digit '4' with calendar linked calls _try_next_meeting."""
        with PATCH_PERMISSION:
            with patch(
                'apps.standup.views.WhatsAppWebhookView._try_next_meeting',
                return_value=self._make_xml_response('Next meeting at 14:00'),
            ) as mock_next:
                self.client.post(
                    self.url,
                    data={'From': self.phone, 'Body': '4'},
                    format='multipart',
                )
                mock_next.assert_called_once_with(self.phone)

    def test_digit_5_routes_to_free_today_handler_with_calendar(self):
        """Digit '5' with calendar linked calls _try_free_today."""
        with PATCH_PERMISSION:
            with patch(
                'apps.standup.views.WhatsAppWebhookView._try_free_today',
                return_value=self._make_xml_response('Free slots today'),
            ) as mock_free:
                self.client.post(
                    self.url,
                    data={'From': self.phone, 'Body': '5'},
                    format='multipart',
                )
                mock_free.assert_called_once_with(self.phone)

    # ------------------------------------------------------------------
    # Digits 1-5 with NO calendar -> fall through to standup
    # ------------------------------------------------------------------

    def test_digit_1_no_calendar_falls_through_to_standup(self):
        """Digit '1' with no calendar linked creates a standup entry."""
        # _try_day_query returns None when no calendar is linked
        with PATCH_PERMISSION:
            with patch(
                'apps.standup.views.WhatsAppWebhookView._try_day_query',
                return_value=None,
            ):
                response = self.client.post(
                    self.url,
                    data={'From': self.phone, 'Body': '1'},
                    format='multipart',
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StandupEntry.objects.count(), 1)
        entry = StandupEntry.objects.first()
        self.assertEqual(entry.message, '1')

    def test_digit_4_no_calendar_falls_through_to_standup(self):
        """Digit '4' with no calendar linked creates a standup entry."""
        with PATCH_PERMISSION:
            with patch(
                'apps.standup.views.WhatsAppWebhookView._try_next_meeting',
                return_value=None,
            ):
                response = self.client.post(
                    self.url,
                    data={'From': self.phone, 'Body': '4'},
                    format='multipart',
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StandupEntry.objects.count(), 1)

    def test_digit_5_no_calendar_falls_through_to_standup(self):
        """Digit '5' with no calendar linked creates a standup entry."""
        with PATCH_PERMISSION:
            with patch(
                'apps.standup.views.WhatsAppWebhookView._try_free_today',
                return_value=None,
            ):
                response = self.client.post(
                    self.url,
                    data={'From': self.phone, 'Body': '5'},
                    format='multipart',
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StandupEntry.objects.count(), 1)

    # ------------------------------------------------------------------
    # Digits 7-9 -> fall through to standup
    # ------------------------------------------------------------------

    def test_digit_7_creates_standup_entry(self):
        """Digit '7' should be logged as a standup entry."""
        response = self._post('7')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StandupEntry.objects.count(), 1)
        entry = StandupEntry.objects.first()
        self.assertEqual(entry.message, '7')

    def test_digit_8_creates_standup_entry(self):
        """Digit '8' should be logged as a standup entry."""
        response = self._post('8')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StandupEntry.objects.count(), 1)
        entry = StandupEntry.objects.first()
        self.assertEqual(entry.message, '8')

    def test_digit_9_creates_standup_entry(self):
        """Digit '9' should be logged as a standup entry."""
        response = self._post('9')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StandupEntry.objects.count(), 1)
        entry = StandupEntry.objects.first()
        self.assertEqual(entry.message, '9')

    def test_digit_7_response_contains_confirmation(self):
        """The standup confirmation text should appear in the '7' response."""
        response = self._post('7')
        content = response.content.decode()
        self.assertIn('Got it', content)

    # ------------------------------------------------------------------
    # Multi-digit inputs -> fall through to standup
    # ------------------------------------------------------------------

    def test_multi_digit_12_creates_standup_entry(self):
        """Input '12' (multi-digit) should be logged as a standup entry."""
        response = self._post('12')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StandupEntry.objects.count(), 1)
        entry = StandupEntry.objects.first()
        self.assertEqual(entry.message, '12')

    def test_multi_digit_99_creates_standup_entry(self):
        """Input '99' (multi-digit) should be logged as a standup entry."""
        response = self._post('99')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StandupEntry.objects.count(), 1)

    def test_multi_digit_123_creates_standup_entry(self):
        """Input '123' (three digits) should be logged as a standup entry."""
        response = self._post('123')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StandupEntry.objects.count(), 1)

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _make_xml_response(text):
        """Return a minimal HttpResponse mimicking a TwiML response."""
        from django.http import HttpResponse
        from twilio.twiml.messaging_response import MessagingResponse
        resp = MessagingResponse()
        resp.message(text)
        return HttpResponse(str(resp), content_type='application/xml')
