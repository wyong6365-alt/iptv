"""口令散列（scrypt）与令牌（JWT）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from .db import data_dir

ROLES = {"admin", "data_admin", "estimator", "reviewer", "viewer"}


def secret() -> str:
    env = os.environ.get("GC_SECRET")
    if env:
        return env
    path = data_dir() / "secret.key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_b64, digest_b64 = stored.split("$")
        salt, digest = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
    except ValueError:
        return False
    return hmac.compare_digest(hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1), digest)


def issue_token(user_id: int, hours: int = 12) -> str:
    payload = {"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(hours=hours)}
    return jwt.encode(payload, secret(), algorithm="HS256")


def read_token(token: str) -> int | None:
    try:
        return int(jwt.decode(token, secret(), algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
