"""Transactional email — Resend HTTP API (preferred) or SMTP. Secrets from environment only.

Resend is used when RESEND_API_KEY is set: it works on hosts that block SMTP
ports (e.g. Render Free) and supports idempotency keys so a retried send never
emails the customer twice.
"""

from __future__ import annotations

import logging
import smtplib

import httpx
from email.message import EmailMessage

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings_override = settings

    @property
    def _settings(self) -> Settings:
        return self._settings_override or get_settings()

    @property
    def configured(self) -> bool:
        s = self._settings
        return bool(s.resend_api_key) or bool(s.smtp_host and s.smtp_from)

    def send(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        html: str | None = None,
        idempotency_key: str | None = None,
        reply_to: str | None = None,
    ) -> bool:
        if not self.configured:
            logger.info("Email skipped — no email provider configured.")
            return False
        recipient = to_email.strip()
        if not recipient:
            return False
        if self._settings.resend_api_key:
            return self._send_resend(recipient, subject, body, html, idempotency_key, reply_to)
        message = EmailMessage()
        message["From"] = self._settings.smtp_from
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        if html:
            message.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port, timeout=20) as smtp:
                if self._settings.smtp_use_tls:
                    smtp.starttls()
                if self._settings.smtp_user:
                    smtp.login(self._settings.smtp_user, self._settings.smtp_password)
                smtp.send_message(message)
            logger.info("Email sent to %s subject=%s", recipient, subject)
            return True
        except Exception:
            logger.exception("Email delivery failed for recipient %s", recipient)
            return False

    def _send_resend(
        self,
        recipient: str,
        subject: str,
        body: str,
        html: str | None,
        idempotency_key: str | None,
        reply_to: str | None,
    ) -> bool:
        payload: dict = {
            "from": self._settings.email_from,
            "to": [recipient],
            "subject": subject,
            "text": body,
        }
        if html:
            payload["html"] = html
        reply = reply_to or self._settings.contact_email
        if reply:
            payload["reply_to"] = reply
        headers = {"Authorization": f"Bearer {self._settings.resend_api_key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key[:256]
        try:
            response = httpx.post("https://api.resend.com/emails", json=payload, headers=headers, timeout=20)
        except httpx.HTTPError as exc:
            logger.warning("Resend request failed (%s) for subject=%s", type(exc).__name__, subject)
            return False
        if response.status_code >= 300:
            logger.warning("Resend rejected email subject=%s status=%s", subject, response.status_code)
            return False
        logger.info("Email sent via Resend subject=%s", subject)
        return True
