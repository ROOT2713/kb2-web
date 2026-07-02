"""Bank management endpoints — CRUD for knowledge bases, wiki tree, categories.

Ported from: kb-web server.py list_banks() L4152-L4179,
             create_bank_api() L4180-L4216, delete_bank_api() L4217-L4252,
             wiki_tree() L4087-L4132, list_categories() L4133-L4151
"""

import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import get_db, SessionLocal
from app.services.retrieval import (
    BANKS, _active_hs_banks_cache, _hindsight_request, get_bank_config, reload_bank_config,
)

from app.middleware.auth import require_admin
from app.middleware.jwt_auth import require_role

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Default categories (matches v1 DEFAULT_CATEGORIES) ──────────
DEFAULT_CATEGORIES = [
    "\U0001f4a1想法", "\U0001f4bc工作", "\U0001f4da学习", "\U0001f3e0生活", "\U0001f680项目",
    "\U0001f4ad灵感", "\U0001f4dd会议", "\U0001f527技术", "\U0001f4ca数据", "\U0001f4f0资讯",
    "\U0001f512安全", "\U0001f916AI", "其他",
]


# ── Banks config persistence ─────────────────────────────────────

def _save_banks_config(banks: dict):
    """Save bank config to banks.json (matches v1 _save_banks_config L111-L122)."""
    to_save = {}
    for key, val in banks.items():
        cfg = dict(val)
        if "name" in cfg:
            cfg["label"] = cfg.pop("name")
        to_save[key] = cfg
    try:
        cfg_path = settings.banks_config_path
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(to_save, f, ensure_ascii=False, indent=2)
        logger.info("Saved %d banks to %s", len(to_save), cfg_path)
    except Exception as e:
        logger.error("Failed to save banks.json: %s", e)


def _load_banks_config() -> dict:
    """Load bank config from banks.json (matches v1 _load_banks_config L90-L109)."""
    cfg_path = settings.banks_config_path
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            normalized = {}
            for key, val in raw.items():
                cfg = dict(val)
                if "label" in cfg and "name" not in cfg:
                    cfg["name"] = cfg.pop("label")
                normalized[key] = cfg
            logger.info("Loaded %d banks from %s", len(normalized), cfg_path)
            return normalized
        except Exception as e:
            logger.warning("Failed to load banks.json: %s, using hardcoded fallback", e)
    else:
        logger.info("banks.json not found, using hardcoded fallback")
    return dict(BANKS)


def _refresh_banks():
    return reload_bank_config()


def _invalidate_bank_caches():
    _active_hs_banks_cache["banks"] = None
    _active_hs_banks_cache["ts"] = 0


# ═══════════════════════════════════════════════════════════════════
# Route: GET /wiki — knowledge base wiki tree
# ═══════════════════════════════════════════════════════════════════

@router.get("/wiki")
async def wiki_tree(bank: str = Query("all"), db: Session = Depends(get_db)):
    """Return knowledge base directory tree: bank -> category -> documents (v1 L4087-L4132)."""
    if bank == "all":
        rows = db.execute(
            sa_text(
                "SELECT doc_id, title, category, filename, bank, created_at, doc_type "
                "FROM documents WHERE bank NOT IN ('skip') ORDER BY bank, category, title"
            )
        ).fetchall()
    else:
        rows = db.execute(
            sa_text(
                "SELECT doc_id, title, category, filename, bank, created_at, doc_type "
                "FROM documents WHERE bank = :bank AND bank NOT IN ('skip') ORDER BY category, title"
            ),
            {"bank": bank}
        ).fetchall()

    tree = {}
    bank_counts = {}
    for r in rows:
        b = r[4] or "kb"  # bank
        cat = r[2] or "未分类"  # category
        if b not in tree:
            tree[b] = {}
            bank_counts[b] = 0
        if cat not in tree[b]:
            tree[b][cat] = []
        bank_counts[b] += 1
        tree[b][cat].append({
            "id": r[0],       # doc_id
            "title": r[1] or "unknown",
            "filename": r[3] or "",
            "doc_type": r[6] or "generic",
            "created": str(r[5]) if r[5] else "",
        })

    banks_cfg = _refresh_banks()
    bank_names = {k: v["name"] for k, v in banks_cfg.items() if k != "all"}

    return {
        "tree": tree,
        "bank_names": bank_names,
        "bank_counts": bank_counts,
        "total": len(rows),
    }


# ═══════════════════════════════════════════════════════════════════
# Route: GET /categories — list all categories with doc counts
# ═══════════════════════════════════════════════════════════════════

@router.get("/categories")
async def list_categories(db: Session = Depends(get_db)):
    """List all categories with document counts (v1 L4133-L4151)."""
    rows = db.execute(
        sa_text(
            "SELECT category, COUNT(*) as cnt FROM documents "
            "WHERE category != '' GROUP BY category ORDER BY cnt DESC"
        )
    ).fetchall()

    used = {r[0]: r[1] for r in rows}
    result = []
    for cat in DEFAULT_CATEGORIES:
        result.append({"name": cat, "count": used.get(cat, 0)})
    for cat, cnt in used.items():
        if cat not in DEFAULT_CATEGORIES:
            result.append({"name": cat, "count": cnt})
    return {"categories": result}


