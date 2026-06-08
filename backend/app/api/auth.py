"""Authentication endpoint — JWT login."""

import secrets

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.middleware.jwt_auth import create_access_token

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    """Authenticate with username/password, returns JWT token."""
    if not settings.admin_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="管理员密码未配置，无法登录",
        )

    # Use secrets.compare_digest to prevent timing attacks
    user_ok = secrets.compare_digest(body.username, settings.admin_username)
    pass_ok = secrets.compare_digest(body.password, settings.admin_password)

    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    token = create_access_token(body.username)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
    )
