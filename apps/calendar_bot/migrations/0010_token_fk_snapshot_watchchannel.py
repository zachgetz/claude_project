import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calendar_bot', '0009_calendartoken_multi_account'),
    ]

    operations = [
        # 1. Add token FK to CalendarEventSnapshot (nullable)
        migrations.AddField(
            model_name='calendareventsnapshot',
            name='token',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='event_snapshots',
                to='calendar_bot.calendartoken',
            ),
        ),
        # 2. Add token FK to CalendarWatchChannel (nullable)
        migrations.AddField(
            model_name='calendarwatchchannel',
            name='token',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='watch_channels',
                to='calendar_bot.calendartoken',
            ),
        ),
        # 3. First drop old unique_together on CalendarEventSnapshot
        migrations.AlterUniqueTogether(
            name='calendareventsnapshot',
            unique_together=set(),
        ),
        # 4. Then add new unique_together including token
        migrations.AlterUniqueTogether(
            name='calendareventsnapshot',
            unique_together={('phone_number', 'token', 'event_id')},
        ),
    ]
