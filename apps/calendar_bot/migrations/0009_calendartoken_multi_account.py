from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calendar_bot', '0008_pendingblockconfirmation_pending_at'),
    ]

    operations = [
        # 1. Remove unique=True from phone_number
        migrations.AlterField(
            model_name='calendartoken',
            name='phone_number',
            field=models.CharField(max_length=30),
        ),
        # 2. Add account_email field
        migrations.AddField(
            model_name='calendartoken',
            name='account_email',
            field=models.CharField(default='', max_length=255),
        ),
        # 3. Add account_label field
        migrations.AddField(
            model_name='calendartoken',
            name='account_label',
            field=models.CharField(default='primary', max_length=50),
        ),
        # 4. Add unique_together constraint
        migrations.AlterUniqueTogether(
            name='calendartoken',
            unique_together={('phone_number', 'account_email')},
        ),
    ]
