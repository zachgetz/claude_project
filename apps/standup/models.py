import datetime
from django.db import models

class StandupEntry(models.Model):
    phone_number = models.CharField(max_length=20)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    week_number = models.IntegerField()

    def save(self, *args, **kwargs):
        if not self.pk and not self.week_number:
            self.week_number = datetime.datetime.now().isocalendar()[1]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.phone_number} — Week {self.week_number}"

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Standup Entries'
