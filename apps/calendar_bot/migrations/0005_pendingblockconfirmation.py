from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calendar_bot', '0004_calendarwatchchannel'),
        ('calendar_bot', '0003_calendartoken_digest_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='PendingBlockConfirmation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone_number', models.CharField(max_length=30)),
                ('event_data', models.JSONField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'unique_together': {('phone_number',)},
            },
        ),
    ]
