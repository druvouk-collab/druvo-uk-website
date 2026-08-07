"""Website email service tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.config import Settings
from app.services.email_service import EmailService


def test_email_skipped_when_not_configured():
    service = EmailService(Settings(smtp_host="", smtp_from=""))
    assert service.configured is False
    assert service.send(to_email="a@b.com", subject="Hi", body="Test") is False


def test_email_configured_when_host_and_from_set():
    service = EmailService(Settings(smtp_host="smtp.test.com", smtp_from="orders@druvo.uk"))
    assert service.configured is True


def test_email_send_uses_smtp(monkeypatch):
    service = EmailService(
        Settings(
            smtp_host="smtp.test.com",
            smtp_port=587,
            smtp_user="user",
            smtp_password="pass",
            smtp_from="orders@druvo.uk",
        )
    )
    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=False)
    with patch("app.services.email_service.smtplib.SMTP", return_value=mock_smtp):
        assert service.send(to_email="buyer@example.com", subject="Order confirmed", body="Thanks") is True
    mock_smtp.starttls.assert_called_once()
    mock_smtp.login.assert_called_once()
    mock_smtp.send_message.assert_called_once()
