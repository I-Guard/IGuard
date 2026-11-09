"""Argon2id password hashing and password policy."""

from __future__ import annotations

import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings
from app.core.errors import ValidationFailed

_hasher = PasswordHasher()  # argon2id with library defaults (RFC 9106 low-memory profile)
# Verified against when a user does not exist, to keep login timing uniform.
_DUMMY_HASH = _hasher.hash("iguard-dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def validate_password_policy(password: str) -> None:
    min_len = get_settings().password_min_length
    problems: list[str] = []
    if len(password) < min_len:
        problems.append(f"at least {min_len} characters")
    if len(password) > 256:
        problems.append("at most 256 characters")
    if not re.search(r"[a-z]", password):
        problems.append("a lowercase letter")
    if not re.search(r"[A-Z]", password):
        problems.append("an uppercase letter")
    if not re.search(r"\d", password):
        problems.append("a digit")
    if problems:
        raise ValidationFailed("Password must contain: " + ", ".join(problems))
