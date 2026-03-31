from django.db import migrations, models
from django.utils import timezone


def mark_existing_users_verified(apps, schema_editor):
    User = apps.get_model("core", "User")
    User.objects.all().update(email_verified_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_staffconversation_staffconversationparticipant_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="email_verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(mark_existing_users_verified, migrations.RunPython.noop),
    ]
