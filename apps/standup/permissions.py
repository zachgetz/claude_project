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
        try:
            validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
            signature = request.META.get('HTTP_X_TWILIO_SIGNATURE', '')
            url = request.build_absolute_uri()
            # request.data may be a QueryDict (not a plain dict) — convert it
            if hasattr(request.data, 'dict'):
                post_params = request.data.dict()
            elif isinstance(request.data, dict):
                post_params = request.data
            else:
                post_params = {}
            return validator.validate(url, post_params, signature)
        except Exception:
            return False
