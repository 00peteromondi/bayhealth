import json
import os
from email.utils import parseaddr
from urllib import error, request as urllib_request

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

import logging


logger = logging.getLogger(__name__)


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

    def send_messages(self, email_messages):
        if not self.api_key:
            logger.error("BrevoEmailBackend was selected but no Brevo API key is configured.")
            return 0

        delivered = 0
        for message in email_messages:
            if not message.recipients():
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
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                    "api-key": self.api_key,
                },
                method="POST",
            )
            try:
                with urllib_request.urlopen(request_obj, timeout=12):
                    delivered += 1
            except error.HTTPError as exc:
                response_body = ""
                try:
                    response_body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    response_body = ""
                logger.error(
                    "Brevo email send failed with HTTP %s for recipients %s. Response: %s",
                    exc.code,
                    ",".join(message.recipients()),
                    response_body or exc.reason,
                )
                if not self.fail_silently:
                    raise
            except error.URLError as exc:
                logger.error(
                    "Brevo email send failed for recipients %s due to network error: %s",
                    ",".join(message.recipients()),
                    exc,
                )
                if not self.fail_silently:
                    raise
        return delivered