# ═══════════════════════════════════════════════════════════════════
# Route: GET / — list all banks with doc stats
# ═══════════════════════════════════════════════════════════════════

@router.get("")
async def list_banks(db: Session = Depends(get_db)):
    """List all banks with document statistics (v1 L4152-L4179)."""
    banks_cfg = _refresh_banks()
    bank_stats = {}
    searchable_stats = {}
    try:
        rows = db.execute(
            sa_text(
                "SELECT bank, COUNT(*) as cnt, SUM(CASE WHEN searchable=1 THEN 1 ELSE 0 END) as searchable_cnt "
                "FROM documents WHERE bank != 'skip' GROUP BY bank"
            )
        ).fetchall()
        bank_stats = {r[0]: r[1] for r in rows}
        searchable_stats = {r[0]: r[2] for r in rows}
    except Exception:
        pass
    total = sum(bank_stats.get(key, 0) for key in banks_cfg if key != "all")
    total_searchable = sum(searchable_stats.get(key, 0) for key in banks_cfg if key != "all")
    banks = []
    for key, cfg in banks_cfg.items():
        if key == "all":
            banks.append({
                "key": key, "name": cfg["name"], "count": total, "searchable": total_searchable,
                "description": cfg.get("description", ""), "hindsight": cfg.get("hindsight"),
            })
        else:
            banks.append({
                "key": key, "name": cfg["name"], "count": bank_stats.get(key, 0),
                "searchable": searchable_stats.get(key, 0),
                "description": cfg.get("description", ""), "hindsight": cfg.get("hindsight"),
            })
    return {"banks": banks}


# ═══════════════════════════════════════════════════════════════════
# Route: POST / — create a new bank
# ═══════════════════════════════════════════════════════════════════

@router.post("")
async def create_bank_api(
    key: str = Form(...),
    label: str = Form(...),
    description: str = Form(""),
    prompt: str = Form(""),
    _admin: bool = Depends(require_role("admin")),
):
    """Create a new knowledge base bank (v1 L4180-L4216)."""
    key = key.strip()
    label = label.strip()
    if not label:
        raise HTTPException(400, "bank label cannot be empty")
    banks_cfg = _refresh_banks()
    if key in banks_cfg or key == "all":
        raise HTTPException(409, f"bank '{key}' already exists")
    if not re.match(r'^[a-z_]+$', key):
        raise HTTPException(400, "bank key must contain only lowercase letters and underscores")

    hs_bank_id = f"kb_{key}"
    banks_cfg[key] = {
        "name": label,
        "hindsight": hs_bank_id,
        "prompt": prompt or f"You are an expert in the {label} domain.",
        "description": description,
    }
    # banks_cfg IS BANKS (same dict ref from _refresh_banks()), so no clear/update needed
    _save_banks_config(BANKS)
    _invalidate_bank_caches()
    logger.info("Created local bank config: key=%s hindsight=%s", key, hs_bank_id)
    return {"ok": True, "bank": key, "hindsight_bank": hs_bank_id}


# ═══════════════════════════════════════════════════════════════════
# Route: DELETE /{bank_key} — delete a bank
# ═══════════════════════════════════════════════════════════════════

@router.delete("/{bank_key}")
async def delete_bank_api(
    bank_key: str,
    confirm: bool = False,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_role("admin")),
):
    """Delete a bank (requires confirmation) (v1 L4217-L4252)."""
    banks_cfg = _refresh_banks()
    if bank_key not in banks_cfg or bank_key == "all":
        raise HTTPException(404, f"bank '{bank_key}' not found")

    count_row = db.execute(
        sa_text("SELECT COUNT(*) FROM documents WHERE bank = :bank"),
        {"bank": bank_key}
    ).fetchone()
    count = count_row[0] if count_row else 0

    if count > 0 and not confirm:
        return JSONResponse(
            {"ok": False, "detail": f"This bank has {count} documents, require confirm=true"},
            status_code=409,
        )

    hs_bank_id = banks_cfg[bank_key].get("hindsight")

    # 1. Delete Hindsight bank
    if hs_bank_id:
        try:
            await _hindsight_request(f"/v1/default/banks/{hs_bank_id}", "DELETE")
        except Exception as e:
            logger.warning("Failed to delete Hindsight bank: %s", e)

    # 2. Move documents to general
    if count > 0:
        db.execute(
            sa_text("UPDATE documents SET bank = 'general', hs_bank = 'kb_general' WHERE bank = :bank"),
            {"bank": bank_key}
        )
        db.commit()

    # 3. Remove from in-memory config
    del banks_cfg[bank_key]
    # banks_cfg IS BANKS (same dict ref from _refresh_banks()), so no clear/update needed
    _save_banks_config(BANKS)
    _invalidate_bank_caches()

    return {"ok": True, "moved_docs_to": "general" if count > 0 else None}
