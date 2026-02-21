from django.db import models
from django.utils import timezone


class StandupEntry(models.Model):
    phone_number = models.CharField(max_length=30)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    week_number = models.IntegerField()

    def save(self, *args, **kwargs):
        if not self.pk and not self.week_number:
            self.week_number = timezone.now().isocalendar()[1]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.phone_number} — Week {self.week_number}"

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Standup Entries'
        indexes = [
            models.Index(fields=['phone_number'], name='standup_phone_idx'),
            models.Index(fields=['week_number'], name='standup_week_idx'),
            models.Index(fields=['created_at'], name='standup_created_idx'),
            models.Index(fields=['phone_number', 'week_number'], name='standup_phone_week_idx'),
        ]
