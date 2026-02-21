"""
Tests for multi-account calendar commands (TZA-78).

Covers: connect calendar, my calendars, remove calendar.
"""
import datetime
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

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
class ConnectCalendarCommandTests(TestCase):

    PHONE = 'whatsapp:+1234567890'

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')

    def _post(self, body):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url, data={'From': self.PHONE, 'Body': body}, format='multipart'
            )

    def test_connect_calendar_returns_oauth_link(self):
        response = self._post('connect calendar')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('calendar/auth/start', content)
        # Phone number should appear in the link
        self.assertIn('phone', content)

    def test_add_calendar_alias_returns_oauth_link(self):
        response = self._post('add calendar')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('calendar/auth/start', content)

    def test_connect_calendar_uses_webhook_base_url(self):
        response = self._post('connect calendar')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('example.com', content)


@override_settings(**TWILIO_SETTINGS)
class MyCalendarsCommandTests(TestCase):

    PHONE = 'whatsapp:+1234567890'

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')

    def _post(self, body):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url, data={'From': self.PHONE, 'Body': body}, format='multipart'
            )

    def test_my_calendars_no_tokens(self):
        response = self._post('my calendars')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('No Google Calendar', content.replace('\n', ' '))

    def test_my_calendars_single_token(self):
        _make_token(phone=self.PHONE, email='work@example.com', label='work')
        response = self._post('my calendars')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('work@example.com', content)
        self.assertIn('work', content)

    def test_my_calendars_two_tokens(self):
        _make_token(phone=self.PHONE, email='work@example.com', label='work')
        _make_token(phone=self.PHONE, email='personal@example.com', label='personal')
        response = self._post('my calendars')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('work@example.com', content)
        self.assertIn('personal@example.com', content)
        self.assertIn('2', content)  # '2' in 'Connected calendars (2):'


@override_settings(**TWILIO_SETTINGS)
class RemoveCalendarCommandTests(TestCase):

    PHONE = 'whatsapp:+1234567890'

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('whatsapp-webhook')

    def _post(self, body):
        with PATCH_PERMISSION:
            return self.client.post(
                self.url, data={'From': self.PHONE, 'Body': body}, format='multipart'
            )

    def test_remove_calendar_by_email(self):
        _make_token(phone=self.PHONE, email='work@example.com', label='work')
        self.assertEqual(CalendarToken.objects.filter(phone_number=self.PHONE).count(), 1)

        response = self._post('remove calendar work@example.com')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Removed', content)
        self.assertEqual(CalendarToken.objects.filter(phone_number=self.PHONE).count(), 0)

    def test_remove_calendar_by_label(self):
        _make_token(phone=self.PHONE, email='work@example.com', label='work')

        response = self._post('remove calendar work')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Removed', content)
        self.assertEqual(CalendarToken.objects.filter(phone_number=self.PHONE).count(), 0)

    def test_remove_calendar_not_found(self):
        response = self._post('remove calendar nonexistent@example.com')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('No connected calendar found', content.replace('\n', ' '))

    def test_remove_calendar_no_identifier(self):
        response = self._post('remove calendar')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('specify', content)

    def test_remove_calendar_cascades_watch_channels(self):
        """Removing a token should cascade-delete associated watch channels."""
        token = _make_token(phone=self.PHONE, email='work@example.com', label='work')
        CalendarWatchChannel.objects.create(phone_number=self.PHONE, token=token)
        self.assertEqual(CalendarWatchChannel.objects.filter(token=token).count(), 1)

        self._post('remove calendar work@example.com')
        self.assertEqual(CalendarWatchChannel.objects.filter(phone_number=self.PHONE).count(), 0)

    def test_remove_one_of_two_tokens(self):
        """Removing one account should leave the other intact."""
        _make_token(phone=self.PHONE, email='work@example.com', label='work')
        _make_token(phone=self.PHONE, email='personal@example.com', label='personal')

        self._post('remove calendar work@example.com')
        remaining = CalendarToken.objects.filter(phone_number=self.PHONE)
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().account_email, 'personal@example.com')
