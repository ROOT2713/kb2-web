"""Crystallization Light — LLM-judged contradiction refinement.

Problem
-------
Current embedding-based contradiction (BGE-M3) flags ~20% of concepts as
"contradicting siblings" but most are metadata noise / table fragments /
same-concept-different-chunk. The cornerstone claim pattern:

  BGE-M3 filter → removes 99% false positives (everything > 0.45)
  LLM judgment  → decides the remaining ~200 borderline pairs
  Result        → review_required only fires on TRUE contradictions

Schema: concept_contradictions (new table via raw SQL)
  concept_a_id, concept_b_id, embedding_similarity,
  llm_verdict (str enum), llm_reason (str), judged_at
"""

import logging, json, time
from typing import List, Optional, Dict, Tuple
from datetime import datetime, timezone

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Enums ──
LLM_VERDICT_TRUE_CONTRADICTION = "TRUE_CONTRADICTION"
LLM_VERDICT_TERM_DIFFERENCE = "TERM_DIFFERENCE"  # 同义术语差异
LLM_VERDICT_UNRELATED = "UNRELATED"               # 完全无关（BGE-M3 误报）
LLM_VERDICT_METADATA_NOISE = "METADATA_NOISE"     # 封面/日期/版式
LLM_VERDICT_SAME_SECTION = "SAME_SECTION"         # 同一文档不同章节

# Grey zone: only these embedding scores get LLM judgment
GREY_MIN = 0.20
GREY_MAX = 0.50

