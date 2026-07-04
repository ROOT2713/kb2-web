"""Multidimensional reranking — reorders search results using multiple signals.

Dimensions:
- keyword_score: BM25 / keyword-match relevance (from existing keyword_rerank score)
- dense_score: semantic similarity score (from vector recall)
- confidence: document-level profile_confidence or tags-based confidence
- freshness: recency boost (newer documents score higher)
- source_count: how many documents share the same concept (popularity signal)

Weights are configurable via the `weights` dict.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import text as sa_text

from app.models.database import SessionLocal

logger = logging.getLogger(__name__)

# Default dimension weights
DEFAULT_WEIGHTS = {
    "keyword": 0.45,
    "dense": 0.45,
    "confidence": 0.05,
    "freshness": 0.03,
    "source_count": 0.02,
}

# Freshness half-life in days
_FRESHNESS_HALF_LIFE_DAYS = 365


def multidim_rerank(
    results: List[dict],
    query: str,
    bank: str = "all",
    weights: Optional[Dict[str, float]] = None,
    top_k: int = 20,
) -> List[dict]:
    """Multidimensional reranking of search results.

    Args:
        results: List of result dicts from RRF merge
        query: Original query string
        bank: Bank scope
        weights: Dimension weights (defaults to DEFAULT_WEIGHTS)
        top_k: Max results to return

    Returns:
        Re-ranked results list (same format as input)
    """
    if not results:
        return results

    w = {**DEFAULT_WEIGHTS, **(weights or {})}

    # Normalize weights to sum to 1.0
    total_w = sum(w.values())
    if total_w > 0:
        w = {k: v / total_w for k, v in w.items()}

    # Pre-fetch document metadata from DB for confidence, freshness, source_count
    doc_meta = _fetch_doc_metadata(results)

    scored = []
    for rank, item in enumerate(results):
        doc_id = _extract_doc_id(item)
        meta = doc_meta.get(doc_id, {})
        tags = item.get("tags", [])

        # 1. keyword_score — from keyword_rerak or calculate simple coverage
        keyword_score = _calc_keyword_score(item, query)

        # 2. dense_score — from recall score or tags
        dense_score = _calc_dense_score(item)

        # 3. confidence — from document.profile_confidence or tags
        confidence = _calc_confidence(item, meta, tags)

        # 4. freshness — time-decay score (0-1)
        freshness = _calc_freshness(meta, tags)

        # 5. source_count — concept popularity (0-1 normalized)
        source_count = _calc_source_count(meta)

        composite = (
            w.get("keyword", 0) * keyword_score
            + w.get("dense", 0) * dense_score
            + w.get("confidence", 0) * confidence
            + w.get("freshness", 0) * freshness
            + w.get("source_count", 0) * source_count
        )

        scored.append((composite, rank, item))

    # Sort by composite score descending, then by original rank as tiebreaker
    scored.sort(key=lambda x: (-x[0], x[1]))

    return [item for _, _, item in scored[:top_k]]


def _extract_doc_id(item: dict) -> str:
    """Extract doc_id from a result item."""
    if item.get("doc_id"):
        return str(item["doc_id"])
    for tag in item.get("tags", []):
        if tag.startswith("doc_id:"):
            return tag[7:]
    return ""


def _calc_keyword_score(item: dict, query: str) -> float:
    """Calculate keyword coverage score (0-1)."""
    text = item.get("text", "") or ""
    text_lower = text.lower()
    query_lower = query.lower()
    query_tokens = [t.strip() for t in query_lower.split() if len(t.strip()) > 1]

    if not query_tokens or not text:
        return 0.0

    hits = sum(1 for t in query_tokens if t in text_lower)
    return min(hits / len(query_tokens), 1.0)


def _calc_dense_score(item: dict) -> float:
    """Extract dense/semantic score from result (0-1)."""
    # Try tags first (Hindsight stores score in tags like "score:0.85")
    for tag in item.get("tags", []):
        if tag.startswith("score:"):
            try:
                return min(max(float(tag[6:]), 0.0), 1.0)
            except (ValueError, TypeError):
                pass

    # Try score field
    score = item.get("score")
    if score is not None:
        try:
            return min(max(float(score), 0.0), 1.0)
        except (ValueError, TypeError):
            pass

    # Fallback: normalized rank-based score
    return 0.5


def _calc_confidence(item: dict, meta: dict, tags: list) -> float:
    """Calculate confidence score (0-1)."""
    # 1. Document-level profile_confidence from DB
    doc_conf = meta.get("profile_confidence")
    if doc_conf is not None:
        try:
            return min(max(float(doc_conf), 0.0), 1.0)
        except (ValueError, TypeError):
            pass

    # 2. Confidence from tags (Hindsight tags format: "confidence:0.85")
    for tag in tags:
        if tag.startswith("confidence:"):
            try:
                return min(max(float(tag[11:]), 0.0), 1.0)
            except (ValueError, TypeError):
                pass

    # 3. Fallback: neutral
    return 0.5


def _calc_freshness(meta: dict, tags: list) -> float:
    """Calculate freshness score (0-1, newer = higher)."""
    now = datetime.now(timezone.utc)

    # Try updated_at from DB meta
    updated = meta.get("updated_at")
    if updated:
        if isinstance(updated, str):
            try:
                updated = datetime.fromisoformat(updated)
            except (ValueError, TypeError):
                updated = None
        if updated and hasattr(updated, "tzinfo"):
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            days_old = (now - updated).days
            if days_old < 0:
                days_old = 0
            # Exponential decay: score = 2^(-days/half_life)
            return 2.0 ** (-days_old / _FRESHNESS_HALF_LIFE_DAYS)

    # Try created_at
    created = meta.get("created_at")
    if created:
        if isinstance(created, str):
            try:
                created = datetime.fromisoformat(created)
            except (ValueError, TypeError):
                created = None
        if created and hasattr(created, "tzinfo"):
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            days_old = (now - created).days
            if days_old < 0:
                days_old = 0
            return 2.0 ** (-days_old / _FRESHNESS_HALF_LIFE_DAYS)

    return 0.5  # neutral


def _calc_source_count(meta: dict) -> float:
    """Calculate source/popularity score (0-1)."""
    count = meta.get("source_count")
    if count is not None:
        try:
            c = int(count)
            # Soft normalization: score = 1 - 1/(c+1)
            return 1.0 - 1.0 / (c + 1)
        except (ValueError, TypeError):
            pass
    return 0.0


def _fetch_doc_metadata(results: List[dict]) -> Dict[str, dict]:
    """Batch-fetch document metadata from DB for all results.

    Returns {doc_id: {profile_confidence, updated_at, created_at, source_count}}
    """
    doc_ids = set()
    for item in results:
        did = _extract_doc_id(item)
        if did:
            doc_ids.add(did)

    if not doc_ids:
        return {}

    meta = {}
    try:
        db = SessionLocal()
        try:
            # Batch query: fetch document metadata + concept-level source count
            placeholders = ",".join(f":d{i}" for i in range(len(doc_ids)))
            params = {f"d{i}": did for i, did in enumerate(doc_ids)}
            rows = db.execute(
                sa_text(f"""
                    SELECT
                        d.doc_id,
                        d.profile_confidence,
                        d.updated_at,
                        d.created_at,
                        d.concept_id,
                        (SELECT COUNT(*) FROM documents d2
                         WHERE d2.concept_id = d.concept_id
                           AND d2.status = 'active') AS source_count
                    FROM documents d
                    WHERE d.doc_id IN ({placeholders})
                """),
                params,
            ).fetchall()

            for r in rows:
                meta[r[0]] = {
                    "profile_confidence": r[1],
                    "updated_at": r[2],
                    "created_at": r[3],
                    "concept_id": r[4],
                    "source_count": r[5] if r[5] else 0,
                }
        finally:
            db.close()
    except Exception as e:
        logger.warning("multidim_rerank: failed to fetch doc metadata: %s", e)

    return meta
