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
    GET /calendar/auth/start/?phone=+1234567890[&label=work]
    Stores phone (and optional label) in session and redirects to Google OAuth.
    """

    def get(self, request):
        # Use the raw QUERY_STRING to preserve '+' prefix in phone numbers.
        from urllib.parse import parse_qs
        raw_qs = request.META.get('QUERY_STRING', '').replace('+', '%2B')
        params = parse_qs(raw_qs, keep_blank_values=True)
        raw_phone_list = params.get('phone', [''])
        phone = raw_phone_list[0].strip() if raw_phone_list else ''
        if not phone:
            return HttpResponse('Missing ?phone parameter.', status=400)

        # Store optional label param for multi-account labelling
        label_list = params.get('label', ['primary'])
        label = label_list[0].strip() if label_list else 'primary'

        request.session['oauth_phone'] = phone
        request.session['oauth_label'] = label

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
        error = request.GET.get('error')
        if error:
            logger.warning('OAuth callback received error: %s', error)
            return HttpResponse(
                '<h1>Authorization failed</h1>'
                f'<p>Google returned an error: <code>{error}</code></p>'
                '<p>Please go back to WhatsApp and send <strong>connect calendar</strong> to try again.</p>',
                content_type='text/html',
                status=400,
            )

        phone = request.session.get('oauth_phone')
        if not phone:
            return HttpResponse('Session expired. Please restart OAuth flow.', status=400)

        label = request.session.get('oauth_label', 'primary')

        # CSRF state validation
        returned_state = request.GET.get('state', '')
        expected_state = request.session.get('oauth_state', '')
        if not returned_state or returned_state != expected_state:
            return HttpResponse('Invalid state parameter.', status=400)

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

        # Fetch Google email to use as account_email
        email = ''
        try:
            import requests as http_requests
            userinfo_response = http_requests.get(
                'https://www.googleapis.com/oauth2/v3/userinfo',
                headers={'Authorization': f'Bearer {creds.token}'},
                timeout=10,
            )
            if userinfo_response.ok:
                email = userinfo_response.json().get('email', '')
        except Exception as exc:
            logger.warning('Could not fetch Google userinfo for phone=%s: %s', phone, exc)

        token_obj, _ = CalendarToken.objects.update_or_create(
            phone_number=phone,
            account_email=email,
            defaults={
                'account_label': label,
                'access_token': creds.token,
                'refresh_token': creds.refresh_token or '',
                'token_expiry': token_expiry,
            },
        )

        # Register Google Calendar push notification watch channel
        try:
            from .sync import register_watch_channel
            register_watch_channel(token_obj)
        except Exception as exc:
            logger.warning('Could not register watch channel for %s: %s', phone, exc)

        # Prime the snapshot table
        try:
            from .calendar_service import sync_calendar_snapshot
            sync_calendar_snapshot(token_obj, send_alerts=False)
        except Exception as exc:
            logger.warning('Could not prime calendar snapshot for %s: %s', phone, exc)

        # Clean up session
        request.session.pop('oauth_phone', None)
        request.session.pop('oauth_state', None)
        request.session.pop('oauth_label', None)

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
            watch_channel = CalendarWatchChannel.objects.select_related('token').get(
                channel_id=channel_id_header
            )
        except CalendarWatchChannel.DoesNotExist:
            logger.warning('Received notification for unknown channel_id: %s', channel_id_header)
            return HttpResponse('Unknown channel', status=404)

        phone_number = watch_channel.phone_number

        # Use the watch channel's token for scoped sync; fallback if token is NULL
        token = watch_channel.token

        # Sync calendar and detect changes
        try:
            from .calendar_service import sync_calendar_snapshot
            if token is not None:
                changes = sync_calendar_snapshot(token)
            else:
                # Legacy path: token is NULL, fall back to first token for phone
                from .models import CalendarToken as CT
                fallback_token = CT.objects.filter(
                    phone_number=phone_number
                ).order_by('created_at').first()
                if fallback_token is None:
                    logger.warning(
                        'No token found for phone=%s in CalendarNotificationsView fallback',
                        phone_number,
                    )
                    return HttpResponse('OK', status=200)
                changes = sync_calendar_snapshot(fallback_token)
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
