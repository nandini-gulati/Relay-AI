"""Authentication helpers: password hashing and signed session tokens."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException, status

_FALLBACK_SECRET = secrets.token_hex(32)
TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days


def _get_auth_secret() -> bytes:
    secret = os.getenv("AUTH_SECRET", "").strip()
    if not secret:
        keys = os.getenv("LLM_API_KEYS", "").strip()
        if keys:
            secret = hashlib.sha256(f"relay-auth:{keys}".encode()).hexdigest()
        else:
            secret = _FALLBACK_SECRET
    return secret.encode("utf-8")


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 and a random 16-byte salt."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a stored salt$hash string."""
    try:
        salt, expected_hex = stored_hash.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
        return hmac.compare_digest(dk.hex(), expected_hex)
    except Exception:
        return False


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def create_access_token(user_id: int, email: str) -> str:
    """Create an HMAC-SHA256 signed session token."""
    payload = {
        "uid": user_id,
        "email": email,
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_get_auth_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url_encode(sig)}"


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify and decode a signed session token. Returns None if invalid or expired."""
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        expected_sig = hmac.new(
            _get_auth_secret(), payload_b64.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected_sig, _b64url_decode(sig_b64)):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def get_optional_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Optional[Dict[str, Any]]:
    """FastAPI dependency returning {uid, email} if a valid Bearer token is present."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    return decode_access_token(token)


def get_required_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, Any]:
    """FastAPI dependency requiring a valid Bearer token."""
    user = get_optional_user(authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user
