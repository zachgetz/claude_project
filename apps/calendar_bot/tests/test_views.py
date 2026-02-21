"""
Unit tests for apps.calendar_bot.views.

Covers CalendarAuthStartView, CalendarAuthCallbackView, and CalendarNotificationsView.
All Google OAuth and Twilio calls are mocked.
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory, Client, override_settings

from apps.calendar_bot.models import CalendarToken, CalendarWatchChannel


@override_settings(
    GOOGLE_CLIENT_ID='fake_id',
    GOOGLE_CLIENT_SECRET='fake_secret',
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
    SESSION_ENGINE='django.contrib.sessions.backends.db',
)
class CalendarAuthStartTests(TestCase):
    """Tests for GET /calendar/auth/start/"""

    def setUp(self):
        self.client = Client()

    @patch('apps.calendar_bot.views.get_oauth_flow')
    def test_redirects_to_google_oauth(self, mock_flow_factory):
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ('https://accounts.google.com/o/oauth2/auth?foo', 'state123')
        mock_flow_factory.return_value = mock_flow

        response = self.client.get('/calendar/auth/start/?phone=+1234567890')

        self.assertRedirects(
            response,
            'https://accounts.google.com/o/oauth2/auth?foo',
            fetch_redirect_response=False,
        )

    @patch('apps.calendar_bot.views.get_oauth_flow')
    def test_stores_phone_in_session(self, mock_flow_factory):
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ('https://accounts.google.com/auth', 'state_xyz')
        mock_flow_factory.return_value = mock_flow

        self.client.get('/calendar/auth/start/?phone=+9876543210')

        session = self.client.session
        self.assertEqual(session.get('oauth_phone'), '+9876543210')

    @patch('apps.calendar_bot.views.get_oauth_flow')
    def test_stores_state_in_session(self, mock_flow_factory):
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ('https://accounts.google.com/auth', 'state_csrf_abc')
        mock_flow_factory.return_value = mock_flow

        self.client.get('/calendar/auth/start/?phone=+1111111111')

        session = self.client.session
        self.assertEqual(session.get('oauth_state'), 'state_csrf_abc')

    def test_missing_phone_returns_400(self):
        response = self.client.get('/calendar/auth/start/')
        self.assertEqual(response.status_code, 400)


@override_settings(
    GOOGLE_CLIENT_ID='fake_id',
    GOOGLE_CLIENT_SECRET='fake_secret',
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
    SESSION_ENGINE='django.contrib.sessions.backends.db',
    WEBHOOK_BASE_URL='https://example.com',
)
class CalendarAuthCallbackTests(TestCase):
    """Tests for GET /calendar/auth/callback/"""

    def setUp(self):
        self.client = Client()

    def _set_session(self, phone='+1234567890', state='test_state'):
        session = self.client.session
        session['oauth_phone'] = phone
        session['oauth_state'] = state
        session.save()

    @patch('apps.calendar_bot.views.get_oauth_flow')
    def test_rejects_invalid_state(self, mock_flow_factory):
        self._set_session(state='correct_state')
        response = self.client.get('/calendar/auth/callback/?code=abc&state=wrong_state')
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Invalid state', response.content)

    @patch('apps.calendar_bot.views.get_oauth_flow')
    def test_missing_session_returns_400(self, mock_flow_factory):
        # No session set
        response = self.client.get('/calendar/auth/callback/?code=abc&state=some_state')
        self.assertEqual(response.status_code, 400)

    @patch('apps.calendar_bot.sync.register_watch_channel')
    @patch('apps.calendar_bot.views.get_oauth_flow')
    def test_stores_tokens_on_success(self, mock_flow_factory, mock_register):
        self._set_session(phone='+1234567890', state='valid_state')

        mock_flow = MagicMock()
        mock_flow.credentials.token = 'new_access_token'
        mock_flow.credentials.refresh_token = 'new_refresh_token'
        mock_flow.credentials.expiry = None
        mock_flow_factory.return_value = mock_flow
        mock_register.return_value = MagicMock()

        response = self.client.get('/calendar/auth/callback/?code=auth_code&state=valid_state')

        self.assertEqual(response.status_code, 200)
        token = CalendarToken.objects.get(phone_number='+1234567890')
        self.assertEqual(token.access_token, 'new_access_token')
        self.assertEqual(token.refresh_token, 'new_refresh_token')

    @patch('apps.calendar_bot.sync.register_watch_channel')
    @patch('apps.calendar_bot.views.get_oauth_flow')
    def test_calls_register_watch_channel(self, mock_flow_factory, mock_register):
        self._set_session(phone='+1234567890', state='valid_state')

        mock_flow = MagicMock()
        mock_flow.credentials.token = 'tok'
        mock_flow.credentials.refresh_token = 'ref'
        mock_flow.credentials.expiry = None
        mock_flow_factory.return_value = mock_flow

        self.client.get('/calendar/auth/callback/?code=auth_code&state=valid_state')

        mock_register.assert_called_once_with('+1234567890')

    @patch('apps.calendar_bot.sync.register_watch_channel')
    @patch('apps.calendar_bot.views.get_oauth_flow')
    def test_clears_session_after_callback(self, mock_flow_factory, mock_register):
        self._set_session(phone='+1234567890', state='valid_state')

        mock_flow = MagicMock()
        mock_flow.credentials.token = 'tok'
        mock_flow.credentials.refresh_token = 'ref'
        mock_flow.credentials.expiry = None
        mock_flow_factory.return_value = mock_flow

        self.client.get('/calendar/auth/callback/?code=auth_code&state=valid_state')

        session = self.client.session
        self.assertNotIn('oauth_phone', session)
        self.assertNotIn('oauth_state', session)


@override_settings(
    GOOGLE_CLIENT_ID='fake_id',
    GOOGLE_CLIENT_SECRET='fake_secret',
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test_token',
    TWILIO_WHATSAPP_NUMBER='whatsapp:+15005550006',
)
class CalendarNotificationsTests(TestCase):
    """Tests for POST /calendar/notifications/"""

    PHONE = '+1234567890'

    def setUp(self):
        self.client = Client()
        CalendarToken.objects.create(
            phone_number=self.PHONE,
            access_token='a',
            refresh_token='b',
        )

    def test_missing_channel_id_header_returns_400(self):
        response = self.client.post(
            '/calendar/notifications/',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_channel_id_returns_404(self):
        response = self.client.post(
            '/calendar/notifications/',
            content_type='application/json',
            HTTP_X_GOOG_CHANNEL_ID='00000000-0000-0000-0000-000000000000',
        )
        self.assertEqual(response.status_code, 404)

    @patch('apps.calendar_bot.sync.send_change_alerts')
    @patch('apps.calendar_bot.calendar_service.sync_calendar_snapshot')
    def test_calls_sync_for_known_channel(self, mock_sync, mock_alerts):
        import uuid
        channel = CalendarWatchChannel.objects.create(
            phone_number=self.PHONE,
        )
        mock_sync.return_value = []
        mock_alerts.return_value = None

        response = self.client.post(
            '/calendar/notifications/',
            content_type='application/json',
            HTTP_X_GOOG_CHANNEL_ID=str(channel.channel_id),
        )

        self.assertEqual(response.status_code, 200)
        mock_sync.assert_called_once_with(self.PHONE)

    @patch('apps.calendar_bot.sync.send_change_alerts')
    @patch('apps.calendar_bot.calendar_service.sync_calendar_snapshot')
    def test_sends_change_alerts_after_sync(self, mock_sync, mock_alerts):
        channel = CalendarWatchChannel.objects.create(
            phone_number=self.PHONE,
        )
        changes = [{'type': 'new', 'event_id': 'e1', 'title': 'Meeting',
                    'old_start': None, 'new_start': None}]
        mock_sync.return_value = changes
        mock_alerts.return_value = None

        self.client.post(
            '/calendar/notifications/',
            content_type='application/json',
            HTTP_X_GOOG_CHANNEL_ID=str(channel.channel_id),
        )

        mock_alerts.assert_called_once_with(self.PHONE, changes)
