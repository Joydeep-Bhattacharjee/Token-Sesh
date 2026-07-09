"""JWT creation, password hashing, auth dependency.

Token lifecycle state (revoked access jtis, consumed refresh jtis) is held
in-memory with a lock; the service runs as a single process.
"""

import hashlib
import hmac
import os
import threading
import time
import uuid

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app import config
from app.database import get_db
from app.errors import AppError
from app.models import User

_PBKDF2_ITERATIONS = 100_000

_lock = threading.Lock()
_revoked_access_jtis: dict[str, float] = {}   # jti -> exp epoch
_consumed_refresh_jtis: dict[str, float] = {}  # jti -> exp epoch

_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        _, iterations, salt_hex, digest_hex = hashed.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------- tokens
def _create_token(user: User, token_type: str, ttl_seconds: int) -> str:
    now = int(time.time())
    claims = {
        "sub": str(user.id),
        "org": user.org_id,
        "role": user.role,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + ttl_seconds,
        "type": token_type,
    }
    return jwt.encode(claims, config.SECRET_KEY, algorithm=config.JWT_ALGORITHM)


def create_access_token(user: User) -> str:
    return _create_token(user, "access", config.ACCESS_TOKEN_TTL_SECONDS)


def create_refresh_token(user: User) -> str:
    return _create_token(user, "refresh", config.REFRESH_TOKEN_TTL_SECONDS)


def decode_token(token: str) -> dict:
    """Decode and validate signature/expiry. Raises 401 on any failure."""
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise AppError(401, "INVALID_TOKEN", "Invalid or expired token")


def _purge_expired(store: dict[str, float]) -> None:
    now = time.time()
    for jti in [j for j, exp in store.items() if exp < now]:
        store.pop(jti, None)


def revoke_access_jti(jti: str, exp: float) -> None:
    with _lock:
        _purge_expired(_revoked_access_jtis)
        _revoked_access_jtis[jti] = exp


def is_access_jti_revoked(jti: str) -> bool:
    with _lock:
        return jti in _revoked_access_jtis


def consume_refresh_jti(jti: str, exp: float) -> bool:
    """Mark a refresh jti as used. Returns False if it was already used."""
    with _lock:
        _purge_expired(_consumed_refresh_jtis)
        if jti in _consumed_refresh_jtis:
            return False
        _consumed_refresh_jtis[jti] = exp
        return True


# ---------------------------------------------------------------- dependency
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise AppError(401, "INVALID_TOKEN", "Missing bearer token")
    claims = decode_token(credentials.credentials)
    if claims.get("type") != "access":
        raise AppError(401, "INVALID_TOKEN", "Not an access token")
    jti = claims.get("jti", "")
    if not jti or is_access_jti_revoked(jti):
        raise AppError(401, "INVALID_TOKEN", "Token has been invalidated")
    try:
        user_id = int(claims.get("sub", ""))
    except (TypeError, ValueError):
        raise AppError(401, "INVALID_TOKEN", "Invalid subject claim")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise AppError(401, "INVALID_TOKEN", "Unknown user")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise AppError(403, "FORBIDDEN", "Admin role required")
    return user
