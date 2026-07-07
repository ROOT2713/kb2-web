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
    """
    _admin_username = settings.admin_username

    def _role_checker(
        username: str = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> bool:
        # Admin config user: always pass
        if username == _admin_username:
            return True

        # DB user: check role
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="用户不存在",
            )

        _role_rank = {"admin": 2, "viewer": 1}
        _min_rank = _role_rank.get(min_role, 0)
        _user_rank = _role_rank.get(user.role, 0)

        if _user_rank < _min_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足，仅管理员可执行此操作",
            )
        return True

    return _role_checker
