import uuid

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


class CalendarEventSnapshot(models.Model):
    phone_number = models.CharField(max_length=30)
    event_id = models.CharField(max_length=255)
    title = models.CharField(max_length=500)
    start_time = models.DateTimeField()  # timezone-aware
    end_time = models.DateTimeField()    # timezone-aware
    status = models.CharField(max_length=20, default='active')  # 'active' or 'cancelled'
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('phone_number', 'event_id')]

    def __str__(self):
        return f'CalendarEventSnapshot({self.phone_number}, {self.event_id})'


class CalendarWatchChannel(models.Model):
    phone_number = models.CharField(max_length=30)
    channel_id = models.UUIDField(default=uuid.uuid4)
    resource_id = models.CharField(max_length=255, blank=True)
    expiry = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('phone_number', 'channel_id')]

    def __str__(self):
        return f'CalendarWatchChannel({self.phone_number}, {self.channel_id})'
