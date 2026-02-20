"""Data migration: register purge_old_standup_entries Celery-beat task."""
from django.db import migrations


def create_purge_task(apps, schema_editor):
    CrontabSchedule = apps.get_model('django_celery_beat', 'CrontabSchedule')
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')

    # Daily at 02:00 UTC — off-peak to minimise disruption
    purge_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute='0',
        hour='2',
        day_of_week='*',
        day_of_month='*',
        month_of_year='*',
    )

    PeriodicTask.objects.get_or_create(
        name='purge_old_standup_entries',
        defaults={
            'crontab': purge_schedule,
            'task': 'apps.standup.tasks.purge_old_standup_entries',
            'enabled': True,
            'description': 'Delete StandupEntry records older than STANDUP_RETENTION_DAYS (default 30) days (02:00 UTC).',
        },
    )


def remove_purge_task(apps, schema_editor):
    PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
    PeriodicTask.objects.filter(name='purge_old_standup_entries').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('standup', '0002_create_periodic_tasks'),
        ('django_celery_beat', '0018_improve_crontab_helptext'),
    ]

    operations = [
        migrations.RunPython(
            create_purge_task,
            reverse_code=remove_purge_task,
        ),
    ]
