from django.db import models


class CalendarToken(models.Model):
    phone_number = models.CharField(max_length=30, unique=True)
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_expiry = models.DateTimeField(null=True, blank=True)
    timezone = models.CharField(max_length=64, default='UTC')
    digest_enabled = models.BooleanField(default=True)
    digest_hour = models.IntegerField(default=8)
    digest_minute = models.IntegerField(default=0)
    digest_always = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'CalendarToken({self.phone_number})'
