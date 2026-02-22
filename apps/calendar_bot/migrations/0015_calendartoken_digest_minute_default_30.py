from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Schema migration: change digest_minute field default from 0 to 30.
    """

    dependencies = [
        ('calendar_bot', '0014_usermenustate_calendartoken_pending_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='calendartoken',
            name='digest_minute',
            field=models.IntegerField(default=30),
        ),
    ]
