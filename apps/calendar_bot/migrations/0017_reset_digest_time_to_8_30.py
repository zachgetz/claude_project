from django.db import migrations


def reset_digest_time(apps, schema_editor):
    """Reset all tokens to 8:30 AM digest time."""
    CalendarToken = apps.get_model('calendar_bot', 'CalendarToken')
    CalendarToken.objects.all().update(digest_hour=8, digest_minute=30)


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
