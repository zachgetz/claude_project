from django.db import migrations


def remove_morning_checkin_task(apps, schema_editor):
    """Delete the send_morning_checkin periodic task if it exists in the DB."""
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        PeriodicTask.objects.filter(
            task='apps.standup.tasks.send_morning_checkin'
        ).delete()
    except LookupError:
        # django_celery_beat not installed or table doesn't exist yet
        pass


class Migration(migrations.Migration):

    dependencies = [
        ('standup', '0002_alter_standupentry_options'),
    ]

    operations = [
        migrations.RunPython(
            remove_morning_checkin_task,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
