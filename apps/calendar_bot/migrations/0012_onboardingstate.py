from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calendar_bot', '0011_calendartoken_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='OnboardingState',
            fields=[
                ('phone_number', models.CharField(max_length=20, primary_key=True, serialize=False)),
                ('step', models.CharField(
                    choices=[('awaiting_name', 'Awaiting name')],
                    default='awaiting_name',
                    max_length=50,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'calendar_bot_onboardingstate',
            },
        ),
    ]
