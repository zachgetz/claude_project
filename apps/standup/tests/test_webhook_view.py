"""
Unit tests for apps.standup.views.WhatsAppWebhookView.

The TwilioSignaturePermission is patched out for all tests so that
we can focus on view logic without needing a real Twilio signature.
"""
import datetime
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.standup.models import StandupEntry


PATCH_PERMISSION = patch(
    'apps.standup.permissions.TwilioSignaturePermission.has_permission',
    return_value=True,
)


@override_settings(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
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
    # Tests
    # ------------------------------------------------------------------
    def test_valid_standup_creates_entry(self):
        """A non-empty Body creates a StandupEntry and returns 200 XML."""
        response = self._post('Working on TZA-18 today.')

        self.assertEqual(response.status_code, 200)
        self.assertIn('application/xml', response['Content-Type'])
        self.assertEqual(StandupEntry.objects.count(), 1)

        entry = StandupEntry.objects.first()
        self.assertEqual(entry.phone_number, self.phone)
        self.assertEqual(entry.message, 'Working on TZA-18 today.')

    def test_response_contains_confirmation_text(self):
        """Reply TwiML should contain the confirmation message."""
        response = self._post('Done with review.')
        content = response.content.decode()
        self.assertIn('Got it', content)
        self.assertIn('/summary', content)

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

    def test_entry_count_increments_per_week(self):
        """Multiple entries from the same number increment the count correctly."""
        self._post('First entry.')
        self._post('Second entry.')
        response = self._post('Third entry.')

        self.assertEqual(StandupEntry.objects.count(), 3)
        content = response.content.decode()
        # The reply should mention entry #3
        self.assertIn('entry #3', content)

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

    def test_summary_command_no_entries(self):
        """/summary with no entries this week returns a friendly message."""
        response = self._post('/summary')

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('No entries yet this week', content)

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

    def test_multiple_users_isolated(self):
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
