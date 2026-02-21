from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calendar_bot', '0012_onboardingstate'),
    ]

    operations = [
        migrations.AddField(
            model_name='calendartoken',
            name='language',
            field=models.CharField(default='he', max_length=10),
        ),
    ]
