from django.db import migrations


def reset_digest_time(apps, schema_editor):
    """Set digest time to 20:23 (8:23 PM) for testing."""
    CalendarToken = apps.get_model('calendar_bot', 'CalendarToken')
    CalendarToken.objects.all().update(digest_hour=20, digest_minute=23)


class Migration(migrations.Migration):

    dependencies = [
        ('calendar_bot', '0016_backfill_digest_minute_to_30'),
    ]

    operations = [
        migrations.RunPython(
            reset_digest_time,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
