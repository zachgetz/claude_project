"""Data migration: register morning check-in and evening digest
Celery-beat periodic tasks via django-celery-beat PeriodicTask model.
"""
from django.db import migrations


def create_periodic_tasks(apps, schema_editor):
    CrontabSchedule = apps.get_model('django_celery_beat', 'CrontabSchedule')
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')

    # Morning check-in at 08:00 UTC every day
    morning_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute='0',
        hour='8',
        day_of_week='*',
        day_of_month='*',
        month_of_year='*',
    )

    PeriodicTask.objects.get_or_create(
        name='send_morning_checkin',
        defaults={
            'crontab': morning_schedule,
            'task': 'apps.standup.tasks.send_morning_checkin',
            'enabled': True,
            'description': 'Send WhatsApp morning check-in prompt to all users (08:00 UTC).',
        },
    )

    # Evening digest at 18:00 UTC every day
    evening_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute='0',
        hour='18',
        day_of_week='*',
        day_of_month='*',
        month_of_year='*',
    )

    PeriodicTask.objects.get_or_create(
        name='send_evening_digest',
        defaults={
            'crontab': evening_schedule,
            'task': 'apps.standup.tasks.send_evening_digest',
            'enabled': True,
            'description': 'Send WhatsApp evening digest to all users (18:00 UTC).',
        },
    )


def remove_periodic_tasks(apps, schema_editor):
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
    PeriodicTask.objects.filter(
        name__in=['send_morning_checkin', 'send_evening_digest']
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('standup', '0001_initial'),
        ('django_celery_beat', '0018_improve_crontab_helptext'),
    ]

    operations = [
        migrations.RunPython(
            create_periodic_tasks,
            reverse_code=remove_periodic_tasks,
        ),
    ]
