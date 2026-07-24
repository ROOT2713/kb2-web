"""Wiki service — structured knowledge layer alongside RAG.

Wiki entries are structured records (standards, FAQs, guides) with
flexible JSON content per category. The service supports CRUD,
keyword search, cross-reference relations, and query-time retrieval
for augmenting RAG answers.
"""
import json
import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import text as sa_text

from app.models.database import SessionLocal

logger = logging.getLogger(__name__)

# ── Category schemas (documented, not enforced in DB) ──
# standard:  {"scope": "...", "key_clauses": "...", "application": "...", "notes": "..."}
# faq:       {"question": "...", "answer": "...", "references": [...]}
# guide:     {"purpose": "...", "method": "...", "examples": "..."}
# term:      {"definition": "...", "context": "...", "synonyms": [...]}


def _now() -> str:
    return datetime.utcnow().isoformat()


# ── CRUD ──


def create_entry(
    title: str,
    standard_no: str = "",
    category: str = "",
    subcategory: str = "",
    tags: list = None,
    summary: str = "",
    content: dict = None,
    source_doc_id: str = "",
    importance: int = 0,
    status: str = "draft",
) -> Optional[int]:
    """Create a new wiki entry. Returns entry ID or None on failure."""
    db = SessionLocal()
    try:
        now = _now()
        db.execute(sa_text(
            "INSERT INTO wiki_entries "
            "(title, standard_no, category, subcategory, tags, summary, content, "
            " source_doc_id, importance, status, created_at, updated_at) "
            "VALUES (:title, :std, :cat, :sub, :tags, :summary, :content, "
            " :src, :imp, :status, :now, :now)"
        ), {
            "title": title, "std": standard_no, "cat": category,
            "sub": subcategory, "tags": json.dumps(tags or [], ensure_ascii=False),
            "summary": summary, "content": json.dumps(content or {}, ensure_ascii=False),
            "src": source_doc_id, "imp": importance, "status": status, "now": now,
        })
        db.commit()
        result = db.execute(sa_text("SELECT last_insert_rowid()")).scalar()
        return result
    except Exception as e:
        logger.error("[Wiki] create_entry failed: %s", e)
        db.rollback()
        return None
    finally:
        db.close()


