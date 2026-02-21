import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calendar_bot', '0007_add_phone_number_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='pendingblockconfirmation',
            name='pending_at',
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
            ),
            preserve_default=False,
        ),
    ]
