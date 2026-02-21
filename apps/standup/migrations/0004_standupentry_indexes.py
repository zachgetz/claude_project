"""Migration: add database indexes to StandupEntry for query performance."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('standup', '0003_register_purge_task'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='standupentry',
            index=models.Index(fields=['phone_number'], name='standup_phone_idx'),
        ),
        migrations.AddIndex(
            model_name='standupentry',
            index=models.Index(fields=['week_number'], name='standup_week_idx'),
        ),
        migrations.AddIndex(
            model_name='standupentry',
            index=models.Index(fields=['created_at'], name='standup_created_idx'),
        ),
        migrations.AddIndex(
            model_name='standupentry',
            index=models.Index(fields=['phone_number', 'week_number'], name='standup_phone_week_idx'),
        ),
    ]
