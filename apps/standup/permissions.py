from django.conf import settings
from rest_framework.permissions import BasePermission
from twilio.request_validator import RequestValidator


class TwilioSignaturePermission(BasePermission):
    """
    DRF permission that validates the X-Twilio-Signature header
    on incoming webhook requests using Twilio's RequestValidator.
    Returns 403 if the signature is missing or invalid.
    """

    def has_permission(self, request, view):
        validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)

        signature = request.META.get('HTTP_X_TWILIO_SIGNATURE', '')
        url = request.build_absolute_uri()
        post_params = request.data if isinstance(request.data, dict) else {}

        return validator.validate(url, post_params, signature)
