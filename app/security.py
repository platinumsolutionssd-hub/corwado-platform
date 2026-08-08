"""
Auth primitives: password hashing (bcrypt) and JWT issue/decode.

bcrypt is used directly rather than via passlib to avoid the well-known
passlib(1.7.x)+bcrypt(>=4) __about__ incompatibility.
"""
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt  # PyJWT
from fastapi import HTTPException

# No default on purpose: an unset signing secret must fail closed at import,
# not silently sign tokens with a blank key.
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALG = "HS256"
JWT_TTL_HOURS = 12

# bcrypt truncates silently past 72 bytes; guard so a long password can't be
# accepted-then-truncated.
_BCRYPT_MAX_BYTES = 72


def hash_password(raw: str) -> str:
    pw = raw.encode("utf-8")
    if len(pw) > _BCRYPT_MAX_BYTES:
        raise HTTPException(status_code=422, detail="password too long")
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def issue_token(subject: str, typ: str) -> str:
    # typ is 'staff' or 'platform_admin'. A token minted for one role can
    # never satisfy the other dependency's typ check (see app/deps.py).
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": subject, "typ": typ, "iat": now, "exp": now + timedelta(hours=JWT_TTL_HOURS)},
        JWT_SECRET, algorithm=JWT_ALG,
    )


def parse_bearer(header):
    if not header or not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return header[7:]


def decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid or expired token")
