import uuid

from django.db import models


class CalendarToken(models.Model):
    phone_number = models.CharField(max_length=30)
    account_email = models.CharField(max_length=255, default='')
    account_label = models.CharField(max_length=50, default='primary')
    name = models.CharField(max_length=100, blank=True, default='')
    language = models.CharField(max_length=10, default='he')
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

    class Meta:
        unique_together = [('phone_number', 'account_email')]

    def __str__(self):
        return f'CalendarToken({self.phone_number})'


class CalendarEventSnapshot(models.Model):
    phone_number = models.CharField(max_length=30, db_index=True)
    token = models.ForeignKey(
        'CalendarToken',
        null=True,
        on_delete=models.CASCADE,
        related_name='event_snapshots',
    )
    event_id = models.CharField(max_length=255)
    title = models.CharField(max_length=500)
    start_time = models.DateTimeField()  # timezone-aware
    end_time = models.DateTimeField()    # timezone-aware
    status = models.CharField(max_length=20, default='active')  # 'active' or 'cancelled'
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('phone_number', 'token', 'event_id')]

    def __str__(self):
        return f'CalendarEventSnapshot({self.phone_number}, {self.event_id})'


class CalendarWatchChannel(models.Model):
    phone_number = models.CharField(max_length=30, db_index=True)
    token = models.ForeignKey(
        'CalendarToken',
        null=True,
        on_delete=models.CASCADE,
        related_name='watch_channels',
    )
    channel_id = models.UUIDField(default=uuid.uuid4)
    resource_id = models.CharField(max_length=255, blank=True)
    expiry = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('phone_number', 'channel_id')]

    def __str__(self):
        return f'CalendarWatchChannel({self.phone_number}, {self.channel_id})'


class PendingBlockConfirmation(models.Model):
    phone_number = models.CharField(max_length=30)
    event_data = models.JSONField()  # {date, start, end, title}
    # pending_at records when the confirmation was requested; used to enforce
    # the 10-minute expiry window in confirm_block_command().
    pending_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # one pending per user max
        unique_together = [('phone_number',)]

    def __str__(self):
        return f'PendingBlockConfirmation({self.phone_number})'


class OnboardingState(models.Model):
    """
    Tracks a user mid-onboarding flow.
    Created when a new user sends their first message.
    Deleted once the user provides their name.
    """
    STEP_AWAITING_NAME = 'awaiting_name'
    STEP_CHOICES = [
        (STEP_AWAITING_NAME, 'Awaiting name'),
    ]

    phone_number = models.CharField(max_length=20, primary_key=True)
    step = models.CharField(max_length=50, choices=STEP_CHOICES, default=STEP_AWAITING_NAME)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'calendar_bot_onboardingstate'

    def __str__(self):
        return f'OnboardingState({self.phone_number}, step={self.step})'
