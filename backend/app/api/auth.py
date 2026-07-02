"""Authentication endpoint — JWT login.

Supports two user sources:
1. Admin user from settings.admin_username / admin_password (config-based)
2. DB-based users from `users` table (supports admin / viewer roles)
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.middleware.jwt_auth import create_access_token
from app.models.database import get_db
from app.models.user import User

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str = "viewer"


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate with username/password, returns JWT token.

    Checks in order:
    1. Admin config credentials (if matched → admin role)
    2. User table (viewer or admin role)
    """
    if not settings.admin_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="管理员密码未配置，无法登录",
        )

    # Try admin config first (timing-safe comparison)
    admin_match = (
        secrets.compare_digest(body.username, settings.admin_username)
        and secrets.compare_digest(body.password, settings.admin_password)
    )
    if admin_match:
        token = create_access_token(body.username)
        return TokenResponse(
            access_token=token,
            expires_in=settings.jwt_expire_minutes * 60,
            role="admin",
        )

    # Try user table
    user = db.query(User).filter(User.username == body.username).first()
    if user and user.check_password(body.password):
        token = create_access_token(body.username)
        return TokenResponse(
            access_token=token,
            expires_in=settings.jwt_expire_minutes * 60,
            role=user.role,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="用户名或密码错误",
    )
