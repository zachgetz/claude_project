from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calendar_bot', '0006_pendingblockconfirmation'),
    ]

    operations = [
        migrations.AlterField(
            model_name='calendareventsnapshot',
            name='phone_number',
            field=models.CharField(db_index=True, max_length=30),
        ),
        migrations.AlterField(
            model_name='calendarwatchchannel',
            name='phone_number',
            field=models.CharField(db_index=True, max_length=30),
        ),
    ]
