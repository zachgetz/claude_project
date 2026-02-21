import datetime
import re
from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.http import HttpResponse
from twilio.twiml.messaging_response import MessagingResponse
from apps.standup.permissions import TwilioSignaturePermission
from apps.standup.models import StandupEntry


class WhatsAppWebhookView(APIView):
    permission_classes = [TwilioSignaturePermission]

    def post(self, request, *args, **kwargs):
        from_number = request.data.get('From', '')
        body = request.data.get('Body', '')
        body_lower = body.strip().lower()

        # Handle /summary command BEFORE any saving
        if body_lower == '/summary':
            return self._handle_summary(from_number)

        # Handle set timezone command
        if body_lower.startswith('set timezone '):
            return self._handle_set_timezone(from_number, body)

        # Handle set digest command
        if body_lower.startswith('set digest'):
            return self._handle_set_digest(from_number, body_lower)

        if not body.strip():
            return Response({'error': 'Body cannot be empty.'}, status=400)

        current_week = datetime.datetime.now().isocalendar()[1]

        entry = StandupEntry.objects.create(
            phone_number=from_number,
            message=body,
            week_number=current_week,
        )

        entry_count = StandupEntry.objects.filter(
            phone_number=from_number,
            week_number=current_week,
        ).count()

        reply_text = (
            f"Got it \u2713 Logged for today (entry #{entry_count} this week). "
            "Type /summary for your weekly digest."
        )

        response = MessagingResponse()
        response.message(reply_text)

        return HttpResponse(str(response), content_type='application/xml')

    def _handle_set_digest(self, from_number, body_lower):
        from apps.calendar_bot.models import CalendarToken

        token, _ = CalendarToken.objects.get_or_create(
            phone_number=from_number,
            defaults={'access_token': '', 'refresh_token': ''},
        )

        # Parse: 'set digest off', 'set digest on', 'set digest always'
        # 'set digest 7:30am', 'set digest 9am'
        arg = body_lower[len('set digest'):].strip()

        if arg == 'off':
            token.digest_enabled = False
            token.save(update_fields=['digest_enabled', 'updated_at'])
            response = MessagingResponse()
            response.message('Morning digest turned off.')
            return HttpResponse(str(response), content_type='application/xml')

        if arg == 'on':
            token.digest_enabled = True
            token.save(update_fields=['digest_enabled', 'updated_at'])
            response = MessagingResponse()
            response.message('Morning digest turned on.')
            return HttpResponse(str(response), content_type='application/xml')

        if arg == 'always':
            token.digest_always = True
            token.save(update_fields=['digest_always', 'updated_at'])
            response = MessagingResponse()
            response.message('Morning digest will be sent even on days with no meetings.')
            return HttpResponse(str(response), content_type='application/xml')

        # Try to parse time like '7:30am', '9am', '14:00'
        parsed = _parse_digest_time(arg)
        if parsed is not None:
            hour, minute = parsed
            token.digest_hour = hour
            token.digest_minute = minute
            token.digest_enabled = True
            token.save(update_fields=['digest_hour', 'digest_minute', 'digest_enabled', 'updated_at'])
            response = MessagingResponse()
            response.message(f'Morning digest scheduled for {hour:02d}:{minute:02d} in your timezone.')
            return HttpResponse(str(response), content_type='application/xml')

        response = MessagingResponse()
        response.message(
            'Could not understand digest setting. '
            'Try: "set digest 7:30am", "set digest off", "set digest on", "set digest always".'
        )
        return HttpResponse(str(response), content_type='application/xml')

    def _handle_set_timezone(self, from_number, body):
        import pytz
        from apps.calendar_bot.models import CalendarToken

        tz_name = body[len('set timezone '):].strip()

        try:
            pytz.timezone(tz_name)
        except Exception:
            response = MessagingResponse()
            response.message(
                f"Unknown timezone '{tz_name}'. "
                "Please use a valid tz name, e.g. 'Europe/London' or 'America/New_York'."
            )
            return HttpResponse(str(response), content_type='application/xml')

        token, _ = CalendarToken.objects.get_or_create(
            phone_number=from_number,
            defaults={
                'access_token': '',
                'refresh_token': '',
            },
        )
        token.timezone = tz_name
        token.save(update_fields=['timezone', 'updated_at'])

        response = MessagingResponse()
        response.message(f"Timezone set to {tz_name}.")
        return HttpResponse(str(response), content_type='application/xml')

    def _handle_summary(self, from_number):
        current_week = datetime.datetime.now().isocalendar()[1]

        entries = StandupEntry.objects.filter(
            phone_number=from_number,
            week_number=current_week,
        ).order_by('created_at')

        response = MessagingResponse()

        if not entries.exists():
            response.message("No entries yet this week.")
        else:
            lines = [f"Week {current_week} summary:\n"]
            for entry in entries:
                date_str = entry.created_at.strftime('%Y-%m-%d')
                lines.append(f"{date_str}: {entry.message}")
            reply_text = "\n".join(lines)
            response.message(reply_text)

        return HttpResponse(str(response), content_type='application/xml')


def _parse_digest_time(arg):
    """
    Parse time strings like '7:30am', '9am', '14:00', '9:00pm'.
    Returns (hour, minute) in 24-hour format, or None if unparseable.
    """
    # Normalize
    arg = arg.strip().lower().replace(' ', '')

    # Match h:mam/pm or hampm
    m = re.match(r'^(\d{1,2})(?::(\d{2}))?(am|pm)?$', arg)
    if not m:
        return None

    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    ampm = m.group(3)

    if ampm == 'pm' and hour != 12:
        hour += 12
    elif ampm == 'am' and hour == 12:
        hour = 0

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    return hour, minute
