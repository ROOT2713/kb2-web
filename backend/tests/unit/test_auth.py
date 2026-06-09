"""Tests for JWT authentication endpoints."""

import os
import pytest


@pytest.fixture(autouse=True)
def _set_admin_password(monkeypatch):
    """Ensure admin password is set for auth tests."""
    monkeypatch.setattr("app.config.settings.admin_password", "testpass123")
    monkeypatch.setattr("app.config.settings.admin_username", "admin")
    monkeypatch.setattr("app.config.settings.jwt_secret", "test_secret_key_for_jwt_32_bytes_minimum")
    monkeypatch.setattr("app.config.settings.jwt_expire_minutes", 60)


class TestLoginEndpoint:
    """POST /api/auth/login"""

    def test_login_success(self, client):
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "testpass123"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    def test_login_wrong_password(self, client):
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401

    def test_login_wrong_username(self, client):
        resp = client.post("/api/auth/login", json={"username": "hacker", "password": "testpass123"})
        assert resp.status_code == 401

    def test_login_empty_body(self, client):
        resp = client.post("/api/auth/login", json={})
        assert resp.status_code == 422  # validation error

    def test_login_no_password_configured(self, client, monkeypatch):
        monkeypatch.setattr("app.config.settings.admin_password", "")
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "testpass123"})
        assert resp.status_code == 503


class TestJWTProtection:
    """Verify /api/* endpoints require JWT."""

    def test_no_token_returns_401(self, client, monkeypatch):
        """Without JWT, /api/documents should return 401."""
        # Remove the JWT override to test real behavior
        from app.main import app
        from app.middleware.jwt_auth import get_current_user
        if get_current_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_user]

        resp = client.get("/api/documents?bank=all")
        assert resp.status_code == 401
        data = resp.json()
        assert "未登录" in data["detail"] or "登录已过期" in data["detail"] or "认证凭证" in data["detail"]

    def test_invalid_token_returns_401(self, client, monkeypatch):
        """With a garbage JWT, /api/documents should return 401."""
        from app.main import app
        from app.middleware.jwt_auth import get_current_user
        if get_current_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_user]

        resp = client.get("/api/documents?bank=all", headers={"Authorization": "Bearer garbage_token"})
        assert resp.status_code == 401

    def test_valid_token_passes(self, client, monkeypatch):
        """With a valid JWT, /api/documents should return 200."""
        from app.main import app
        from app.middleware.jwt_auth import get_current_user
        if get_current_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_user]

        # Get a real token
        from app.middleware.jwt_auth import create_access_token
        token = create_access_token("admin")

        resp = client.get("/api/documents?bank=all", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_health_no_auth_needed(self, client):
        """/health should not require JWT."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
