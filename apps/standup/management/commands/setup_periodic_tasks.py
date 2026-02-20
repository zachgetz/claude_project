"""
Management command: setup_periodic_tasks

Idempotently creates (or updates) the django-celery-beat PeriodicTask
records for send_morning_checkin and send_evening_digest.

Usage:
    python manage.py setup_periodic_tasks
    python manage.py setup_periodic_tasks --morning-hour 9 --evening-hour 19
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from django_celery_beat.models import CrontabSchedule, PeriodicTask


class Command(BaseCommand):
    help = 'Create or update django-celery-beat schedules for standup tasks.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--morning-hour',
            type=int,
            default=getattr(settings, 'MORNING_CHECKIN_HOUR', 8),
            help='UTC hour for the morning check-in (default: 8)',
        )
        parser.add_argument(
            '--evening-hour',
            type=int,
            default=getattr(settings, 'EVENING_DIGEST_HOUR', 18),
            help='UTC hour for the evening digest (default: 18)',
        )

    def handle(self, *args, **options):
        morning_hour = options['morning_hour']
        evening_hour = options['evening_hour']

        # --- Morning check-in ---
        morning_schedule, _ = CrontabSchedule.objects.get_or_create(
            minute='0',
            hour=str(morning_hour),
            day_of_week='*',
            day_of_month='*',
            month_of_year='*',
        )
        task, created = PeriodicTask.objects.update_or_create(
            name='send_morning_checkin',
            defaults={
                'crontab': morning_schedule,
                'task': 'apps.standup.tasks.send_morning_checkin',
                'enabled': True,
                'description': f'Morning check-in WhatsApp prompt at {morning_hour:02d}:00 UTC.',
            },
        )
        action = 'Created' if created else 'Updated'
        self.stdout.write(
            self.style.SUCCESS(
                f'{action} periodic task: send_morning_checkin (hour={morning_hour})'
            )
        )

        # --- Evening digest ---
        evening_schedule, _ = CrontabSchedule.objects.get_or_create(
            minute='0',
            hour=str(evening_hour),
            day_of_week='*',
            day_of_month='*',
            month_of_year='*',
        )
        task, created = PeriodicTask.objects.update_or_create(
            name='send_evening_digest',
            defaults={
                'crontab': evening_schedule,
                'task': 'apps.standup.tasks.send_evening_digest',
                'enabled': True,
                'description': f'Evening digest WhatsApp message at {evening_hour:02d}:00 UTC.',
            },
        )
        action = 'Created' if created else 'Updated'
        self.stdout.write(
            self.style.SUCCESS(
                f'{action} periodic task: send_evening_digest (hour={evening_hour})'
            )
        )
