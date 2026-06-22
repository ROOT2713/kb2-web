"""KG Client — 知识图谱规则抽取 + 实体消歧。

Phase A: 规则抽取 supersedes + cites 边。
Phase B: LLM 辅助抽取 depends_on 等 V2 边。
Phase C: 废弃旧类型，统一到 V2 词表。
"""

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.models.database import SessionLocal
from app.models.document import Document
from app.models.concept import KGTriple
from app.services.version_chain import _extract_standard_number

logger = logging.getLogger(__name__)

# ── V1 谓词词表 ──
V1_PREDICATES = frozenset({
    "references", "supersedes", "defines",
    "applies_to", "cites", "derives_from",
})


def kg_index_document(doc_id: str, title: str, text: str, bank: str) -> Dict:
    """抽取 KG 三元组并写入 kg_triples 表。

    规则抽取（supersedes + cites）+ LLM 辅助（depends_on，阶段B）。

    Args:
        doc_id: 文档 ID
        title: 文档标题
        text: 文档全文
        bank: 所属库

    Returns:
        {"triples_inserted": N}
    """
    triples: List[KGTriple] = []

    # ── 1. supersedes：复用 version_chain 已有的检测逻辑 ──
    from app.services.version_chain import detect_existing_doc
    db = SessionLocal()
    try:
        existing = detect_existing_doc(db, title, bank, doc_type="generic", content_hash="")
        if existing and existing.doc_id != doc_id:
            triples.append(KGTriple(
                subject_type="document",
                subject_id=existing.doc_id,
                predicate="supersedes",
                object_type="document",
                object_id=doc_id,
                doc_id=doc_id,
                confidence=1.0,
                evidence=f"Version chain: {existing.title} superseded by {title}",
                created_at=datetime.now(timezone.utc),
            ))
            logger.info("KG: %s supersedes %s", existing.doc_id[:8], doc_id[:8])

        # ── 2. cites：正则匹配标准号 ──
        cited_docs = _extract_citations(text, db)
        for cited_doc in cited_docs:
            if cited_doc.doc_id != doc_id:
                # avoid duplicate
                exists = db.query(KGTriple).filter(
                    KGTriple.subject_id == doc_id,
                    KGTriple.predicate == "cites",
                    KGTriple.object_id == cited_doc.doc_id,
                ).first()
                if exists:
                    continue
                triples.append(KGTriple(
                    subject_type="document",
                    subject_id=doc_id,
                    predicate="cites",
                    object_type="document",
                    object_id=cited_doc.doc_id,
                    doc_id=doc_id,
                    confidence=0.85,
                    evidence="Standard reference found in text",
                    created_at=datetime.now(timezone.utc),
                ))

        # ── 3. write to KGTriple table ──
        inserted = 0
        for triple in triples:
            db.add(triple)
            inserted += 1
        if inserted > 0:
            db.commit()
            logger.info("KG indexed: %d triples for doc %s", inserted, doc_id[:8])
        else:
            db.rollback()

        return {"triples_inserted": inserted}

    except Exception as e:
        db.rollback()
        logger.exception("KG index failed for doc %s: %s", doc_id[:8], e)
        return {"triples_inserted": 0, "error": str(e)}
    finally:
        db.close()


def kg_disambiguate(query: str) -> Dict:
    """KG entity disambiguation - map query entities to known documents.

    Args:
        query: user query string

    Returns:
        {
            "matched_entities": [...],
            "suggested_doc_ids": [...],
            "disambiguated": bool,
        }
    """
    entities: List[Dict] = []
    suggested_ids: List[str] = []

    db = SessionLocal()
    try:
        # Standard number matching
        std_num = _extract_standard_number(query)
        if std_num:
            docs = db.query(Document).filter(
                Document.status == "active",
            ).all()
            for doc in docs:
                doc_std = _extract_standard_number(doc.title or "")
                if doc_std and doc_std == std_num:
                    entities.append({
                        "name": doc.title,
                        "doc_id": doc.doc_id,
                        "type": "document",
                        "match_type": "standard_number",
                    })
                    suggested_ids.append(doc.doc_id)

        # Title keyword matching
        if not entities:
            keywords = re.findall(r'[\w一-鿿]{2,}', query)
            if keywords:
                docs = db.query(Document).filter(
                    Document.status == "active",
                ).limit(20).all()
                for doc in docs:
                    title_lower = (doc.title or "").lower()
                    matches = [kw for kw in keywords if kw.lower() in title_lower]
                    if len(matches) >= 2:
                        entities.append({
                            "name": doc.title,
                            "doc_id": doc.doc_id,
                            "type": "document",
                            "match_type": "title_keyword",
                        })
                        suggested_ids.append(doc.doc_id)

        return {
            "matched_entities": entities,
            "suggested_doc_ids": suggested_ids,
            "disambiguated": len(entities) > 0,
        }
    except Exception as e:
        logger.exception("KG disambiguate error: %s", e)
        return {
            "matched_entities": [],
            "suggested_doc_ids": [],
            "disambiguated": False,
        }
    finally:
        db.close()


def _extract_citations(text: str, db) -> List[Document]:
    """Extract standard references (GB/GA/JJF/ISO) from text and find matching docs.

    Args:
        text: document full text
        db: database session

    Returns:
        list of matched Document objects
    """
    patterns = re.finditer(
        r'(GB\s*[/\s]?T?\s*\d+[-\d]*|GA\s*[/\s]?\d+[-\d]*|JJF\s*\d+[-\d]*|ISO\s*[/\s]?\d+[-\d]*)',
        text,
    )
    found = set()
    results: List[Document] = []

    for match in patterns:
        raw = match.group()
        normalized = re.sub(r'[/\s]+', '-', raw).lower().strip('-')
        if normalized in found:
            continue
        found.add(normalized)

        docs = db.query(Document).filter(
            Document.status == "active",
        ).all()
        for doc in docs:
            doc_std = _extract_standard_number(doc.title or "")
            if doc_std and doc_std == normalized:
                results.append(doc)
                break

    return results
