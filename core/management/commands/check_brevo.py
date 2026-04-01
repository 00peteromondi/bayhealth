from django.core.management.base import BaseCommand

from core.email_backends import check_brevo_credentials


class Command(BaseCommand):
    help = "Check whether the configured BREVO_API_KEY is accepted by the Brevo account endpoint."

    def handle(self, *args, **options):
        result = check_brevo_credentials()
        status = result.get("status")
        message = result.get("message", "")

        if result.get("ok"):
            self.stdout.write(self.style.SUCCESS(f"Brevo check passed ({status}): {message}"))
            return

        if status:
            self.stderr.write(self.style.ERROR(f"Brevo check failed ({status}): {message}"))
        else:
            self.stderr.write(self.style.ERROR(f"Brevo check failed: {message}"))
