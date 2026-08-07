"""Transactional email via SMTP — secrets from environment only."""

from __future__ import annotations

import logging
import smtplib
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
        return bool(s.smtp_host and s.smtp_from)

    def send(self, *, to_email: str, subject: str, body: str) -> bool:
        if not self.configured:
            logger.info("Email skipped — SMTP not configured.")
            return False
        recipient = to_email.strip()
        if not recipient:
            return False
        message = EmailMessage()
        message["From"] = self._settings.smtp_from
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
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
