from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        verified_at = getattr(user, "email_verified_at", None)
        return f"{user.pk}{user.email}{verified_at}{timestamp}"


email_verification_token_generator = EmailVerificationTokenGenerator()
