"""Integration tests for API endpoints via FastAPI TestClient.

Tests: /health, /api/banks, /api/documents, /api/synonyms
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# ═══════════════════════════════════════════════════════
# Health endpoint
# ═══════════════════════════════════════════════════════

class TestHealthEndpoint:
    def test_health_returns_ok(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_has_version(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.get("/health")
        data = resp.json()
        assert data["version"] == "2.0.0"


# ═══════════════════════════════════════════════════════
# Banks endpoints
# ═══════════════════════════════════════════════════════

class TestBanksEndpoints:
    def test_list_banks(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.get("/api/banks")
        assert resp.status_code == 200
        data = resp.json()
        assert "banks" in data
        assert isinstance(data["banks"], list)
        assert len(data["banks"]) > 0

    def test_list_banks_has_all_entry(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.get("/api/banks")
        banks = resp.json()["banks"]
        keys = [b["key"] for b in banks]
        assert "all" in keys

    def test_list_banks_structure(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.get("/api/banks")
        banks = resp.json()["banks"]
        for bank in banks:
            assert "key" in bank
            assert "name" in bank
            assert "count" in bank

    def test_list_banks_has_project_docs(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.get("/api/banks")
        banks = resp.json()["banks"]
        keys = [b["key"] for b in banks]
        assert "project_docs" in keys
        assert "standards" in keys
        assert "general" in keys

    def test_wiki_tree(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.get("/api/banks/wiki")
        assert resp.status_code == 200
        data = resp.json()
        assert "tree" in data
        assert "total" in data

    def test_categories(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.get("/api/banks/categories")
        assert resp.status_code == 200
        data = resp.json()
        assert "categories" in data
        assert isinstance(data["categories"], list)

    def test_list_banks_has_checklist(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.get("/api/banks")
        assert resp.status_code == 200
        keys = [b["key"] for b in resp.json()["banks"]]
        assert "checklist" in keys

    def test_create_bank_does_not_call_hindsight_create(self, client, monkeypatch, tmp_path):
        import app.api.banks as banks_api
        import app.services.retrieval as retrieval

        called = []

        async def fail_on_hindsight_create(endpoint, method="GET", json_data=None, timeout=30):
            called.append((endpoint, method))
            if endpoint == "/v1/default/banks" and method == "POST":
                raise AssertionError("create_bank_api must not POST /v1/default/banks")
            return {"status": "ok"}

        cfg_path = tmp_path / "banks.json"
        monkeypatch.setattr(banks_api, "_hindsight_request", fail_on_hindsight_create)
        monkeypatch.setattr(retrieval.settings, "banks_config_path", cfg_path)
        monkeypatch.setattr(banks_api.settings, "banks_config_path", cfg_path)
        retrieval.reload_bank_config()
        try:
            resp = client.post("/api/banks", data={"key": "test_bank", "label": "测试库"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["bank"] == "test_bank"
            assert data["hindsight_bank"] == "kb_test_bank"
            assert ("/v1/default/banks", "POST") not in called
            assert cfg_path.exists()
        finally:
            retrieval.BANKS.pop("test_bank", None)
            if cfg_path.exists():
                cfg_path.unlink()
            retrieval.reload_bank_config()

    def test_create_existing_bank_returns_409(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.post("/api/banks", data={"key": "general", "label": "综合文件"})
        assert resp.status_code == 409


# ═══════════════════════════════════════════════════════
# Documents endpoints
# ═══════════════════════════════════════════════════════

class TestDocumentsEndpoints:
    def test_list_documents(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.get("/api/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert "documents" in data
        assert isinstance(data["documents"], list)

    def test_list_documents_empty_by_default(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.get("/api/documents")
        data = resp.json()
        # Empty DB → no documents
        assert data["documents"] == []

    def test_list_documents_with_bank_filter(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.get("/api/documents?bank=standards")
        assert resp.status_code == 200
        data = resp.json()
        assert "documents" in data


# ═══════════════════════════════════════════════════════
# Synonyms endpoints
# ═══════════════════════════════════════════════════════

class TestSynonymsEndpoints:
    def test_list_synonyms_empty(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.get("/api/synonyms")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_add_synonym(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.post(
            "/api/synonyms",
            data={"term": "等保", "expansion": "等级保护", "category": "安全"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_add_then_list_synonyms(self, client, mock_hindsight, mock_get_active_banks):
        # Add
        client.post(
            "/api/synonyms",
            data={"term": "密码测评", "expansion": "密码应用评估", "category": "安全"},
        )
        # List
        resp = client.get("/api/synonyms")
        data = resp.json()
        terms = [s["term"] for s in data]
        assert "密码测评" in terms

    def test_update_synonym(self, client, mock_hindsight, mock_get_active_banks):
        # Add first
        client.post(
            "/api/synonyms",
            data={"term": "旧词", "expansion": "旧释义"},
        )
        # Get the id
        resp = client.get("/api/synonyms")
        syn_id = resp.json()[0]["id"]

        # Update
        resp = client.put(
            f"/api/synonyms/{syn_id}",
            data={"term": "新词", "expansion": "新释义"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_delete_synonym(self, client, mock_hindsight, mock_get_active_banks):
        # Add
        client.post(
            "/api/synonyms",
            data={"term": "待删词", "expansion": "待删释义"},
        )
        # Get id
        resp = client.get("/api/synonyms")
        syn_id = resp.json()[0]["id"]

        # Delete
        resp = client.delete(f"/api/synonyms/{syn_id}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_update_nonexistent_synonym(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.put(
            "/api/synonyms/99999",
            data={"term": "不存在", "expansion": "不存在"},
        )
        assert resp.status_code == 404

    def test_delete_nonexistent_synonym(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.delete("/api/synonyms/99999")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════
# Admin endpoints
# ═══════════════════════════════════════════════════════

class TestAdminEndpoints:
    def test_admin_health(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.get("/api/admin/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "db" in data

    def test_admin_banks_config(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.get("/api/admin/banks/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "banks" in data
        assert isinstance(data["banks"], dict)

    def test_admin_banks_config_has_all_key(self, client, mock_hindsight, mock_get_active_banks):
        resp = client.get("/api/admin/banks/config")
        banks = resp.json()["banks"]
        assert "all" in banks
        assert "name" in banks["all"]


# ═══════════════════════════════════════════════════════
# API Router structure
# ═══════════════════════════════════════════════════════

class TestAPIRouter:
    def test_api_prefix_works(self, client, mock_hindsight, mock_get_active_banks):
        """Verify the /api prefix is mounted."""
        resp = client.get("/api/banks")
        assert resp.status_code == 200

    def test_openapi_docs(self, client, mock_hindsight, mock_get_active_banks):
        """FastAPI auto-generates OpenAPI schema."""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "paths" in schema
        # Should have our endpoints
        assert "/api/banks" in schema["paths"] or "/api/banks/" in schema["paths"]


# ═══════════════════════════════════════════════════════
# V1 compatibility aliases
# ═══════════════════════════════════════════════════════

class TestV1CompatibilityAliases:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/api/stats"),
            ("get", "/api/wiki"),
            ("get", "/api/categories"),
            ("get", "/api/rag-eval"),
            ("get", "/api/audit"),
            ("get", "/api/fetch-standard"),
            ("post", "/api/fetch-standard"),
            ("get", "/api/web-search"),
            ("post", "/api/web-search"),
            ("post", "/api/audit/refetch"),
        ],
    )
    def test_aliases_are_protected_without_token(self, client, method, path):
        from app.main import app
        from app.middleware.jwt_auth import get_current_user

        app.dependency_overrides.pop(get_current_user, None)
        response = getattr(client, method)(path, follow_redirects=False)
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "method,path,location",
        [
            ("get", "/api/stats", "/api/admin/stats"),
            ("get", "/api/wiki", "/api/banks/wiki"),
            ("get", "/api/categories", "/api/banks/categories"),
            ("get", "/api/fetch-standard", "/api/documents/fetch-standard"),
            ("post", "/api/fetch-standard", "/api/documents/fetch-standard"),
            ("post", "/api/web-search", "/api/query/web-search"),
            ("post", "/api/audit/refetch", "/api/documents/refetch"),
        ],
    )
    def test_aliases_redirect_to_v2_routes(self, client, method, path, location):
        response = getattr(client, method)(path, follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == location

    def test_get_web_search_alias_explains_post_requirement(self, client):
        response = client.get("/api/web-search", follow_redirects=False)
        assert response.status_code == 405
        assert "requires POST" in response.json()["detail"]
