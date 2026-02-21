from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('standup', '0004_standupentry_indexes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='standupentry',
            name='phone_number',
            field=models.CharField(max_length=30),
        ),
    ]
