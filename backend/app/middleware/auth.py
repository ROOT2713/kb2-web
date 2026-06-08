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
        return True  # No password configured = skip auth (dev mode)

    user_ok = secrets.compare_digest(credentials.username, settings.admin_username)
    pass_ok = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True
