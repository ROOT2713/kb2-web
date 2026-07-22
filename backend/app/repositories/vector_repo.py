"""Vector store abstraction — interface for Hindsight / future backends.

Ported from: kb-web server.py hindsight_request() L1305-L1340

Hindsight API endpoints:
  - POST /v1/default/banks/{bank}/memories        → upsert chunks
  - POST /v1/default/banks/{bank}/memories/recall → semantic search
  - DELETE /v1/default/banks/{bank}/documents/{doc_id} → delete document
  - GET /v1/default/banks/{bank}/documents        → list documents
"""

import logging
import json
from typing import List, Dict, Optional, Protocol

import asyncpg
import httpx
import numpy as np

from app.config import settings
from app.utils.embeddings import get_embedding

logger = logging.getLogger(__name__)

# Default timeout for Hindsight requests (seconds)
_DEFAULT_TIMEOUT = 30


class VectorStore(Protocol):
    """Abstract interface for vector storage backends."""

    async def upsert(self, doc_id: str, chunks: List[Dict], bank: str) -> int:
        """Insert/update document chunks. Returns chunk count."""
        ...

    async def query(self, embedding: List[float], bank: str, top_k: int = 20, query_text: str = "") -> List[Dict]:
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


class PgVectorStore:
    """PostgreSQL pgvector 向量存储后端。

    Uses asyncpg for direct PostgreSQL access with pgvector extension.
    Compatible with the VectorStore Protocol interface.
    """

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or settings.pgvector_database_url
        self._pool: Optional[asyncpg.Pool] = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            from pgvector.asyncpg import register_vector
            async def _init(conn):
                await register_vector(conn)
                # Re-register JSON/JSONB codec that register_vector corrupts
                try:
                    await conn.set_type_codec(
                        'jsonb', encoder=json.dumps, decoder=json.loads,
                        schema='pg_catalog', format='text'
                    )
                except Exception:
                    pass  # may already be registered
            self._pool = await asyncpg.create_pool(
                self.database_url, min_size=2, max_size=10, init=_init
            )
        return self._pool

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    # ── helpers ────────────────────────────────────────────────
    async def _tags_to_metadata(self, tags: List[str]) -> Dict:
        """Parse hindsight-style tags into a metadata dict."""
        meta: Dict = {}
        for t in tags:
            if ":" in t:
                k, v = t.split(":", 1)
                meta[k] = v
        return meta

    async def _chunks_to_rows(
        self, doc_id: str, chunks: List[Dict], bank: str, embeddings: List[np.ndarray]
    ) -> List[tuple]:
        """Convert chunks + embeddings to rows for bulk INSERT."""
        rows = []
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            text = chunk.get("content") or chunk.get("text", "")
            tags = chunk.get("tags", [])
            meta = await self._tags_to_metadata(tags)
            rows.append((
                doc_id,
                i,
                bank,
                text,
                meta,
                emb.tolist() if emb is not None else None,
            ))
        return rows

    async def get_embedding_batch(self, texts: List[str]) -> List[Optional[np.ndarray]]:
        """Batch get embeddings — one at a time via existing get_embedding()."""
        # TODO: Replace with true batch embedding API call when available
        results = []
        for text in texts:
            emb = await get_embedding(text)
            results.append(emb)
        return results

    # ── upsert ─────────────────────────────────────────────────
    async def upsert(self, doc_id: str, chunks: List[Dict], bank: str) -> int:
        """批量 INSERT vector_chunks (先删后插)."""
        pool = await self._get_pool()

        # Get embeddings for all chunks
        texts = [
            c.get("content") or c.get("text", "")
            for c in chunks
        ]
        embeddings = await self.get_embedding_batch(texts)

        rows = await self._chunks_to_rows(doc_id, chunks, bank, embeddings)

        async with pool.acquire() as conn:
            # Delete existing chunks for this doc+bank
            await conn.execute(
                "DELETE FROM vector_chunks WHERE doc_id = $1 AND bank = $2",
                doc_id, bank,
            )
            # Bulk insert
            await conn.executemany(
                "INSERT INTO vector_chunks (doc_id, chunk_index, bank, content, metadata, embedding) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                rows,
            )

        logger.info("PgVectorStore upsert: doc_id=%s bank=%s chunks=%d", doc_id, bank, len(chunks))
        return len(chunks)

    # ── query (by text) ────────────────────────────────────────
    async def query(
        self,
        query_text: str,
        bank: str,
        top_k: int = 20,
        max_tokens: int = 32768,
    ) -> List[Dict]:
        """语义搜索：embed query_text → cosine similarity search."""
        qvec = await get_embedding(query_text)
        if qvec is None:
            logger.warning("PgVectorStore query: failed to get embedding for query")
            return []

        return await self.query_by_embedding(qvec.tolist(), bank, top_k, query_text)

    # ── query (by embedding) ───────────────────────────────────
    async def query_by_embedding(
        self,
        embedding: List[float],
        bank: str,
        top_k: int = 20,
        query_text: str = "",
    ) -> List[Dict]:
        """混合检索：余弦相似度（HNSW 索引） + tsvector 关键词 + RRF 融合."""
        pool = await self._get_pool()
        re_rank_k = top_k * 3  # 多取 3 倍用于重排
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH top_vec AS (
                    SELECT content, metadata, doc_id, chunk_index, embedding
                    FROM vector_chunks
                    WHERE bank = $1 AND embedding IS NOT NULL
                    ORDER BY embedding <=> $2::vector
                    LIMIT $3
                )
                SELECT content, metadata, doc_id, chunk_index,
                       CASE WHEN $4::text <> '' AND content IS NOT NULL
                            THEN (1 - (embedding <=> $2::vector))
                                 + 1.0 * COALESCE(
                                     ts_rank(
                                       to_tsvector('public.zhcfg', COALESCE(content, '')),
                                       plainto_tsquery('public.zhcfg', $4::text)
                                     ), 0)
                            ELSE 1 - (embedding <=> $2::vector)
                       END AS score
                FROM top_vec
                ORDER BY score DESC
                LIMIT $3
                """,
                bank,
                embedding,
                top_k,
                query_text,
            )

        results = []
        for r in rows:
            tags = []
            raw_meta = r["metadata"]
            if isinstance(raw_meta, str):
                import json
                meta = json.loads(raw_meta) if raw_meta and raw_meta != "{}" else {}
            else:
                meta = dict(raw_meta) if raw_meta else {}
            for k, v in meta.items():
                tags.append(f"{k}:{v}")
            tags.append(f"doc_id:{r['doc_id']}")
            tags.append(f"chunk:{r['chunk_index']}")
            results.append({
                "text": r["content"],
                "tags": tags,
                "score": float(r["score"]),
            })
        return results

    # ── delete ─────────────────────────────────────────────────
    async def delete(self, doc_id: str, bank: str) -> bool:
        """DELETE FROM vector_chunks WHERE doc_id=$1 AND bank=$2."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM vector_chunks WHERE doc_id = $1 AND bank = $2",
                doc_id, bank,
            )
        affected = result.replace("DELETE ", "")
        logger.info("PgVectorStore delete: doc_id=%s bank=%s affected=%s", doc_id, bank, affected)
        return int(affected) > 0 if affected.isdigit() else True

    # ── list_documents ─────────────────────────────────────────
    async def list_documents(self, bank: str, limit: int = 1000) -> List[Dict]:
        """SELECT DISTINCT doc_id, title FROM vector_chunks WHERE bank=$1."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT doc_id,
                       metadata->>'title' AS title,
                       MIN(created_at) AS created_at
                FROM vector_chunks
                WHERE bank = $1
                GROUP BY doc_id, metadata->>'title'
                ORDER BY MIN(created_at) DESC
                LIMIT $2
                """,
                bank,
                limit,
            )
        return [
            {
                "doc_id": r["doc_id"],
                "title": r["title"] or r["doc_id"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

    # ── health ─────────────────────────────────────────────────
    async def health(self) -> bool:
        """SELECT 1 检查数据库连接。"""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            logger.warning("PgVectorStore health check failed: %s", e)
            return False

    # ── get_document_detail ─────────────────────────────────────
    async def get_document_detail(self, doc_id: str, bank: Optional[str] = None) -> List[Dict]:
        """按 doc_id 取所有 chunks，按 chunk_index 排序。
        
        In pgvector mode, bank filter is optional — all chunks share the same table
        and doc_id is already unique. We skip the bank WHERE clause when bank is None
        so that documents whose bank doesn't match the BANKS config (e.g. old bank
        values like kb_xhs, kb_general) are still findable.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if bank:
                rows = await conn.fetch(
                    """
                    SELECT chunk_index, content, metadata, created_at
                    FROM vector_chunks
                    WHERE doc_id = $1 AND bank = $2
                    ORDER BY chunk_index
                    """,
                    doc_id, bank,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT chunk_index, content, metadata, created_at
                    FROM vector_chunks
                    WHERE doc_id = $1
                    ORDER BY chunk_index
                    """,
                    doc_id,
                )
        return [
            {
                "chunk_index": r["chunk_index"],
                "content": r["content"],
                "metadata": dict(r["metadata"]) if r["metadata"] else {},
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

    # ── get_document_chunk_count ─────────────────────────────────
    async def get_document_chunk_count(self, bank: str) -> int:
        """返回指定 bank 的 chunk 总数。"""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM vector_chunks WHERE bank = $1", bank
            ) or 0


# ── Factory ──
_store_instance: Optional[PgVectorStore] = None

def get_vector_store() -> object:
    """根据配置返回 vector store 实例。
    当 vector_backend=pgvector 时返回 PgVectorStore 单例，
    否则返回 HindsightStore（默认行为）。
    """
    global _store_instance
    if settings.vector_backend == "pgvector":
        if _store_instance is None:
            _store_instance = PgVectorStore()
        return _store_instance
    return HindsightStore()
