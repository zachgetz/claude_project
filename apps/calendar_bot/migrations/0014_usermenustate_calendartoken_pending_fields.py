from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calendar_bot', '0013_calendartoken_language'),
    ]

    operations = [
        migrations.AddField(
            model_name='calendartoken',
            name='pending_action',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='calendartoken',
            name='pending_step',
            field=models.IntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='calendartoken',
            name='pending_data',
            field=models.JSONField(null=True, blank=True),
        ),
        migrations.CreateModel(
            name='UserMenuState',
            fields=[
                ('phone_number', models.CharField(max_length=30, primary_key=True, serialize=False)),
                ('pending_action', models.CharField(blank=True, max_length=50, null=True)),
                ('pending_step', models.IntegerField(blank=True, null=True)),
                ('pending_data', models.JSONField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
