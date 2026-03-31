from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_user_email_verified_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="email_verification_code",
            field=models.CharField(blank=True, max_length=7),
        ),
        migrations.AddField(
            model_name="user",
            name="email_verification_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
