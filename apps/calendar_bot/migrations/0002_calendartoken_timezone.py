from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calendar_bot', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='calendartoken',
            name='timezone',
            field=models.CharField(default='UTC', max_length=64),
        ),
    ]
