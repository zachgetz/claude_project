import logging

import pytz
from django.http import HttpResponse, HttpResponseRedirect
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .oauth import get_oauth_flow
from .models import CalendarToken, CalendarWatchChannel

logger = logging.getLogger(__name__)


class CalendarAuthStartView(View):
    """
    GET /calendar/auth/start/?phone=+1234567890
    Stores phone in session and redirects to Google OAuth.
    """

    def get(self, request):
        phone = request.GET.get('phone', '').strip()
        if not phone:
            return HttpResponse('Missing ?phone parameter.', status=400)

        request.session['oauth_phone'] = phone

        redirect_uri = request.build_absolute_uri('/calendar/auth/callback/')
        flow = get_oauth_flow(redirect_uri=redirect_uri)
        auth_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',
        )
        request.session['oauth_state'] = state
        return HttpResponseRedirect(auth_url)


class CalendarAuthCallbackView(View):
    """
    GET /calendar/auth/callback/
    Handles the OAuth2 code, stores tokens in CalendarToken.
    """

    def get(self, request):
        phone = request.session.get('oauth_phone')
        if not phone:
            return HttpResponse('Session expired. Please restart OAuth flow.', status=400)

        redirect_uri = request.build_absolute_uri('/calendar/auth/callback/')
        flow = get_oauth_flow(redirect_uri=redirect_uri)

        try:
            flow.fetch_token(code=request.GET.get('code'))
        except Exception as e:
            return HttpResponse(f'OAuth error: {e}', status=400)

        creds = flow.credentials

        token_expiry = None
        if creds.expiry:
            token_expiry = creds.expiry.replace(tzinfo=pytz.UTC)

        CalendarToken.objects.update_or_create(
            phone_number=phone,
            defaults={
                'access_token': creds.token,
                'refresh_token': creds.refresh_token or '',
                'token_expiry': token_expiry,
            },
        )

        # Register Google Calendar push notification watch channel
        try:
            from .sync import register_watch_channel
            register_watch_channel(phone)
        except Exception as exc:
            logger.warning('Could not register watch channel for %s: %s', phone, exc)

        # Clean up session
        request.session.pop('oauth_phone', None)
        request.session.pop('oauth_state', None)

        return HttpResponse(
            '<h1>Connected!</h1><p>Your Google Calendar is now linked to the WhatsApp bot.</p>',
            content_type='text/html',
        )


@method_decorator(csrf_exempt, name='dispatch')
class CalendarNotificationsView(View):
    """
    POST /calendar/notifications/
    Receives Google Calendar push notification pings.
    """

    def post(self, request):
        channel_id_header = request.headers.get('X-Goog-Channel-ID', '').strip()
        resource_id_header = request.headers.get('X-Goog-Resource-ID', '').strip()

        if not channel_id_header:
            return HttpResponse('Missing X-Goog-Channel-ID', status=400)

        try:
            watch_channel = CalendarWatchChannel.objects.get(channel_id=channel_id_header)
        except CalendarWatchChannel.DoesNotExist:
            logger.warning('Received notification for unknown channel_id: %s', channel_id_header)
            return HttpResponse('Unknown channel', status=404)

        phone_number = watch_channel.phone_number

        # Sync calendar and detect changes
        try:
            from .calendar_service import sync_calendar_snapshot
            changes = sync_calendar_snapshot(phone_number)
        except Exception as exc:
            logger.exception('Error syncing calendar snapshot for %s: %s', phone_number, exc)
            return HttpResponse('OK', status=200)

        # Send change alerts
        try:
            from .sync import send_change_alerts
            send_change_alerts(phone_number, changes)
        except Exception as exc:
            logger.exception('Error sending change alerts for %s: %s', phone_number, exc)

        return HttpResponse('OK', status=200)


calendar_auth_start = CalendarAuthStartView.as_view()
calendar_auth_callback = CalendarAuthCallbackView.as_view()
calendar_notifications = CalendarNotificationsView.as_view()
