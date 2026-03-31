from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_user_email_verification_limits"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="email_verification_failed_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="user",
            name="email_verification_failed_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
