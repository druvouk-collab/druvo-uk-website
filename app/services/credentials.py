"""Encrypted storage for marketplace credentials (Fernet / AES-128-CBC + HMAC, key from CREDENTIALS_KEY)."""

from __future__ import annotations

import json
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from app.config import get_settings
from app.db import models
from app.db.base import session_scope


class CredentialsError(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = get_settings().credentials_key.strip()
    if not key:
        raise CredentialsError("CREDENTIALS_KEY is not set — marketplace credentials can't be stored securely.")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        if len(key) < 32:
            raise CredentialsError("CREDENTIALS_KEY is too short (use 32+ random characters).") from None
        # Any long random secret (e.g. Render's generated value) is turned into a Fernet key.
        import base64
        import hashlib

        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def save_credentials(channel_code: str, secrets: dict, *, environment: str, account_label: str = "",
                     expires_at: datetime | None = None) -> None:
    if environment not in ("sandbox", "production"):
        raise CredentialsError("environment must be 'sandbox' or 'production'.")
    token = _fernet().encrypt(json.dumps(secrets).encode()).decode()
    with session_scope() as db:
        row = db.scalar(select(models.ChannelCredential).where(models.ChannelCredential.channel_code == channel_code))
        if row is None:
            row = models.ChannelCredential(channel_code=channel_code, encrypted=token)
            db.add(row)
        row.encrypted, row.environment, row.account_label, row.expires_at = token, environment, account_label[:200], expires_at


def load_credentials(channel_code: str) -> dict | None:
    with session_scope() as db:
        row = db.scalar(select(models.ChannelCredential).where(models.ChannelCredential.channel_code == channel_code))
        if row is None:
            return None
        token, env = row.encrypted, row.environment
    try:
        data = json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as exc:
        raise CredentialsError(f"Stored {channel_code} credentials can't be decrypted (CREDENTIALS_KEY changed?).") from exc
    data["_environment"] = env
    return data


def credential_summary() -> dict[str, dict]:
    """Safe-to-display facts only (never the secrets)."""
    with session_scope() as db:
        return {r.channel_code: {"environment": r.environment, "account": r.account_label, "updated": r.updated_at,
                                 "expires": r.expires_at}
                for r in db.scalars(select(models.ChannelCredential)).all()}
