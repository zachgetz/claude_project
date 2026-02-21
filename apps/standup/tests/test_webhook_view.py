"""
TZA-117: Updated unit tests for apps.standup.views.WhatsAppWebhookView.

After TZA-110, the bot is fully menu-driven and Hebrew-only:
- Free text from new (unconnected) users triggers onboarding, not standup entry.
- Free text from connected users at root shows the Hebrew main menu.
- StandupEntry records are no longer created from free-text messages.
- The legacy /summary command still works (returns Hebrew digest).
- The TwilioSignaturePermission is enforced (returns 403 without mock).

The TwilioSignaturePermission is patched out for all tests so that we
can focus on view logic without needing a real Twilio signature.
"""
import datetime
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.standup.models import StandupEntry
from apps.calendar_bot.models import CalendarToken, UserMenuState


PATCH_PERMISSION = patch(
    'apps.standup.permissions.TwilioSignaturePermission.has_permission',
    return_value=True,
)


@override_settings(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
    WEBHOOK_BASE_URL='https://example.com',
)
class WhatsAppWebhookViewTests(TestCase):
    """Tests for POST /standup/webhook/."""

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')
        self.phone = 'whatsapp:+1234567890'

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------
    def _post(self, body, from_number=None):
        """POST to the webhook with Twilio signature check bypassed."""
        from_number = from_number or self.phone
        with PATCH_PERMISSION:
            return self.client.post(
                self.url,
                data={'From': from_number, 'Body': body},
                format='multipart',
            )

    # ------------------------------------------------------------------
    # Unconnected users: onboarding flow
    # ------------------------------------------------------------------

    def test_new_user_gets_onboarding_greeting(self):
        """A user with no CalendarToken gets the Hebrew onboarding greeting."""
        response = self._post('Hello!')
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/xml', response['Content-Type'])
        content = response.content.decode()
        # Hebrew onboarding: '\u05d4\u05d9\u05d9' = 'היי'
        self.assertIn('\u05d4\u05d9\u05d9', content)
        # Asks for name: '\u05de\u05d4 \u05e9\u05de\u05da' = 'מה שמך'
        self.assertIn('\u05de\u05d4 \u05e9\u05de\u05da', content)

    def test_new_user_does_not_create_standup_entry(self):
        """No StandupEntry is created during onboarding."""
        self._post('Working on TZA-18 today.')
        self.assertEqual(StandupEntry.objects.count(), 0)

    # ------------------------------------------------------------------
    # Connected users: main menu at root
    # ------------------------------------------------------------------

    def test_connected_user_sees_hebrew_main_menu(self):
        """A connected user sending any text at root sees the Hebrew main menu."""
        CalendarToken.objects.create(
            phone_number=self.phone,
            account_email='test@example.com',
            access_token='fake_access',
            refresh_token='fake_refresh',
        )
        response = self._post('Done with review.')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Hebrew main menu header: 'תפריט'
        self.assertIn('\u05ea\u05e4\u05e8\u05d9\u05d8', content)

    def test_connected_user_does_not_create_standup_entry(self):
        """Free text from a connected user must NOT create a StandupEntry."""
        CalendarToken.objects.create(
            phone_number=self.phone,
            account_email='test@example.com',
            access_token='fake_access',
            refresh_token='fake_refresh',
        )
        self._post('Working on TZA-18 today.')
        self.assertEqual(StandupEntry.objects.count(), 0)

    # ------------------------------------------------------------------
    # Empty body
    # ------------------------------------------------------------------

    def test_empty_body_returns_400(self):
        """An empty Body should return HTTP 400 without creating any entry."""
        response = self._post('')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(StandupEntry.objects.count(), 0)

    def test_whitespace_only_body_returns_400(self):
        """A whitespace-only Body should also return HTTP 400."""
        response = self._post('   ')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(StandupEntry.objects.count(), 0)

    # ------------------------------------------------------------------
    # /summary command (legacy — still functional)
    # ------------------------------------------------------------------

    def test_summary_command_returns_digest(self):
        """/summary returns a weekly digest containing submitted messages."""
        StandupEntry.objects.create(
            phone_number=self.phone,
            message='Fixed the login bug.',
            week_number=datetime.datetime.now().isocalendar()[1],
        )

        response = self._post('/summary')

        self.assertEqual(response.status_code, 200)
        self.assertIn('application/xml', response['Content-Type'])
        content = response.content.decode()
        self.assertIn('Fixed the login bug.', content)

    def test_summary_command_no_entries_returns_hebrew_message(self):
        """/summary with no entries this week returns a Hebrew 'no entries' message."""
        response = self._post('/summary')

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Hebrew 'no entries': '\u05d0\u05d9\u05df \u05e8\u05e9\u05d5\u05de\u05d5\u05ea'
        self.assertIn('\u05d0\u05d9\u05df \u05e8\u05e9\u05d5\u05de\u05d5\u05ea', content)

    def test_summary_only_shows_current_week(self):
        """/summary only shows entries from the current ISO week."""
        current_week = datetime.datetime.now().isocalendar()[1]
        last_week = current_week - 1 if current_week > 1 else 52

        StandupEntry.objects.create(
            phone_number=self.phone,
            message='Last week message.',
            week_number=last_week,
        )
        StandupEntry.objects.create(
            phone_number=self.phone,
            message='This week message.',
            week_number=current_week,
        )

        response = self._post('/summary')
        content = response.content.decode()

        self.assertIn('This week message.', content)
        self.assertNotIn('Last week message.', content)

    def test_multiple_users_summary_isolated(self):
        """Entries from different phone numbers don't appear in each other's summary."""
        other_phone = 'whatsapp:+9876543210'
        current_week = datetime.datetime.now().isocalendar()[1]

        StandupEntry.objects.create(
            phone_number=self.phone,
            message='My standup.',
            week_number=current_week,
        )
        StandupEntry.objects.create(
            phone_number=other_phone,
            message='Other person standup.',
            week_number=current_week,
        )

        response = self._post('/summary', from_number=self.phone)
        content = response.content.decode()

        self.assertIn('My standup.', content)
        self.assertNotIn('Other person standup.', content)

    # ------------------------------------------------------------------
    # Twilio signature enforcement
    # ------------------------------------------------------------------

    def test_twilio_signature_rejected_without_mock(self):
        """
        Without the mock, an invalid/missing Twilio signature returns 403.
        This verifies TwilioSignaturePermission is actually enforced.
        """
        response = self.client.post(
            self.url,
            data={'From': self.phone, 'Body': 'test'},
            format='multipart',
        )
        self.assertEqual(response.status_code, 403)
