"""User model — stores username, hashed password, and role.

Roles:
  - admin: full access (upload, manage, query)
  - viewer: query-only access
"""

import hashlib
import os

from sqlalchemy import Column, String, Integer, Enum as SAEnum

from app.models.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)
    salt = Column(String(32), nullable=False)
    role = Column(String(32), nullable=False, default="viewer")  # admin | viewer

    def check_password(self, password: str) -> bool:
        """Verify password against stored hash."""
        return self.password_hash == _hash_password(password, self.salt)

    @classmethod
    def create(cls, username: str, password: str, role: str = "viewer") -> "User":
        """Create a new user with salted password hash."""
        salt = os.urandom(16).hex()
        return cls(
            username=username,
            password_hash=_hash_password(password, salt),
            salt=salt,
            role=role,
        )


def _hash_password(password: str, salt: str) -> str:
    """SHA-256(salt + password) as hex string."""
    return hashlib.sha256((salt + password).encode()).hexdigest()
