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
