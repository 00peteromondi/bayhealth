from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_user_email_verification_code_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="email_verification_locked_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="email_verification_send_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="user",
            name="email_verification_send_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
