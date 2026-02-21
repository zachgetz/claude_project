"""
TZA-130: Unit tests for TwilioStatusCallbackView and status_callback kwarg in tasks.

Covers:
- POST /standup/twilio-status/ with 'sent' status -> 204 + logger.info
- POST /standup/twilio-status/ with 'delivered' status -> 204 + logger.info
- POST /standup/twilio-status/ with 'failed' status -> 204 + logger.error with ErrorCode/ErrorMessage
- POST /standup/twilio-status/ with 'undelivered' status -> 204 + logger.error
- POST /standup/twilio-status/ with 'queued' status -> 204 + logger.error
- CSRF-exempt: POST without CSRF token works
- send_morning_checkin passes status_callback kwarg to messages.create()
- send_evening_digest passes status_callback kwarg to messages.create()
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.standup.models import StandupEntry
from apps.standup.tasks import send_morning_checkin, send_evening_digest


PATCH_TWILIO = 'apps.standup.tasks.Client'

TWILIO_SETTINGS = dict(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
    WEBHOOK_BASE_URL='https://example.com',
)


def make_entry(phone, message='Test message'):
    """Create a StandupEntry for the given phone number."""
    import datetime
    week = datetime.datetime.now().isocalendar()[1]
    return StandupEntry.objects.create(
        phone_number=phone,
        message=message,
        week_number=week,
    )


@override_settings(**TWILIO_SETTINGS)
class TwilioStatusCallbackViewTests(TestCase):
    """Tests for POST /standup/twilio-status/."""

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('twilio-status-callback')

    def _post(self, data):
        """POST to the status callback endpoint."""
        return self.client.post(self.url, data=data, format='multipart')

    # ------------------------------------------------------------------
    # Success statuses: sent, delivered -> logger.info
    # ------------------------------------------------------------------

    def test_sent_status_returns_204_and_logs_info(self):
        """'sent' status returns HTTP 204 and calls logger.info."""
        with patch('apps.standup.views.logger') as mock_logger:
            response = self._post({
                'MessageSid': 'SM123',
                'To': 'whatsapp:+1234567890',
                'MessageStatus': 'sent',
            })
        self.assertEqual(response.status_code, 204)
        mock_logger.info.assert_called_once()
        mock_logger.error.assert_not_called()
        # Verify key fields appear in the log call args
        call_args = mock_logger.info.call_args
        log_args = call_args[0]  # positional args
        self.assertIn('SM123', log_args)
        self.assertIn('whatsapp:+1234567890', log_args)
        self.assertIn('sent', log_args)

    def test_delivered_status_returns_204_and_logs_info(self):
        """'delivered' status returns HTTP 204 and calls logger.info."""
        with patch('apps.standup.views.logger') as mock_logger:
            response = self._post({
                'MessageSid': 'SM456',
                'To': 'whatsapp:+9876543210',
                'MessageStatus': 'delivered',
            })
        self.assertEqual(response.status_code, 204)
        mock_logger.info.assert_called_once()
        mock_logger.error.assert_not_called()

    # ------------------------------------------------------------------
    # Error statuses: failed, undelivered, queued -> logger.error
    # ------------------------------------------------------------------

    def test_failed_status_returns_204_and_logs_error_with_details(self):
        """'failed' status returns HTTP 204 and calls logger.error with ErrorCode/ErrorMessage."""
        with patch('apps.standup.views.logger') as mock_logger:
            response = self._post({
                'MessageSid': 'SM789',
                'To': 'whatsapp:+1111111111',
                'MessageStatus': 'failed',
                'ErrorCode': '63038',
                'ErrorMessage': 'Daily limit exceeded',
            })
        self.assertEqual(response.status_code, 204)
        mock_logger.error.assert_called_once()
        mock_logger.info.assert_not_called()
        # Verify error code and message appear in the log call
        call_args = mock_logger.error.call_args
        log_args = call_args[0]
        self.assertIn('SM789', log_args)
        self.assertIn('whatsapp:+1111111111', log_args)
        self.assertIn('failed', log_args)
        self.assertIn('63038', log_args)
        self.assertIn('Daily limit exceeded', log_args)

    def test_undelivered_status_returns_204_and_logs_error(self):
        """'undelivered' status returns HTTP 204 and calls logger.error."""
        with patch('apps.standup.views.logger') as mock_logger:
            response = self._post({
                'MessageSid': 'SMABC',
                'To': 'whatsapp:+2222222222',
                'MessageStatus': 'undelivered',
                'ErrorCode': '30008',
                'ErrorMessage': 'Unknown error',
            })
        self.assertEqual(response.status_code, 204)
        mock_logger.error.assert_called_once()
        mock_logger.info.assert_not_called()

    def test_queued_status_returns_204_and_logs_error(self):
        """'queued' status (non-success) returns HTTP 204 and calls logger.error."""
        with patch('apps.standup.views.logger') as mock_logger:
            response = self._post({
                'MessageSid': 'SMXYZ',
                'To': 'whatsapp:+3333333333',
                'MessageStatus': 'queued',
            })
        self.assertEqual(response.status_code, 204)
        mock_logger.error.assert_called_once()
        mock_logger.info.assert_not_called()

    # ------------------------------------------------------------------
    # CSRF-exempt: POST without CSRF token must work
    # ------------------------------------------------------------------

    def test_csrf_exempt_post_without_token_succeeds(self):
        """
        The status callback endpoint must be CSRF-exempt so Twilio's server
        can POST to it without a CSRF token.
        """
        from django.test import Client as DjangoClient
        csrf_client = DjangoClient(enforce_csrf_checks=True)
        response = csrf_client.post(
            self.url,
            data={
                'MessageSid': 'SMCSRF',
                'To': 'whatsapp:+4444444444',
                'MessageStatus': 'sent',
            },
        )
        # Should NOT return 403 Forbidden (CSRF failure)
        self.assertNotEqual(response.status_code, 403)
        self.assertEqual(response.status_code, 204)


# ---------------------------------------------------------------------------
# Task tests: verify status_callback kwarg is passed to messages.create()
# ---------------------------------------------------------------------------

@override_settings(**TWILIO_SETTINGS)
class TaskStatusCallbackKwargTests(TestCase):
    """Verify that tasks pass status_callback to every Twilio messages.create() call."""

    PHONE_A = 'whatsapp:+5555555555'

    def _make_entry(self):
        make_entry(self.PHONE_A)

    def test_send_morning_checkin_passes_status_callback(self):
        """send_morning_checkin must pass status_callback= to messages.create()."""
        self._make_entry()
        mock_client = MagicMock()
        with patch(PATCH_TWILIO, return_value=mock_client):
            send_morning_checkin()

        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args.kwargs
        self.assertIn('status_callback', call_kwargs)
        self.assertEqual(
            call_kwargs['status_callback'],
            'https://example.com/standup/twilio-status/',
        )

    def test_send_evening_digest_passes_status_callback(self):
        """send_evening_digest must pass status_callback= to messages.create()."""
        self._make_entry()
        mock_client = MagicMock()
        with patch(PATCH_TWILIO, return_value=mock_client):
            send_evening_digest()

        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args.kwargs
        self.assertIn('status_callback', call_kwargs)
        self.assertEqual(
            call_kwargs['status_callback'],
            'https://example.com/standup/twilio-status/',
        )
