"""Authentication endpoint — JWT login.

Supports two user sources:
1. Admin user from settings.admin_username / admin_password (config-based)
2. DB-based users from `users` table (supports admin / viewer roles)
"""

import secrets
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.middleware.jwt_auth import create_access_token, get_current_user
from app.models.database import get_db
from app.models.user import User

router = APIRouter()

# ── 登录限速（2026-08-13 安全加固）：每 IP 5 次/分钟 ──
_login_attempts: dict = defaultdict(list)
_MAX_LOGIN_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 60


def _check_rate_limit(ip: str) -> None:
    now = time.time()
    attempts = [t for t in _login_attempts[ip] if now - t < _LOGIN_WINDOW_SECONDS]
    _login_attempts[ip] = attempts
    if len(attempts) >= _MAX_LOGIN_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录尝试过于频繁，请 1 分钟后再试",
        )


def _record_attempt(ip: str) -> None:
    _login_attempts[ip].append(time.time())


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str = "viewer"


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Authenticate with username/password, returns JWT token.

    Checks in order:
    1. Admin config credentials (if matched → admin role)
    2. User table (viewer or admin role)

    2026-08-13: 登录限速（每 IP 5 次/分钟）+ 旧 SHA-256 哈希首次登录自动升级 bcrypt。
    """
    # 获取客户端 IP（FastAPI 无内置，从 request 提取）
    ip = request.client.host if request else "unknown"
    _check_rate_limit(ip)

    if not settings.admin_password:
        _record_attempt(ip)
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
        _login_attempts[ip].clear()  # 2026-08-13 CC 建议：成功登录重置限速计数
        token = create_access_token(body.username)
        return TokenResponse(
            access_token=token,
            expires_in=settings.jwt_expire_minutes * 60,
            role="admin",
        )

    # Try user table
    user = db.query(User).filter(User.username == body.username).first()
    if user and user.check_password(body.password):
        # 旧 SHA-256 哈希 → 自动升级 bcrypt（2026-08-13）
        if user.needs_upgrade():
            user.upgrade_to_bcrypt(body.password)
            db.commit()
        _login_attempts[ip].clear()  # 2026-08-13 CC 建议：成功登录重置限速计数
        token = create_access_token(body.username)
        return TokenResponse(
            access_token=token,
            expires_in=settings.jwt_expire_minutes * 60,
            role=user.role,
        )

    # 登录失败统一计数（admin 路径失败 + User 表失败）
    _record_attempt(ip)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="用户名或密码错误",
    )


# ── GET /api/auth/me — 返回当前登录用户信息（2026-08-13 CC 审查 S7）──
@router.get("/me")
async def get_me(
    request: Request,
    username: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回当前 JWT 用户信息（username + role），供前端校验角色。"""
    role = "admin"
    if username != settings.admin_username:
        user = db.query(User).filter(User.username == username).first()
        if user:
            role = user.role
    return {"username": username, "role": role}
