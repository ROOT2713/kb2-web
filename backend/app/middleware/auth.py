"""HTTP Basic Auth middleware.

Replaces: kb-web server.py require_admin()
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings

_security = HTTPBasic()


async def require_admin(credentials: HTTPBasicCredentials = Depends(_security)):
    """Verify admin credentials for protected endpoints."""
    if not settings.admin_password:
        return True  # No password configured = skip auth (dev mode)

    if credentials.username != settings.admin_username or \
       credentials.password != settings.admin_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True
