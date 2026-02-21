from django.urls import path
from apps.standup.views import WhatsAppWebhookView, TwilioStatusCallbackView

urlpatterns = [
    path('webhook/', WhatsAppWebhookView.as_view(), name='whatsapp-webhook'),
    path('twilio-status/', TwilioStatusCallbackView.as_view(), name='twilio-status-callback'),
]
