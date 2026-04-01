import json
import os
from email.utils import parseaddr
from urllib import error, request as urllib_request

from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend as SMTPEmailBackend
from django.core.mail.backends.base import BaseEmailBackend

import logging


logger = logging.getLogger(__name__)


class BrevoEmailError(RuntimeError):
    """Raised when Brevo email delivery fails in a non-transient way."""


class BrevoEmailAuthError(BrevoEmailError):
    """Raised when Brevo rejects the configured API key."""


def _brevo_headers(api_key: str) -> dict[str, str]:
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": api_key,
    }


def _read_error_body(exc: error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _has_smtp_config() -> bool:
    smtp_host = (getattr(settings, "EMAIL_HOST", "") or "").strip()
    smtp_user = (getattr(settings, "EMAIL_HOST_USER", "") or "").strip()
    smtp_pass = (getattr(settings, "EMAIL_HOST_PASSWORD", "") or "").strip()
    return bool(smtp_host and smtp_user and smtp_pass)


def check_brevo_credentials(timeout: int = 8) -> dict[str, object]:
    api_key = os.getenv("BREVO_API_KEY", "").strip()
    if not api_key:
        return {
            "ok": False,
            "status": None,
            "message": "BREVO_API_KEY is not configured.",
        }

    request_obj = urllib_request.Request(
        "https://api.brevo.com/v3/account",
        headers=_brevo_headers(api_key),
        method="GET",
    )
    try:
        with urllib_request.urlopen(request_obj, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "ok": True,
                "status": getattr(response, "status", 200),
                "message": "Brevo accepted the configured API key.",
                "body": body,
            }
    except error.HTTPError as exc:
        return {
            "ok": False,
            "status": exc.code,
            "message": _read_error_body(exc) or str(exc.reason),
        }
    except error.URLError as exc:
        return {
            "ok": False,
            "status": None,
            "message": f"Network error while contacting Brevo: {exc}",
        }


class BrevoEmailBackend(BaseEmailBackend):
    api_url = "https://api.brevo.com/v3/smtp/email"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_key = os.getenv("BREVO_API_KEY", "").strip()
        self.sender_email = (
            os.getenv("BREVO_SENDER_EMAIL")
            or parseaddr(getattr(settings, "DEFAULT_FROM_EMAIL", "00peteromondi@gmail.com"))[1]
            or "00peteromondi@gmail.com"
        )
        self.sender_name = (
            os.getenv("BREVO_SENDER_NAME")
            or parseaddr(getattr(settings, "DEFAULT_FROM_EMAIL", "BayAfya <00peteromondi@gmail.com>"))[0]
            or "BayAfya"
        )
        self.reply_to = os.getenv("BREVO_REPLY_TO", "").strip()

    def _smtp_backend(self):
        if not _has_smtp_config():
            return None
        return SMTPEmailBackend(
            host=getattr(settings, "EMAIL_HOST", ""),
            port=getattr(settings, "EMAIL_PORT", 587),
            username=getattr(settings, "EMAIL_HOST_USER", ""),
            password=getattr(settings, "EMAIL_HOST_PASSWORD", ""),
            use_tls=getattr(settings, "EMAIL_USE_TLS", True),
            use_ssl=getattr(settings, "EMAIL_USE_SSL", False),
            timeout=getattr(settings, "EMAIL_TIMEOUT", 10),
            fail_silently=self.fail_silently,
        )

    def _deliver_with_smtp_fallback(self, message, reason: str) -> int:
        smtp_backend = self._smtp_backend()
        if not smtp_backend:
            logger.warning(
                "Brevo SMTP fallback is unavailable after %s because EMAIL_HOST/EMAIL_HOST_USER/EMAIL_HOST_PASSWORD are not fully configured.",
                reason,
            )
            if not self.fail_silently:
                raise BrevoEmailError(
                    f"Brevo API send failed after {reason}, and SMTP fallback is not configured."
                )
            return 0

        if not message.from_email:
            message.from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)
        try:
            sent = smtp_backend.send_messages([message]) or 0
            if sent:
                logger.info(
                    "Email delivered via SMTP fallback to %s after %s.",
                    ",".join(message.recipients()),
                    reason,
                )
            return sent
        except Exception as exc:
            logger.exception(
                "SMTP fallback failed for recipients %s after %s.",
                ",".join(message.recipients()),
                reason,
            )
            if not self.fail_silently:
                raise BrevoEmailError(
                    f"Brevo API send failed after {reason}, and SMTP fallback also failed: {exc}"
                ) from exc
            return 0

    def send_messages(self, email_messages):
        delivered = 0
        for message in email_messages:
            if not message.recipients():
                continue
            if not self.api_key:
                logger.error("BrevoEmailBackend was selected but no Brevo API key is configured.")
                delivered += self._deliver_with_smtp_fallback(message, "missing BREVO_API_KEY")
                continue
            payload = {
                "sender": {
                    "name": self.sender_name,
                    "email": self.sender_email,
                },
                "to": [{"email": recipient} for recipient in message.recipients()],
                "subject": message.subject,
            }
            if message.body:
                if getattr(message, "alternatives", None):
                    html_alternative = next((content for content, mime_type in message.alternatives if mime_type == "text/html"), "")
                    if html_alternative:
                        payload["htmlContent"] = html_alternative
                    payload["textContent"] = message.body
                elif getattr(message, "content_subtype", "plain") == "html":
                    payload["htmlContent"] = message.body
                else:
                    payload["textContent"] = message.body
            if self.reply_to:
                payload["replyTo"] = {"email": self.reply_to}

            request_obj = urllib_request.Request(
                self.api_url,
                data=json.dumps(payload).encode("utf-8"),
                headers=_brevo_headers(self.api_key),
                method="POST",
            )
            try:
                with urllib_request.urlopen(request_obj, timeout=12):
                    delivered += 1
            except error.HTTPError as exc:
                response_body = _read_error_body(exc)
                logger.error(
                    "Brevo email send failed with HTTP %s for recipients %s. Response: %s",
                    exc.code,
                    ",".join(message.recipients()),
                    response_body or exc.reason,
                )
                try:
                    sent = self._deliver_with_smtp_fallback(message, f"Brevo HTTP {exc.code}")
                    delivered += sent
                except BrevoEmailError:
                    if exc.code == 401:
                        raise BrevoEmailAuthError(
                            "Brevo rejected BREVO_API_KEY with HTTP 401. The configured key is not enabled for "
                            "transactional email on this environment."
                        ) from exc
                    raise
            except error.URLError as exc:
                logger.error(
                    "Brevo email send failed for recipients %s due to network error: %s",
                    ",".join(message.recipients()),
                    exc,
                )
                delivered += self._deliver_with_smtp_fallback(message, f"network error {exc}")
        return delivered
