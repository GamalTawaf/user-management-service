"""Password hashing helpers (bcrypt)."""

from __future__ import annotations

import bcrypt


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(raw, salt)
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    raw = password.encode("utf-8")
    stored = password_hash.encode("utf-8")
    return bcrypt.checkpw(raw, stored)
