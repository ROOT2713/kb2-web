"""Vector store abstraction — interface for Hindsight / future backends.

Ported from: kb-web server.py hindsight_request() L1305-L1340

Hindsight API endpoints:
  - POST /v1/default/banks/{bank}/memories        → upsert chunks
  - POST /v1/default/banks/{bank}/memories/recall → semantic search
  - DELETE /v1/default/banks/{bank}/documents/{doc_id} → delete document
  - GET /v1/default/banks/{bank}/documents        → list documents
"""

import logging
from typing import List, Dict, Optional, Protocol

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Default timeout for Hindsight requests (seconds)
_DEFAULT_TIMEOUT = 30


class VectorStore(Protocol):
    """Abstract interface for vector storage backends."""

    async def upsert(self, doc_id: str, chunks: List[Dict], bank: str) -> int:
        """Insert/update document chunks. Returns chunk count."""
        ...

    async def query(self, embedding: List[float], bank: str, top_k: int = 20) -> List[Dict]:
        """Semantic vector search."""
        ...

    async def delete(self, doc_id: str, bank: str) -> bool:
        """Delete all chunks of a document."""
        ...

    async def list_documents(self, bank: str) -> List[Dict]:
        """List all documents in a bank."""
        ...


class HindsightError(Exception):
    """Raised when the Hindsight API returns an error."""


class HindsightStore:
    """Hindsight HTTP API adapter.

    Uses httpx.AsyncClient for async HTTP calls to the Hindsight vector store.
    Base URL comes from settings.hindsight_url.
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or settings.hindsight_url).rstrip("/")

    # ── internal HTTP helper ────────────────────────────────────
    async def _request(
        self,
        endpoint: str,
        method: str = "GET",
        json_data: Optional[dict] = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> dict:
        """Make an async HTTP request to the Hindsight API.

        Matches v1 hindsight_request() error-handling patterns.
        """
        url = f"{self.base_url}{endpoint}"
        logger.debug("Hindsight %s %s", method, url)

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                if method == "POST":
                    resp = await client.post(url, json=json_data)
                elif method == "DELETE":
                    resp = await client.delete(url)
                else:
                    resp = await client.get(url)
            except httpx.TimeoutException:
                raise HindsightError(
                    f"Hindsight {method} {endpoint}: 请求超时（{timeout}s）"
                )
            except httpx.ConnectError:
                raise HindsightError(
                    f"Hindsight {method} {endpoint}: 无法连接（服务未启动？）"
                )
            except Exception as e:
                raise HindsightError(
                    f"Hindsight {method} {endpoint}: 网络异常: {e}"
                )

            # Handle non-2xx responses
            if resp.status_code >= 400:
                detail = ""
                try:
                    detail = resp.json().get("detail", "")
                except Exception:
                    pass
                detail = detail or resp.text[:200] or f"HTTP {resp.status_code}"
                raise HindsightError(
                    f"Hindsight {method} {endpoint} returned {resp.status_code}: {detail}"
                )

            # Parse JSON response
            try:
                return resp.json()
            except Exception:
                raise HindsightError(
                    f"Hindsight {method} {endpoint}: 响应不是有效 JSON: {resp.text[:200]}"
                )

    # ── upsert ──────────────────────────────────────────────────
    async def upsert(self, doc_id: str, chunks: List[Dict], bank: str) -> int:
        """Upload document chunks to Hindsight.

        chunks: list of dicts with keys like {"content": str, "tags": [...], "type": "world"}.

        Returns number of chunks successfully stored.

        Matches v1: POST /v1/default/banks/{bank}/memories
        """
        if not chunks:
            logger.warning("upsert called with empty chunks for doc_id=%s", doc_id)
            return 0

        endpoint = f"/v1/default/banks/{bank}/memories"
        chunk_count = len(chunks)
        # 大文档逐批写入超时：20chunk默认120s，每多10chunk加60s，上限600s
        timeout = min(120 + max(0, chunk_count - 20) * 3, 600)

        result = await self._request(
            endpoint,
            method="POST",
            json_data={"items": chunks},
            timeout=timeout,
        )
        count = result.get("items_count", 0)
        logger.info("Hindsight upsert: doc_id=%s bank=%s chunks=%d/%d",
                     doc_id, bank, count, len(chunks))
        return count

    # ── query ───────────────────────────────────────────────────
    async def query(
        self,
        query_text: str,
        bank: str,
        top_k: int = 20,
        max_tokens: int = 32768,
    ) -> List[Dict]:
        """Semantic vector search via Hindsight recall endpoint.

        Matches v1: POST /v1/default/banks/{bank}/memories/recall
        """
        endpoint = f"/v1/default/banks/{bank}/memories/recall"
        result = await self._request(
            endpoint,
            method="POST",
            json_data={
                "query": query_text,
                "max_tokens": max_tokens,
                "limit": top_k,
            },
            timeout=15,
        )
        return result.get("results", [])

    async def query_by_embedding(
        self,
        embedding: List[float],
        bank: str,
        top_k: int = 20,
    ) -> List[Dict]:
        """Semantic search by embedding vector.

        Note: Hindsight REST API uses text query, not raw embeddings.
        This method is provided for interface compatibility with Protocol.
        """
        logger.warning(
            "query_by_embedding: Hindsight REST API does not support raw embeddings. "
            "Falling back to empty results."
        )
        return []

    # ── delete ──────────────────────────────────────────────────
    async def delete(self, doc_id: str, bank: str) -> bool:
        """Delete document from Hindsight by doc_id.

        Matches v1: DELETE /v1/default/banks/{bank}/documents/{doc_id}
        """
        endpoint = f"/v1/default/banks/{bank}/documents/{doc_id}"
        try:
            await self._request(endpoint, method="DELETE", timeout=30)
            logger.info("Hindsight delete: doc_id=%s bank=%s", doc_id, bank)
            return True
        except HindsightError as e:
            logger.warning("Hindsight delete failed (continuing): %s", e)
            return False

    # ── list_documents ──────────────────────────────────────────
    async def list_documents(self, bank: str, limit: int = 1000) -> List[Dict]:
        """List all documents in a Hindsight bank.

        Matches v1: GET /v1/default/banks/{bank}/documents?limit=1000
        """
        endpoint = f"/v1/default/banks/{bank}/documents?limit={limit}"
        result = await self._request(endpoint, method="GET", timeout=15)
        return result.get("items", []) or result.get("documents", [])

    # ── health ──────────────────────────────────────────────────
    async def health(self) -> bool:
        """Check if Hindsight service is reachable."""
        try:
            result = await self._request("/health", method="GET", timeout=5)
            return result.get("status") == "ok"
        except HindsightError:
            return False
