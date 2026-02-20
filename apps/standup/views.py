from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.http import HttpResponse
from twilio.twiml.messaging_response import MessagingResponse


class WhatsAppWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        from_number = request.data.get('From', '')
        body = request.data.get('Body', '')

        response = MessagingResponse()
        response.message("Received your message.")

        return HttpResponse(str(response), content_type='application/xml')
