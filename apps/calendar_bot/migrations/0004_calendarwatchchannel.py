import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calendar_bot', '0003_calendarevent_snapshot'),
    ]

    operations = [
        migrations.CreateModel(
            name='CalendarWatchChannel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone_number', models.CharField(max_length=30)),
                ('channel_id', models.UUIDField(default=uuid.uuid4)),
                ('resource_id', models.CharField(blank=True, max_length=255)),
                ('expiry', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'unique_together': {('phone_number', 'channel_id')},
            },
        ),
    ]
