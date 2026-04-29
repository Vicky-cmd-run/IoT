from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import Header, HTTPException
from pydantic import BaseModel, EmailStr

from config import settings


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: int
    admin_email: str


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_token(email: str, ttl_seconds: int = 60 * 60 * 8) -> LoginResponse:
    expires_at = int(time.time()) + ttl_seconds
    payload = {"sub": email, "exp": expires_at}
    payload_segment = _b64_encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(
        settings.jwt_secret.encode(),
        payload_segment.encode(),
        hashlib.sha256,
    ).hexdigest()
    token = f"{payload_segment}.{signature}"
    return LoginResponse(
        access_token=token,
        expires_at=expires_at,
        admin_email=email,
    )


def verify_token(token: str) -> dict[str, Any]:
    try:
        payload_segment, signature = token.split(".", 1)
    except ValueError as error:
        raise HTTPException(status_code=401, detail="Invalid token format") from error

    expected_signature = hmac.new(
        settings.jwt_secret.encode(),
        payload_segment.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(status_code=401, detail="Invalid token signature")

    payload = json.loads(_b64_decode(payload_segment).decode())
    if int(payload["exp"]) < int(time.time()):
        raise HTTPException(status_code=401, detail="Token expired")
    return payload


def authenticate_admin(email: str, password: str) -> LoginResponse:
    if email != settings.admin_email or password != settings.admin_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not settings.jwt_secret:
        raise HTTPException(status_code=500, detail="JWT secret is not configured")
    return create_token(email)


def require_auth(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    return verify_token(token)
