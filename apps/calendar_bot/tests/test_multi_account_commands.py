"""
Tests for multi-account calendar model layer (TZA-78).

After replacing the digit menu with NLP (Claude tool-use), menu-specific
WhatsApp interaction tests have been removed.  What remains:

  - Unconnected user → onboarding greeting
  - Model-layer: cascade delete, token counting
"""
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from unittest.mock import patch

from apps.calendar_bot.models import CalendarToken, CalendarWatchChannel


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
class OnboardingForUnconnectedUsersTests(TestCase):
    """Unconnected users sending any text should receive the onboarding greeting."""

    PHONE = 'whatsapp:+1234567890'

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')

    def _post(self, body):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url, data={'From': self.PHONE, 'Body': body}, format='multipart'
            )

    def test_unconnected_user_gets_onboarding(self):
        """Sending any text with no CalendarToken returns the onboarding greeting."""
        response = self._post('hello')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Onboarding greeting starts with 'היי'
        self.assertIn('\u05d4\u05d9\u05d9', content)

    def test_no_token_returns_onboarding_regardless_of_text(self):
        """Sending 'remove calendar' with no token still returns onboarding."""
        response = self._post('remove calendar nonexistent@example.com')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('\u05d4\u05d9\u05d9', content)


class MultiAccountModelTests(TestCase):
    """Model-layer tests for multi-account CalendarToken management."""

    PHONE = 'whatsapp:+1234567890'

    def test_calendar_token_cascade_delete_model_layer(self):
        """Deleting a token also removes its associated watch channels."""
        token = _make_token(phone=self.PHONE, email='work@example.com', label='work')
        CalendarWatchChannel.objects.create(phone_number=self.PHONE, token=token)
        self.assertEqual(CalendarWatchChannel.objects.filter(token=token).count(), 1)

        token.delete()
        self.assertEqual(CalendarWatchChannel.objects.filter(phone_number=self.PHONE).count(), 0)

    def test_two_tokens_one_deletion_leaves_other_model_layer(self):
        """Removing one of two CalendarTokens leaves the other intact."""
        _make_token(phone=self.PHONE, email='work@example.com', label='work')
        _make_token(phone=self.PHONE, email='personal@example.com', label='personal')

        CalendarToken.objects.filter(
            phone_number=self.PHONE, account_email='work@example.com'
        ).delete()

        remaining = CalendarToken.objects.filter(phone_number=self.PHONE)
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().account_email, 'personal@example.com')
