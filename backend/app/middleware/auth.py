"""HTTP Basic Auth middleware.

Replaces: kb-web server.py require_admin()
"""

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings

_security = HTTPBasic()


async def require_admin(credentials: HTTPBasicCredentials = Depends(_security)):
    """Verify admin credentials for protected endpoints.

    Uses secrets.compare_digest to prevent timing side-channel attacks.
    """
    if not settings.admin_password:
        # 【审计盲区修复】原为 fail-open（return True），未配置密码时任何人均可访问。
        # 改为 fail-closed：管理端点必须显式配置密码，防止误用/漏配导致越权。
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="管理员密码未配置，管理端点不可用",
            headers={"WWW-Authenticate": "Basic"},
        )

    user_ok = secrets.compare_digest(credentials.username, settings.admin_username)
    pass_ok = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True
