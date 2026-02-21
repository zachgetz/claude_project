from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('calendar_bot', '0010_token_fk_snapshot_watchchannel'),
    ]

    operations = [
        migrations.AddField(
            model_name='calendartoken',
            name='name',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
