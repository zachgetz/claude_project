from django.db import migrations


def remove_standup_tasks(apps, schema_editor):
    """Delete all standup periodic tasks from django-celery-beat."""
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        PeriodicTask.objects.filter(task__startswith='apps.standup.tasks.').delete()
    except LookupError:
        pass


class Migration(migrations.Migration):

    dependencies = [
        ('standup', '0006_remove_morning_checkin_periodic_task'),
    ]

    operations = [
        migrations.RunPython(
            remove_standup_tasks,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
