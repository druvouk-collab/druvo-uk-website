"""Admin authentication: argon2 passwords, TOTP 2FA, recovery codes, signed sessions, CSRF, rate limits."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pyotp
import segno
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select

from app.config import get_settings
from app.db import models
from app.db.base import session_scope

COOKIE_NAME = "druvo_admin"
SESSION_MAX_AGE = 12 * 60 * 60  # 12 hours
PENDING_MFA_MAX_AGE = 10 * 60  # password accepted, waiting for 2FA code
MIN_PASSWORD_LENGTH = 12
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
ISSUER = "DRUVO UK Admin"
DEV_SECRET = "dev-only-change-in-production"

_hasher = PasswordHasher()


class AdminAuthError(Exception):
    pass


# ------------------------------------------------------------------ passwords & codes


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def validate_new_password(password: str, email: str = "") -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AdminAuthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    lowered = password.lower()
    if email and email.split("@")[0].lower() in lowered:
        raise AdminAuthError("Password must not contain your email name.")
    if lowered in {"password1234", "druvo1234567", "123456789012"} or len(set(password)) < 6:
        raise AdminAuthError("Password is too easy to guess.")


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def totp_qr_svg(uri: str) -> str:
    return segno.make(uri, error="m").svg_inline(scale=5, dark="#111", light="#fff")


def verify_totp(secret: str, code: str, last_step: int = 0) -> int | None:
    """Return the accepted time-step (to store, preventing reuse) or None."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != 6 or not secret:
        return None
    totp = pyotp.TOTP(secret)
    now = int(time.time())
    for offset in (-1, 0, 1):
        step = now // 30 + offset
        if step <= last_step:
            continue
        if secrets.compare_digest(totp.at(step * 30), code):
            return step
    return None


def new_recovery_codes(count: int = 8) -> tuple[list[str], list[str]]:
    plain = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}".upper() for _ in range(count)]
    return plain, [_hasher.hash(c) for c in plain]


def use_recovery_code(hashes: list[str], code: str) -> list[str] | None:
    """Return remaining hashes if the code matched (one-time use), else None."""
    cleaned = (code or "").strip().upper()
    for index, stored in enumerate(hashes or []):
        try:
            if _hasher.verify(stored, cleaned):
                return hashes[:index] + hashes[index + 1 :]
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            continue
    return None


# ------------------------------------------------------------------ sessions


def _serializer() -> URLSafeTimedSerializer:
    secret = get_settings().session_secret
    if get_settings().production_mode and (not secret or secret == DEV_SECRET or len(secret) < 32):
        raise HTTPException(status_code=503, detail="Admin is disabled: set a strong SESSION_SECRET.")
    return URLSafeTimedSerializer(secret, salt="druvo-admin-session")


@dataclass
class AdminSession:
    admin_id: int
    email: str
    role: str
    csrf: str
    mfa: bool


def issue_cookie(response, admin: models.AdminUser, *, mfa: bool, request: Request) -> None:
    payload = {
        "uid": admin.id,
        "v": admin.session_version,
        "mfa": mfa,
        "csrf": secrets.token_urlsafe(24),
        "iat": int(time.time()),
    }
    response.set_cookie(
        COOKIE_NAME,
        _serializer().dumps(payload),
        max_age=SESSION_MAX_AGE if mfa else PENDING_MFA_MAX_AGE,
        httponly=True,
        secure=request.url.scheme == "https" or get_settings().production_mode,
        samesite="strict",
        path="/",
    )


def clear_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def read_session(request: Request, *, require_mfa: bool = True) -> AdminSession | None:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        data = _serializer().loads(raw, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    if not data.get("mfa") and time.time() - int(data.get("iat", 0)) > PENDING_MFA_MAX_AGE:
        return None
    if require_mfa and not data.get("mfa"):
        return None
    with session_scope() as db:
        admin = db.get(models.AdminUser, int(data.get("uid", 0)))
        if admin is None or not admin.is_active or admin.session_version != data.get("v"):
            return None
        return AdminSession(admin.id, admin.email, admin.role, str(data.get("csrf", "")), bool(data.get("mfa")))


def check_csrf(session: AdminSession, token: str) -> None:
    if not token or not secrets.compare_digest(session.csrf, token):
        raise HTTPException(status_code=403, detail="Security token expired — reload the page and try again.")


def admin_count() -> int:
    with session_scope() as db:
        return int(db.scalar(select(func.count(models.AdminUser.id))) or 0)


# ------------------------------------------------------------------ rate limiting


class RateLimiter:
    """Simple in-memory sliding window (per process) for login attempts by IP."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit, self.window = limit, window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.window]
            allowed = len(hits) < self.limit
            hits.append(now)
            self._hits[key] = hits[-(self.limit * 2) :]
            return allowed

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = RateLimiter(limit=10, window_seconds=15 * 60)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return (forwarded.split(",")[0].strip() if forwarded else "") or (request.client.host if request.client else "unknown")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_locked(admin: models.AdminUser) -> bool:
    locked = admin.locked_until
    if locked is None:
        return False
    if locked.tzinfo is None:
        locked = locked.replace(tzinfo=timezone.utc)
    return locked > _now()


def register_failure(admin: models.AdminUser) -> None:
    admin.failed_logins += 1
    if admin.failed_logins >= MAX_FAILED_LOGINS:
        admin.locked_until = _now() + LOCKOUT
        admin.failed_logins = 0
