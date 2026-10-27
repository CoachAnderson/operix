"""Senhas (Argon2id), tokens JWT, 2FA (TOTP) e CSRF."""
from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()  # Argon2id com parâmetros recomendados pela biblioteca

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)


# Hash fixo usado para gastar o mesmo tempo quando o e-mail não existe (evita enumeração por tempo).
DUMMY_HASH = _hasher.hash("senha-ficticia-para-tempo-constante")


def create_token(user_id: uuid.UUID, token_version: int, kind: TokenType, extra: dict[str, Any] | None = None) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    ttl = timedelta(minutes=s.access_token_minutes) if kind == "access" else timedelta(days=s.refresh_token_days)
    payload = {
        "sub": str(user_id),
        "ver": token_version,
        "typ": kind,
        "iat": now,
        "exp": now + ttl,
        "jti": secrets.token_urlsafe(12),
        **(extra or {}),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_token(token: str, expected: TokenType) -> dict[str, Any] | None:
    s = get_settings()
    try:
        data = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm], options={"require": ["exp", "sub", "typ"]})
    except jwt.PyJWTError:
        return None
    if data.get("typ") != expected:
        return None
    return data


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=get_settings().app_name)


def verify_totp(secret: str, code: str) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)
