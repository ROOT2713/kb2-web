"""User model — stores username, hashed password, and role.

Roles:
  - admin: full access (upload, manage, query)
  - viewer: query-only access

2026-08-13 安全加固：SHA-256 → bcrypt（GPU 抗爆破）。
旧 SHA-256 哈希兼容：check_password 识别旧格式，首次登录自动升级为 bcrypt。
"""

import bcrypt
import hashlib

from sqlalchemy import Column, String, Integer

from app.models.database import Base

_BCRYPT_PREFIX = "$2b$"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)
    salt = Column(String(32), nullable=False)
    role = Column(String(32), nullable=False, default="viewer")  # admin | viewer

    def check_password(self, password: str) -> bool:
        """Verify password. Returns True if password matches.

        2026-08-13: bcrypt 主路径；旧 SHA-256 哈希兼容（命中后返回 True，
        由调用方触发升级）。格式判断：password_hash 以 $2b$ 开头 → bcrypt；
        否则按旧 SHA-256(salt+password) 校验。
        """
        if self.password_hash.startswith(_BCRYPT_PREFIX):
            try:
                return bcrypt.checkpw(password.encode(), self.password_hash.encode())
            except ValueError:
                return False
        # 旧格式 SHA-256 兼容
        return self.password_hash == _hash_password_legacy(password, self.salt)

    def needs_upgrade(self) -> bool:
        """True if stored hash is legacy SHA-256 (should upgrade to bcrypt)."""
        return not self.password_hash.startswith(_BCRYPT_PREFIX)

    def upgrade_to_bcrypt(self, password: str) -> None:
        """Rehash password with bcrypt (for legacy hashes on successful login)."""
        self.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        self.salt = ""  # bcrypt 自带盐，不再需要独立 salt 列

    @classmethod
    def create(cls, username: str, password: str, role: str = "viewer") -> "User":
        """Create a new user with bcrypt password hash."""
        return cls(
            username=username,
            password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
            salt="",
            role=role,
        )


def _hash_password_legacy(password: str, salt: str) -> str:
    """Legacy SHA-256(salt + password) — 仅用于旧哈希校验（2026-08-13 前创建的用户）。"""
    return hashlib.sha256((salt + password).encode()).hexdigest()