def update_entry(entry_id: int, **kwargs) -> bool:
    """Update wiki entry fields. Returns True on success."""
    allowed = {"title", "standard_no", "category", "subcategory", "tags",
               "summary", "content", "source_doc_id", "importance", "status"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    db = SessionLocal()
    try:
        now = _now()
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = entry_id
        updates["updated_at"] = now
        if "tags" in updates and isinstance(updates["tags"], list):
            updates["tags"] = json.dumps(updates["tags"], ensure_ascii=False)
        if "content" in updates and isinstance(updates["content"], dict):
            updates["content"] = json.dumps(updates["content"], ensure_ascii=False)
        db.execute(sa_text(
            f"UPDATE wiki_entries SET {set_clause}, updated_at = :updated_at WHERE id = :id"
        ), updates)
        db.commit()
        return db.rowcount > 0
    except Exception as e:
        logger.error("[Wiki] update_entry %d failed: %s", entry_id, e)
        db.rollback()
        return False
    finally:
        db.close()


def delete_entry(entry_id: int) -> bool:
    """Delete wiki entry and its relations."""
    db = SessionLocal()
    try:
        db.execute(sa_text("DELETE FROM wiki_relations WHERE source_entry_id = :id OR target_entry_id = :id"),
                   {"id": entry_id})
        db.execute(sa_text("DELETE FROM wiki_entries WHERE id = :id"), {"id": entry_id})
        db.commit()
        return db.rowcount > 0
    except Exception as e:
        logger.error("[Wiki] delete_entry %d failed: %s", entry_id, e)
        db.rollback()
        return False
    finally:
        db.close()


def get_entry(entry_id: int) -> Optional[dict]:
    """Fetch a single wiki entry by ID."""
    db = SessionLocal()
    try:
        row = db.execute(sa_text(
            "SELECT * FROM wiki_entries WHERE id = :id"
        ), {"id": entry_id}).mappings().first()
        if not row:
            return None
        entry = dict(row)
        entry["tags"] = json.loads(entry.get("tags", "[]"))
        entry["content"] = json.loads(entry.get("content", "{}"))
        # Fetch relations
        rels = db.execute(sa_text(
            "SELECT wr.*, we.title AS target_title, we.standard_no AS target_std "
            "FROM wiki_relations wr "
            "JOIN wiki_entries we ON wr.target_entry_id = we.id "
            "WHERE wr.source_entry_id = :id"
        ), {"id": entry_id}).mappings().all()
        entry["relations"] = [dict(r) for r in rels]
        return entry
    except Exception as e:
        logger.error("[Wiki] get_entry %d failed: %s", entry_id, e)
        return None
    finally:
        db.close()


# ── Search ──


def search_entries(
    query: str = "",
    category: str = "",
    standard_no: str = "",
    status: str = "",
    limit: int = 20,
    offset: int = 0,
) -> list:
    """Search wiki entries by keyword, category, or standard number."""
    db = SessionLocal()
    try:
        conditions = []
        params = {}
        if query:
            conditions.append("(title LIKE :q OR summary LIKE :q OR standard_no LIKE :q)")
            params["q"] = f"%{query}%"
        if category:
            conditions.append("category = :cat")
            params["cat"] = category
        if standard_no:
            conditions.append("standard_no LIKE :std")
            params["std"] = f"%{standard_no}%"
        if status:
            conditions.append("status = :status")
            params["status"] = status
        where = " AND ".join(conditions) if conditions else "1=1"
        rows = db.execute(sa_text(
            f"SELECT id, title, standard_no, category, subcategory, "
            f"summary, importance, status, created_at, updated_at "
            f"FROM wiki_entries WHERE {where} "
            f"ORDER BY importance DESC, updated_at DESC "
            f"LIMIT :lim OFFSET :off"
        ), {**params, "lim": limit, "off": offset}).mappings().all()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("[Wiki] search_entries failed: %s", e)
        return []
    finally:
        db.close()


def search_entries_count(
    query: str = "",
    category: str = "",
    standard_no: str = "",
    status: str = "",
) -> int:
    """Count wiki entries matching search criteria."""
    db = SessionLocal()
    try:
        conditions = []
        params = {}
        if query:
            conditions.append("(title LIKE :q OR summary LIKE :q OR standard_no LIKE :q)")
            params["q"] = f"%{query}%"
        if category:
            conditions.append("category = :cat")
            params["cat"] = category
        if standard_no:
            conditions.append("standard_no LIKE :std")
            params["std"] = f"%{standard_no}%"
        if status:
            conditions.append("status = :status")
            params["status"] = status
        where = " AND ".join(conditions) if conditions else "1=1"
        return db.execute(sa_text(
            f"SELECT COUNT(*) FROM wiki_entries WHERE {where}"
        ), params).scalar()
    except Exception as e:
        logger.error("[Wiki] search_entries_count failed: %s", e)
        return 0
    finally:
        db.close()


def list_categories() -> list:
    """Return distinct (category, subcategory, count) groups."""
    db = SessionLocal()
    try:
        rows = db.execute(sa_text(
            "SELECT category, subcategory, COUNT(*) as cnt "
            "FROM wiki_entries WHERE status != 'archived' "
            "GROUP BY category, subcategory ORDER BY category, subcategory"
        )).mappings().all()
        return [dict(r) for r in rows]
    finally:
        db.close()


# ── Relations ──


def add_relation(source_id: int, target_id: int, rel_type: str, desc: str = "") -> bool:
    """Add a cross-reference between two wiki entries."""
    db = SessionLocal()
    try:
        db.execute(sa_text(
            "INSERT INTO wiki_relations (source_entry_id, target_entry_id, relation_type, description) "
            "VALUES (:src, :tgt, :typ, :desc)"
        ), {"src": source_id, "tgt": target_id, "typ": rel_type, "desc": desc})
        db.commit()
        return True
    except Exception as e:
        logger.error("[Wiki] add_relation failed: %s", e)
        db.rollback()
        return False
    finally:
        db.close()


def remove_relation(relation_id: int) -> bool:
    """Delete a cross-reference."""
    db = SessionLocal()
    try:
        db.execute(sa_text("DELETE FROM wiki_relations WHERE id = :id"), {"id": relation_id})
        db.commit()
        return db.rowcount > 0
    finally:
        db.close()


# ── Query-time integration ──


def retrieve_for_query(query: str, limit: int = 5) -> list:
    """Retrieve wiki entries relevant to a user query.

    Matches by keyword overlap between query and (title + summary + standard_no).
    Uses jieba segmentation for Chinese queries to avoid treating full sentences as single terms.
    """
    db = SessionLocal()
    try:
        # Use jieba for Chinese segmentation, fallback to regex for pure ASCII queries
        try:
            import jieba
            _words = jieba.lcut(query, cut_all=False)
            # Filter: 2+ char Chinese words OR 2+ char alphanumeric tokens
            terms = set()
            for w in _words:
                w = w.strip().upper()
                if len(w) >= 2 and (re.match(r'[\u4e00-\u9fff]+$', w) or re.match(r'[A-Z0-9]+$', w)):
                    terms.add(w)
        except ImportError:
            terms = set(re.findall(r'[\u4e00-\u9fffA-Z0-9]{2,}', query.upper()))
        if not terms:
            return []
        rows = db.execute(sa_text(
            "SELECT id, title, standard_no, category, summary, content, importance "
            "FROM wiki_entries WHERE status = 'published'"
        )).mappings().all()
        scored = []
        for r in rows:
            text = (r["title"] + " " + r["standard_no"] + " " + r["summary"]).upper()
            score = sum(1 for t in terms if t in text)
            if score > 0:
                scored.append((score, dict(r)))
        scored.sort(key=lambda x: (-x[0], -x[1]["importance"]))
        result = []
        for score, entry in scored[:limit]:
            entry["_relevance"] = score
            entry["content"] = json.loads(entry.get("content", "{}"))
            entry["tags"] = json.loads(entry.get("tags", "[]"))
            result.append(entry)
        return result
    except Exception as e:
        logger.error("[Wiki] retrieve_for_query failed: %s", e)
        return []
    finally:
        db.close()
