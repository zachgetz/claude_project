from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calendar_bot', '0002_calendartoken_timezone'),
    ]

    operations = [
        migrations.CreateModel(
            name='CalendarEventSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone_number', models.CharField(max_length=30)),
                ('event_id', models.CharField(max_length=255)),
                ('title', models.CharField(max_length=500)),
                ('start_time', models.DateTimeField()),
                ('end_time', models.DateTimeField()),
                ('status', models.CharField(default='active', max_length=20)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'unique_together': {('phone_number', 'event_id')},
            },
        ),
    ]
