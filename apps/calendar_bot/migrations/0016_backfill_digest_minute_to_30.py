from django.db import migrations


def backfill_digest_minute(apps, schema_editor):
    """
    Update existing CalendarToken rows that still have the old default
    (digest_hour=8, digest_minute=0) to the new default (digest_minute=30).
    These are users who never explicitly changed their digest time.
    """
    CalendarToken = apps.get_model('calendar_bot', 'CalendarToken')
    CalendarToken.objects.filter(
        digest_hour=8,
        digest_minute=0,
    ).update(digest_minute=30)


def reverse_backfill_digest_minute(apps, schema_editor):
    """
    Reverse: set digest_minute back to 0 for rows where digest_hour=8
    and digest_minute=30 (best-effort reverse).
    """
    CalendarToken = apps.get_model('calendar_bot', 'CalendarToken')
    CalendarToken.objects.filter(
        digest_hour=8,
        digest_minute=30,
    ).update(digest_minute=0)


class Migration(migrations.Migration):
    """
    Data migration: backfill existing rows with digest_hour=8, digest_minute=0
    to use the new default of digest_minute=30.
    """

    dependencies = [
        ('calendar_bot', '0015_calendartoken_digest_minute_default_30'),
    ]

    operations = [
        migrations.RunPython(
            backfill_digest_minute,
            reverse_code=reverse_backfill_digest_minute,
        ),
    ]
