from django.db import migrations


def set_digest_time_morning(apps, schema_editor):
    """Set digest time to 8:30 AM."""
    CalendarToken = apps.get_model('calendar_bot', 'CalendarToken')
    CalendarToken.objects.all().update(digest_hour=8, digest_minute=30)


class Migration(migrations.Migration):

    dependencies = [
        ('calendar_bot', '0017_reset_digest_time_to_8_30'),
    ]

    operations = [
        migrations.RunPython(
            set_digest_time_morning,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
