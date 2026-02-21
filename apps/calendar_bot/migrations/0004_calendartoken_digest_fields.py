from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calendar_bot', '0003_calendarevent_snapshot'),
    ]

    operations = [
        migrations.AddField(
            model_name='calendartoken',
            name='digest_enabled',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='calendartoken',
            name='digest_hour',
            field=models.IntegerField(default=8),
        ),
        migrations.AddField(
            model_name='calendartoken',
            name='digest_minute',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='calendartoken',
            name='digest_always',
            field=models.BooleanField(default=False),
        ),
    ]
