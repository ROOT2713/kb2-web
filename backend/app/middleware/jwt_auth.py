"""JWT authentication dependency for FastAPI.

Provides `get_current_user` dependency that extracts and validates
JWT from Authorization: Bearer <token> header, and `require_role`
dependency for role-based access control.
"""

import time

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import get_db
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)


def get_username_from_token(token: str) -> str | None:
    """Decode JWT token and return username. Returns None if invalid/expired."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload.get("sub", "")
    except Exception:
        return None


def create_access_token(username: str) -> str:
    """Create a JWT access token."""
    payload = {
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + settings.jwt_expire_minutes * 60,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    """Extract and validate JWT from Authorization header.

    Returns the username from the token.
    Raises 401 if token is missing, expired, or invalid.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录，请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        username: str = payload.get("sub", "")
        if not username:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的认证凭证",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return username
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_role(min_role: str = "admin"):
    """Dependency factory: returns a dependency that checks the user's role.

    Usage:
        @router.get("/admin/stats")
        async def stats(user: str = Depends(get_current_user),
                        _=Depends(require_role("admin"))):
            ...

    The admin config user always passes all role checks.
    DB users must have role >= min_role (admin > viewer).

    【FIX-R2-8】min_role 未知角色 fail-closed：原 _role_rank.get(min_role, 0)
    把拼写错误/未知角色解析为 0 → 所有用户（viewer≥0）通过 = fail-open。
    改为定义期校验，配置错误在 import/启动即抛 ValueError 暴露。
    """
    _VALID_ROLES = {"admin", "uploader", "viewer"}
    if min_role not in _VALID_ROLES:
        raise ValueError(
            f"[FIX-R2-8] require_role: 未知角色 {min_role!r}，合法值 {sorted(_VALID_ROLES)}"
        )
    _admin_username = settings.admin_username

    def _role_checker(
        username: str = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> bool:
        # 【FIX-R2-9】admin 配置用户名不再无条件直通：先查 DB，
        # 若存在同名用户则按其 DB 角色走下方校验（防 .env admin_username 与
        # DB 内低权账号重名导致提权）；DB 无同名用户 = 配置账号（.env 管理员
        # 不在 User 表），保持直通能力（先前回归教训：配置账号不可降级 viewer）。
        user = db.query(User).filter(User.username == username).first()
        if user is None and username == _admin_username:
            return True

        if not user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="用户不存在",
            )

        _role_rank = {"admin": 3, "uploader": 2, "viewer": 1}
        _min_rank = _role_rank[min_role]  # R2-8: 定义期已校验，此处必命中
        _user_rank = _role_rank.get(user.role, 0)

        if _user_rank < _min_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足，仅管理员可执行此操作",
            )
        return True

    return _role_checker
