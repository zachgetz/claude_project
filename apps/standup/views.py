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
