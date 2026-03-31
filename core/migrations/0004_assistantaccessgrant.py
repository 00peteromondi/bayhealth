from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_user_profile_picture"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssistantAccessGrant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("hospital_id", models.PositiveIntegerField(blank=True, null=True)),
                ("status", models.CharField(choices=[("approved", "Approved"), ("revoked", "Revoked")], default="approved", max_length=16)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("reason", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approved_assistant_access_grants", to=settings.AUTH_USER_MODEL)),
                ("patient_user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assistant_access_grants", to=settings.AUTH_USER_MODEL)),
                ("requester", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assistant_access_requests", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="assistantaccessgrant",
            index=models.Index(fields=["requester", "patient_user", "hospital_id", "status"], name="core_assist_request_4814d6_idx"),
        ),
    ]