# ── Schema ──

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS concept_contradictions (
    concept_a_id VARCHAR(255) NOT NULL,
    concept_b_id VARCHAR(255) NOT NULL,
    embedding_similarity REAL NOT NULL,
    llm_verdict VARCHAR(32),
    llm_reason TEXT,
    judged_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (concept_a_id, concept_b_id)
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_cc_judged ON concept_contradictions(judged_at);
CREATE INDEX IF NOT EXISTS idx_cc_doc_a ON concept_contradictions(concept_a_id);
CREATE INDEX IF NOT EXISTS idx_cc_doc_b ON concept_contradictions(concept_b_id);
"""


def ensure_table(db: Session):
    """Ensure concept_contradictions table exists (idempotent)."""
    db.execute(sa_text(CREATE_TABLE_SQL))
    for sql in INDEX_SQL.split(";"):
        sql = sql.strip()
        if sql:
            try:
                db.execute(sa_text(sql))
            except Exception:
                pass
    db.commit()


# ── LLM Judgment ──

def _call_deepseek_judge(
    pairs: List[Tuple[str, str, float, str, str, str, str]],
) -> List[Dict]:
    """Call DeepSeek to judge a batch of contradiction pairs.

    Each pair: (cid_a, cid_b, score, title_a, title_b, summary_a, summary_b)

    Returns list of verdict dicts.
    """
    import requests, os

    # CC HIGH#1: 统一用 python-dotenv 加载 .env，避免手动 split("=") 截断含 = 的值
    try:
        from dotenv import load_dotenv
        load_dotenv("/home/ubuntu/kb2-web/backend/.env")
    except ImportError:
        pass  # dotenv 未安装时 fallback 到环境变量

    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY") or ""
    if not api_key:
        logger.error("DEEPSEEK_API_KEY / LLM_API_KEY not configured")
        return []

    # Build prompt
    items_text = []
    for i, (cid_a, cid_b, score, title_a, title_b, summary_a, summary_b) in enumerate(pairs):
        items_text.append(f"""Pair {i+1}:
  Concept A: {title_a}
  Summary A: {summary_a}
  Concept B: {title_b}
  Summary B: {summary_b}
  Embedding Similarity: {score:.3f}""")

    prompt = f"""You are a knowledge base quality analyst. Analyze each concept pair below and classify the relationship.

Categories:
- TRUE_CONTRADICTION: The concepts describe the same topic but express conflicting requirements, conflicting standards, or incompatible definitions. This is a genuine contradiction that needs human review.
- TERM_DIFFERENCE: The concepts describe the same thing using different terminology. The content is semantically equivalent. No contradiction.
- UNRELATED: The concepts are about completely different topics. No contradiction (BGE-M3 false positive).
- METADATA_NOISE: One or both concepts are metadata (publication date, publisher info, table of contents, formatting artifacts). Not substantive content.
- SAME_SECTION: These are different sections of the SAME document covering different aspects. Complementary, not contradictory.

Respond with EXACTLY one line per pair in this exact format:

Pair 1: TRUE_CONTRADICTION | (brief 1-sentence reason)
Pair 2: TERM_DIFFERENCE | (brief 1-sentence reason)

Pairs to analyze:
{chr(10).join(items_text)}"""

    try:
        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system",
                     "content": "You are a precise knowledge base quality analyst. Respond only in the specified format."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 1024,
            },
            timeout=60,
        )

        if resp.status_code != 200:
            logger.error("DeepSeek API error %d: %s", resp.status_code, resp.text[:200])
            return []

        result = resp.json()
        content = result["choices"][0]["message"]["content"]

        # Parse results
        verdicts = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            for v in [LLM_VERDICT_TRUE_CONTRADICTION, LLM_VERDICT_TERM_DIFFERENCE,
                       LLM_VERDICT_UNRELATED, LLM_VERDICT_METADATA_NOISE,
                       LLM_VERDICT_SAME_SECTION]:
                if v in line and "Pair" in line:
                    # Extract reason
                    reason = line.split("|", 1)[1].strip() if "|" in line else ""
                    verdicts.append({"verdict": v, "reason": reason})
                    break
            else:
                # Try without "Pair"
                for v in [LLM_VERDICT_TRUE_CONTRADICTION, LLM_VERDICT_TERM_DIFFERENCE,
                           LLM_VERDICT_UNRELATED, LLM_VERDICT_METADATA_NOISE,
                           LLM_VERDICT_SAME_SECTION]:
                    if v in line:
                        reason = line.split("|", 1)[1].strip() if "|" in line else ""
                        verdicts.append({"verdict": v, "reason": reason})
                        break

        return verdicts

    except Exception as e:
        logger.error("DeepSeek judge call failed: %s", e)
        return []


def collect_grey_zone_candidates(db: Session, limit: int = 500) -> List[Dict]:
    """Collect concepts whose contradiction score lands in the grey zone.

    For each grey concept, identify the strongest contradicting sibling.
    Returns list of (concept, strongest_sibling, score) ready for LLM judgment.
    """
    import asyncio
    from app.models.concept import Concept
    from app.services.contradiction import _get_concept_embedding, _cosine_similarity, MAX_SIBLINGS, SIBLING_SAMPLE_SIZE
    from app.utils.embeddings import get_embedding
    import numpy as np

    concepts = db.query(Concept).filter(
        Concept.status == "active",
        Concept.summary.isnot(None),
        Concept.summary != "",
    ).limit(limit).all()

    candidates = []
    # Cache embeddings to avoid duplicate API calls
    emb_cache = {}

    def emb(text: str):
        if text in emb_cache:
            return emb_cache[text]
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            v = loop.run_until_complete(get_embedding(text[:2000]))
            loop.close()
            emb_cache[text] = v
            return v
        except Exception:
            return None

    for i, concept in enumerate(concepts):
        if not concept or not concept.concept_id:
            continue
        cid = str(concept.concept_id)
        parts = cid.split("/")
        if len(parts) < 2:
            continue
        domain_prefix = parts[0] + "/"

        c_text = str(concept.content or concept.title or "")
        if len(c_text) < 20:
            continue
        target_vec = emb(c_text)
        if target_vec is None:
            continue

        # Find a few siblings
        siblings = db.query(Concept).filter(
            Concept.concept_id.like(f"{domain_prefix}%"),
            Concept.doc_id != concept.doc_id,
            Concept.status == "active",
            Concept.summary.isnot(None),
        ).limit(MAX_SIBLINGS).all()

        if not siblings:
            continue

        # Sample SIBLING_SAMPLE_SIZE (5) for speed
        sample = siblings[:SIBLING_SAMPLE_SIZE]
        min_sim = 1.0
        best_sib = None

        for sib in sample:
            s_text = str(sib.content or sib.title or "")
            if len(s_text) < 20:
                continue
            sib_vec = emb(s_text)
            if sib_vec is None:
                continue
            sim = _cosine_similarity(target_vec, sib_vec)
            if sim < min_sim:
                min_sim = sim
                best_sib = sib

        if best_sib is None:
            continue

        # Grey zone check
        if GREY_MIN <= min_sim <= GREY_MAX:
            # Deduplicate by pair (a < b)
            a_id, b_id = str(concept.concept_id), str(best_sib.concept_id)
            if a_id > b_id:
                a_id, b_id = b_id, a_id

            # Skip if already judged
            existing = db.execute(
                sa_text("SELECT 1 FROM concept_contradictions WHERE concept_a_id=:a AND concept_b_id=:b AND llm_verdict IS NOT NULL"),
                {"a": a_id, "b": b_id},
            ).fetchone()
            if existing:
                continue

            candidates.append({
                "a_id": a_id,
                "b_id": b_id,
                "concept_a": concept,
                "concept_b": best_sib,
                "score": min_sim,
            })

        if (i + 1) % 100 == 0:
            logger.info("Grey zone scan: %d/%d concepts, %d candidates", i + 1, len(concepts), len(candidates))

    return candidates


def run_crystallization(db: Session, limit: int = 500, batch_size: int = 8) -> Dict:
    """End-to-end Crystallization Light:
    1. Collect grey-zone pairs
    2. Batch LLM judgment
    3. Store results in concept_contradictions
    4. Return summary stats
    """
    ensure_table(db)

    logger.info("Starting Crystallization Light, scanning up to %d concepts...", limit)
    candidates = collect_grey_zone_candidates(db, limit=limit)
    logger.info("Found %d grey-zone candidates for LLM judgment", len(candidates))

    if not candidates:
        return {"candidates": 0, "judged": 0, "verdicts": {}}

    judged = 0
    verdict_counts: Dict[str, int] = {}

    for batch_start in range(0, len(candidates), batch_size):
        batch = candidates[batch_start:batch_start + batch_size]
        input_items = []
        for c in batch:
            ca = c["concept_a"]
            cb = c["concept_b"]
            input_items.append((
                c["a_id"], c["b_id"], c["score"],
                str(ca.title or "")[:200], str(cb.title or "")[:200],
                str(ca.summary or "")[:400], str(cb.summary or "")[:400],
            ))

        verdicts = _call_deepseek_judge(input_items)
        if not verdicts:
            logger.warning("Batch %d returned no verdicts", batch_start // batch_size + 1)
            continue

        now = datetime.now(timezone.utc)
        for i, v in enumerate(verdicts):
            if i >= len(batch):
                break
            pair = batch[i]
            verdict = v.get("verdict")
            try:
                db.execute(
                    sa_text("""INSERT OR REPLACE INTO concept_contradictions
                        (concept_a_id, concept_b_id, embedding_similarity,
                         llm_verdict, llm_reason, judged_at)
                        VALUES (:a, :b, :s, :v, :r, :now)"""),
                    {"a": pair["a_id"], "b": pair["b_id"], "s": pair["score"],
                     "v": verdict, "r": v.get("reason", "")[:500], "now": now},
                )
                db.commit()
                judged += 1
                verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
            except Exception as e:
                logger.warning("Insert failed: %s", e)
                db.rollback()

        logger.info("Batch %d/%d done: judged=%d, dist=%s",
                    batch_start // batch_size + 1,
                    (len(candidates) + batch_size - 1) // batch_size,
                    judged, dict(verdict_counts))

    return {
        "candidates": len(candidates),
        "judged": judged,
        "verdicts": verdict_counts,
    }


def has_true_contradiction(db: Session, doc_id: str) -> bool:
    """Check if a document has any LLM-confirmed true contradiction.

    Used by confidence.py to set review_required.
    """
    row = db.execute(
        sa_text("""SELECT 1 FROM concept_contradictions cc
            WHERE cc.llm_verdict = 'TRUE_CONTRADICTION'
            AND (
                cc.concept_a_id IN (SELECT concept_id FROM concepts WHERE doc_id = :did)
                OR
                cc.concept_b_id IN (SELECT concept_id FROM concepts WHERE doc_id = :did)
            )
            LIMIT 1"""),
        {"did": doc_id},
    ).fetchone()
    return row is not None


def verbose_scores(c: "Concept", score: float):
    """Log first/last digit of concept score for progress tracking."""
    cid = c.concept_id or ""
    logger.debug(
        "Concept score check %s=%.3f | %s",
        cid[:8] if len(cid) > 8 else cid,
        score,
        (c.title or "")[:40],
    )