import datetime
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

        # Handle /summary command BEFORE any saving
        if body.strip().lower() == '/summary':
            return self._handle_summary(from_number)

        # Handle set timezone command
        if body.lower().startswith('set timezone '):
            return self._handle_set_timezone(from_number, body)

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
