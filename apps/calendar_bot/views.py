import pytz
from django.http import HttpResponse, HttpResponseRedirect
from django.views import View
from django.conf import settings

from .oauth import get_oauth_flow
from .models import CalendarToken


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

        # Clean up session
        request.session.pop('oauth_phone', None)
        request.session.pop('oauth_state', None)

        return HttpResponse(
            '<h1>Connected!</h1><p>Your Google Calendar is now linked to the WhatsApp bot.</p>',
            content_type='text/html',
        )


calendar_auth_start = CalendarAuthStartView.as_view()
calendar_auth_callback = CalendarAuthCallbackView.as_view()
