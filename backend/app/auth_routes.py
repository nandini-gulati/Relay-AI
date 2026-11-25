"""Authentication routes: email + password registration and login."""

import re
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.auth import (
    create_access_token,
    get_required_user,
    hash_password,
    verify_password,
)
from app.db import (
    create_user,
    get_user_by_email,
)

auth_router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(v: str) -> str:
    cleaned = (v or "").strip().lower()
    if not _EMAIL_RE.match(cleaned):
        raise ValueError("Please enter a valid email address")
    return cleaned


class AuthCredentialsRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return _normalize_email(v)

    @field_validator("password")
    @classmethod
    def check_strong_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must include at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must include at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must include at least one number")
        if not re.search(r"[^A-Za-z0-9]", v):
            raise ValueError("Password must include at least one special character")
        return v


class PasswordLoginRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return _normalize_email(v)


@auth_router.post("/register")
def register(req: AuthCredentialsRequest):
    """Create an account with email and password and sign the user in."""
    try:
        pw_hash = hash_password(req.password)
        user = create_user(req.email, pw_hash)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    token = create_access_token(user["id"], user["email"])
    return {
        "token": token,
        "user": {"id": user["id"], "email": user["email"]},
    }


@auth_router.post("/login")
def login_with_password(req: PasswordLoginRequest):
    """Authenticate with email and password."""
    user = get_user_by_email(req.email)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(user["id"], user["email"])
    return {
        "token": token,
        "user": {"id": user["id"], "email": user["email"]},
    }


@auth_router.get("/me")
def get_current_user(user=Depends(get_required_user)):
    """Return the authenticated user's profile."""
    return {"id": user["uid"], "email": user["email"]}
