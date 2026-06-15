"""Document management endpoints — list, get, patch, delete, reparse, fetch, audit.

Ported from: kb-web server.py get_document_content() L3792-L3880,
             list_documents() L4004-L4061, patch_document/patch_document_bank() L4062-L4086,
             delete_document() L4276-L4359, reparse_document() L4360-L4555,
             fetch_standard() L3881-L4003, refetch_document() L4814-L4957,
             rag_evaluation() L4556-L4684, audit_knowledge_base() L4685-L4813
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import traceback
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

import docx as _docx_lib
import httpx
import pypdf
from fastapi import APIRouter, Depends, Form, HTTPException, Query
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import get_db, SessionLocal
from app.repositories.document_repo import DocumentRepository
from app.services.retrieval import (
    recall, get_bank_config, _get_active_hindsight_banks,
    _hindsight_request, BANKS,
)
from app.services.generation import chat
from app.services.parsing import parse_document, mineru_parse_pdf
from app.services.chunking import heading_chunk, parent_child_chunk
from app.services.quality import assess_quality, profile_document
from app.services.cache_service import invalidate_for_doc, invalidate_bm25_cache
from app.utils.text_cleaning import filename_to_title, clean_watermarks
from app.middleware.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Default categories (matches v1 DEFAULT_CATEGORIES) ──────────
DEFAULT_CATEGORIES = [
    "\U0001f4a1想法", "\U0001f4bc工作", "\U0001f4da学习", "\U0001f3e0生活", "\U0001f680项目",
    "\U0001f4ad灵感", "\U0001f4dd会议", "\U0001f527技术", "\U0001f4ca数据", "\U0001f4f0资讯",
    "\U0001f512安全", "\U0001f916AI", "其他",
]

# ── Max file size (matches v1 MAX_FILE_SIZE, 50MB) ──────────────
MAX_FILE_SIZE = 50 * 1024 * 1024

# ── Old Hindsight banks for fallback lookups ─────────────────────
OLD_HINDSIGHT_BANKS = ["tech", "security", "ai", "notes", "proposals", "assessment", "projects"]


# ═══════════════════════════════════════════════════════════════════
# Background: verify document searchability
# ═══════════════════════════════════════════════════════════════════

async def _verify_searchable(v_doc_id, v_title, v_original_len, v_bank="kb"):
    """Upload/reparse async verification of document searchability (matches v1 L1772-L1796)."""
    await asyncio.sleep(10)  # wait for consolidation
    for attempt in range(3):
        try:
            recalled = await recall(v_title[:50], limit=20, bank=v_bank, max_tokens=8192)
            if len(recalled) > 0:
                db2 = SessionLocal()
                try:
                    db2.execute(
                        sa_text("UPDATE documents SET searchable=1, coverage_pct=80.0, verified_at=:now, original_text_length=:olen WHERE doc_id=:did"),
                        {"now": datetime.now(timezone.utc), "olen": v_original_len, "did": v_doc_id}
                    )
                    db2.commit()
                finally:
                    db2.close()
                logger.info("VERIFY OK %s searchable=true (recall=%d)", v_title[:40], len(recalled))
                return
            if attempt < 2:
                await asyncio.sleep(30 * (2 ** attempt))
        except Exception as e:
            logger.warning("VERIFY attempt %d error: %s", attempt + 1, e)
            if attempt < 2:
                await asyncio.sleep(10)
    db2 = SessionLocal()
    try:
        db2.execute(
            sa_text("UPDATE documents SET searchable=0, coverage_pct=0, verified_at=:now WHERE doc_id=:did"),
            {"now": datetime.now(timezone.utc), "did": v_doc_id}
        )
        db2.commit()
    finally:
        db2.close()
    logger.warning("VERIFY FAIL %s searchable=false after 3 attempts", v_title[:40])


# ═══════════════════════════════════════════════════════════════════
# Route: GET / — list all documents
# ═══════════════════════════════════════════════════════════════════

@router.get("")
async def list_documents(bank: str = Query("all"), db: Session = Depends(get_db)):
    """List documents (from meta.db, Hindsight supplements chunk/size)."""
    repo = DocumentRepository(db)

    if bank == "all":
        docs_list = repo.list_all()
    else:
        docs_list = repo.list_all(bank=bank)

    # From Hindsight supplement chunk/size data
    hs_stats = {}
    active_banks = await _get_active_hindsight_banks()
    for bank_id in active_banks:
        try:
            result = await _hindsight_request(
                f"/v1/default/banks/{bank_id}/documents?limit=1000", timeout=15
            )
            for item in result.get("items", []):
                doc_id = None
                for t in item.get("tags", []):
                    if t.startswith("doc_id:"):
                        doc_id = t[7:]
                        break
                if not doc_id:
                    continue
                if doc_id not in hs_stats:
                    hs_stats[doc_id] = {"chunks": 0, "size": 0}
                hs_stats[doc_id]["chunks"] += 1
                hs_stats[doc_id]["size"] += item.get("text_length", 0)
        except Exception as e:
            logger.warning("list_documents: bank %s stats failed: %s", bank_id, e)

    docs = []
    for d in docs_list:
        stats = hs_stats.get(d.doc_id, {"chunks": 0, "size": 0})
        docs.append({
            "id": d.doc_id,
            "title": d.title or "unknown",
            "category": d.category or "",
            "filename": d.filename or "",
            "chunks": stats["chunks"],
            "size_chars": stats["size"],
            "created": d.created_at.isoformat() if d.created_at else "",
            "bank": d.bank or "kb",
            "searchable": d.searchable if d.searchable is not None else 0,
            "coverage_pct": d.coverage_pct if d.coverage_pct is not None else 0,
        })

    return {"documents": docs}


# ═══════════════════════════════════════════════════════════════════
# Route: POST /fetch-standard — download standard from public source
# ═══════════════════════════════════════════════════════════════════

@router.post("/fetch-standard")
async def fetch_standard(
    std_no: str = Form(...),
    bank: str = Form("kb"),
    db: Session = Depends(get_db),
):
    """Download and index a national standard from public sources (v1 L3881-L4003)."""
    if not std_no.strip():
        raise HTTPException(400, "Standard number cannot be empty")

    bank_cfg = get_bank_config(bank)
    if bank == "all":
        bank = "general"
    hs_bank = bank_cfg["hindsight"] or "kb"

    # Step 1: Search with AnySearch
    anysearch_cli = os.path.expanduser("~/.agents/skills/anysearch/scripts/anysearch_cli.py")
    try:
        result = subprocess.run(
            ["python3", anysearch_cli, "search", f"{std_no} standard PDF", "-m", "5", "--freshness", "year"],
            capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "Search timed out")
    except Exception as e:
        raise HTTPException(500, f"Search failed: {e}")

    urls = [line.split("**URL**: ")[1].strip() for line in result.stdout.split('\n') if "**URL**: " in line]
    if not urls:
        raise HTTPException(404, f"No download links found for {std_no}")

    # Step 2: Download PDF
    pdf_path = None
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for url in urls[:3]:
            try:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200 and "application/pdf" in resp.headers.get("content-type", ""):
                    fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
                    os.write(fd, resp.content)
                    os.close(fd)
                    break
            except Exception:
                continue

    if not pdf_path:
        raise HTTPException(500, "Download failed: all links unavailable")

    # Step 3: Parse PDF
    try:
        text = ""
        with open(pdf_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
        os.unlink(pdf_path)
    except Exception as e:
        if os.path.exists(pdf_path):
            os.unlink(pdf_path)
        raise HTTPException(500, f"PDF parse failed: {e}")

    if not text or len(text.strip()) < 100:
        raise HTTPException(400, "PDF content too short, may be scanned image")

    # Step 4: Upload to Hindsight
    doc_title = std_no.strip()
    chunk_size = 1000
    chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
    doc_id = str(uuid.uuid4())

    memory_items = []
    for i, chunk in enumerate(chunks):
        chunk = chunk.strip()
        if not chunk:
            continue
        tags = [
            f"doc:{doc_title}.pdf",
            f"chunk:{i + 1}/{len(chunks)}",
            f"doc_id:{doc_id}",
            f"title:{doc_title}",
            f"bank:{bank}",
        ]
        memory_items.append({"content": chunk, "tags": tags, "type": "world"})

    success_count = 0
    total_count = len(memory_items)
    if memory_items:
        dyn_timeout = max(120, min(len(memory_items) * 5, 600))
        try:
            result = await _hindsight_request(
                f"/v1/default/banks/{hs_bank}/memories",
                "POST",
                {"items": memory_items},
                timeout=dyn_timeout,
            )
            success_count = result.get("items_count", 0)
        except Exception as e:
            raise HTTPException(500, f"Hindsight upload failed: {e}")

    if success_count == 0:
        raise HTTPException(500, "Upload failed: all chunks rejected by Hindsight")

    # Step 5: Write meta
    repo = DocumentRepository(db)
    repo.save(
        doc_id=doc_id,
        title=doc_title,
        category="",
        filename=f"{doc_title}.pdf",
        content_hash="",
        doc_type="generic",
        bank=bank,
        hs_bank=hs_bank,
    )

    return {
        "ok": True,
        "doc_id": doc_id,
        "title": doc_title,
        "bank": bank,
        "text_length": len(text),
        "chunks": f"{success_count}/{total_count}",
    }


# ═══════════════════════════════════════════════════════════════════
# Route: POST /refetch — re-download and re-parse a document
# ═══════════════════════════════════════════════════════════════════

@router.post("/refetch")
async def refetch_document(
    doc_id: str = Form(...),
    std_no: str = Form(""),
    db: Session = Depends(get_db),
):
    """Re-download standard document, parse with MinerU, replace old data (v1 L4814-L4957)."""
    repo = DocumentRepository(db)
    meta = repo.get_meta(doc_id)
    if not meta or not meta.get("title"):
        raise HTTPException(404, "Document not found")

    old_bank = meta.get("bank", "kb")
    bank_cfg = BANKS.get(old_bank, BANKS["all"])
    hs_bank = bank_cfg["hindsight"]

    search_term = std_no.strip() or meta["title"]

    # Step 1: Search AnySearch
    anysearch_cli = os.path.expanduser("~/.agents/skills/anysearch/scripts/anysearch_cli.py")
    try:
        result = subprocess.run(
            ["python3", anysearch_cli, "search", f"{search_term} standard PDF", "-m", "5", "--freshness", "year"],
            capture_output=True, text=True, timeout=30
        )
        urls = [line.split("**URL**: ")[1].strip() for line in result.stdout.split('\n') if "**URL**: " in line]
    except Exception as e:
        raise HTTPException(500, f"Search failed: {e}")

    if not urls:
        raise HTTPException(404, f"No download links found for {search_term}")

    # Step 2: Download PDF
    pdf_path = None
    pdf_content = None
    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
        for url in urls[:3]:
            try:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    ct = resp.headers.get("content-type", "")
                    if "application/pdf" in ct or url.lower().endswith(".pdf"):
                        pdf_content = resp.content
                        fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
                        os.write(fd, pdf_content)
                        os.close(fd)
                        break
            except Exception:
                continue

    if not pdf_path or not pdf_content:
        raise HTTPException(500, "Download failed")

    # Step 3: Parse with MinerU
    text = ""
    try:
        text = await mineru_parse_pdf(f"{search_term}.pdf", pdf_content)
    except Exception:
        with open(pdf_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"

    os.unlink(pdf_path)

    if not text or len(text.strip()) < 100:
        raise HTTPException(400, "PDF content too short after parsing")

    # Step 4: Delete old vectors from Hindsight
    try:
        docs_result = await _hindsight_request(
            f"/v1/default/banks/{hs_bank}/documents", timeout=10
        )
        doc_list = docs_result.get("items", []) or docs_result.get("documents", [])
        for d in doc_list:
            tags = d.get("tags", [])
            if f"doc_id:{doc_id}" in tags:
                try:
                    await _hindsight_request(
                        f"/v1/default/banks/{hs_bank}/documents/{d['id']}",
                        method="DELETE", timeout=10
                    )
                except Exception:
                    pass
    except Exception:
        pass

    # Step 5: Re-upload with new text
    chunk_size = 1000
    chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

    success_count = 0
    total_count = 0
    async with httpx.AsyncClient(timeout=30) as client:
        hs_url = settings.hindsight_url
        for i, chunk in enumerate(chunks):
            chunk = chunk.strip()
            if not chunk:
                continue
            total_count += 1
            payload = [{
                "text": chunk,
                "tags": [
                    f"doc:{search_term}.pdf",
                    f"chunk:{i + 1}/{len(chunks)}",
                    f"doc_id:{doc_id}",
                    f"title:{search_term}",
                ]
            }]
            try:
                r = await client.post(
                    f"{hs_url}/v1/default/banks/{hs_bank}/memories",
                    json=payload
                )
                if r.status_code in (200, 201):
                    success_count += 1
            except Exception:
                pass

    repo.update(doc_id, title=search_term)

    quality = assess_quality(text)

    return {
        "ok": True,
        "doc_id": doc_id,
        "title": search_term,
        "text_length": len(text),
        "chunks": f"{success_count}/{total_count}",
        "new_score": quality["score"],
        "used_mineru": bool(settings.mineru_api_key),
    }


# ═══════════════════════════════════════════════════════════════════
# Route: GET /rag-eval — RAG quality evaluation
# ═══════════════════════════════════════════════════════════════════

@router.get("/rag-eval")
async def rag_evaluation():
    """RAG quality evaluation — 4 dimensions (RAGAS style) (v1 L4556-L4684)."""
    test_cases = [
        {"q": "The security zone boundary requirements for Level 3 classified protection", "bank": "standards", "expect_doc": "classified protection"},
        {"q": "The acceptance process steps for government IT projects", "bank": "project_docs", "expect_doc": "acceptance"},
        {"q": "Software cost estimation methods and basis", "bank": "industry_docs", "expect_doc": "cost estimation"},
        {"q": "Evaluation requirements for cryptographic application plans", "bank": "standards", "expect_doc": "cryptography"},
        {"q": "Main content of IT project initiation consulting", "bank": "project_docs", "expect_doc": "initiation"},
        {"q": "National standard number for classified protection evaluation", "bank": "standards", "expect_doc": "GB"},
        {"q": "Responsibilities of government IT supervision services", "bank": "standards", "expect_doc": "supervision"},
        {"q": "Technical requirements for data center construction", "bank": "standards", "expect_doc": "data center"},
    ]

    results = []
    dimensions = {"retrieval": [], "groundedness": [], "relevance": [], "utilization": []}

    for tc in test_cases:
        try:
            recalled = await recall(tc["q"], limit=10, bank="kb")
            context_texts = [r.get("text", "") for r in recalled if r.get("text")]
            context_block = "\n\n---\n\n".join(context_texts[:5])

            if not context_block.strip():
                results.append({
                    "q": tc["q"], "bank": tc["bank"], "error": "no recall results",
                    "scores": {"retrieval": 0, "groundedness": 0, "relevance": 0, "utilization": 0}
                })
                continue

            bank_cfg = get_bank_config(tc["bank"])
            bank_prompt = bank_cfg["prompt"]
            answer_prompt = (
                f"{bank_prompt}\n\n"
                "[Hard Rules]\n"
                "1. Only use information from the document content below, do not supplement with training knowledge\n"
                "2. Each key claim must cite the source document name in brackets\n"
                "3. If the document has no relevant info, answer 'Cannot determine based on available materials'\n\n"
                f"Document content:\n{context_block}\n\n"
                f"Question: {tc['q']}\n\n"
                "Answer in Chinese, cite specific clauses and data, and mark information sources."
            )

            answer = await chat([
                {"role": "system", "content": bank_prompt},
                {"role": "user", "content": answer_prompt},
            ])

            eval_prompt = (
                f"You are a RAG system evaluation expert. Score the following Q&A pair on 4 dimensions.\n\n"
                f"[Question] {tc['q']}\n\n"
                f"[Retrieved document snippets]\n{context_block[:3000]}\n\n"
                f"[Generated answer]\n{answer[:2000]}\n\n"
                "Score each dimension (0.0 ~ 1.0) with a brief reason:\n\n"
                "1. Retrieval: relevance of retrieved snippets to question\n"
                "2. Groundedness: whether each sentence in the answer is grounded in snippets\n"
                "3. Relevance: whether the answer addresses the question\n"
                "4. Utilization: whether the answer fully utilizes retrieved content\n\n"
                "Respond ONLY with this JSON format, nothing else:\n"
                '{"retrieval": {"score": 0.0, "reason": "..."}, '
                '"groundedness": {"score": 0.0, "reason": "..."}, '
                '"relevance": {"score": 0.0, "reason": "..."}, '
                '"utilization": {"score": 0.0, "reason": "..."}}'
            )

            eval_result = await chat([
                {"role": "system", "content": "You are a strict RAG evaluator. Output JSON only."},
                {"role": "user", "content": eval_prompt},
            ])

            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', eval_result, re.DOTALL)
            scores = {"retrieval": 0, "groundedness": 0, "relevance": 0, "utilization": 0}
            if json_match:
                try:
                    parsed = json.loads(json_match.group())
                    for dim in ["retrieval", "groundedness", "relevance", "utilization"]:
                        val = parsed.get(dim, {})
                        if isinstance(val, dict):
                            scores[dim] = round(float(val.get("score", 0)), 2)
                        elif isinstance(val, (int, float)):
                            scores[dim] = round(float(val), 2)
                except Exception:
                    pass

            for dim in dimensions:
                dimensions[dim].append(scores[dim])

            results.append({
                "q": tc["q"],
                "bank": tc["bank"],
                "answer_preview": answer[:200],
                "chunks_recalled": len(recalled),
                "scores": scores,
                "eval_raw": eval_result[:500],
            })

        except Exception as e:
            results.append({
                "q": tc["q"], "bank": tc["bank"], "error": str(e)[:200],
                "scores": {"retrieval": 0, "groundedness": 0, "relevance": 0, "utilization": 0}
            })

    avg_scores = {}
    for dim in dimensions:
        vals = dimensions[dim]
        avg_scores[dim] = round(sum(vals) / max(len(vals), 1), 2)

    overall = round(sum(avg_scores.values()) / 4, 2)

    return {
        "total_cases": len(test_cases),
        "evaluated": len([r for r in results if "error" not in r]),
        "avg_scores": avg_scores,
        "overall": overall,
        "details": results,
    }


# ═══════════════════════════════════════════════════════════════════
# Route: GET /audit — knowledge base quality audit
# ═══════════════════════════════════════════════════════════════════

@router.get("/audit")
async def audit_knowledge_base(db: Session = Depends(get_db)):
    """Scan all documents, output quality audit report (v1 L4685-L4813)."""
    repo = DocumentRepository(db)
    docs_list = repo.list_all()

    results = []
    for d in docs_list:
        doc_id = d.doc_id
        title = d.title or "unknown"
        bank = d.bank or "kb"

        bank_cfg = BANKS.get(bank, BANKS["all"])
        hs_bank = bank_cfg["hindsight"]

        full_text = ""
        try:
            hindsight_doc_id = None
            docs_result = await _hindsight_request(
                f"/v1/default/banks/{hs_bank}/documents", timeout=10
            )
            doc_list = docs_result.get("items", []) or docs_result.get("documents", [])
            for item in doc_list:
                if f"doc_id:{doc_id}" in item.get("tags", []):
                    hindsight_doc_id = item.get("id")
                    break

            if not hindsight_doc_id and hs_bank != "kb":
                try:
                    docs_result = await _hindsight_request(
                        f"/v1/default/banks/kb/documents", timeout=10
                    )
                    doc_list = docs_result.get("items", []) or docs_result.get("documents", [])
                    for item in doc_list:
                        if f"doc_id:{doc_id}" in item.get("tags", []):
                            hindsight_doc_id = item.get("id")
                            hs_bank = "kb"
                            break
                except Exception:
                    pass

            if hindsight_doc_id:
                doc_detail = await _hindsight_request(
                    f"/v1/default/banks/{hs_bank}/documents/{hindsight_doc_id}", timeout=10
                )
                full_text = doc_detail.get("original_text", "") or doc_detail.get("text", "") or ""
            else:
                try:
                    recall_result = await recall(title, limit=50, bank="kb", max_tokens=32768)
                    texts = []
                    for r in recall_result:
                        t = r.get("text", "") or ""
                        if t.strip():
                            texts.append(t.strip())
                    full_text = "\n\n".join(texts)
                except Exception:
                    pass
        except Exception as e:
            logger.warning("audit: failed to get text for %s: %s", doc_id, e)

        quality = assess_quality(full_text)

        filename = d.filename or ""
        completeness = None
        if filename:
            try:
                upload_path = settings.upload_dir / Path(filename).name
            except Exception:
                upload_path = None

            if upload_path and upload_path.exists():
                try:
                    with open(upload_path, "rb") as f:
                        raw = f.read()
                    orig_chars = 0
                    ext = os.path.splitext(filename)[1].lower()
                    if ext == ".pdf":
                        reader = pypdf.PdfReader(BytesIO(raw))
                        for page in reader.pages:
                            t = page.extract_text()
                            if t:
                                orig_chars += len(t)
                    elif ext in (".txt", ".md"):
                        orig_chars = len(raw.decode("utf-8", errors="ignore"))
                    elif ext == ".docx":
                        dx = _docx_lib.Document(BytesIO(raw))
                        orig_chars = sum(len(p.text) for p in dx.paragraphs)

                    if orig_chars > 0:
                        coverage = min(100, round(len(full_text) / orig_chars * 100))
                        completeness = {
                            "available": True,
                            "original_chars": orig_chars,
                            "retrieved_chars": len(full_text),
                            "coverage_pct": coverage,
                        }
                except Exception:
                    pass

        if not completeness:
            completeness = {"available": False, "reason": "Original file unavailable (deleted or not retained)"}

        results.append({
            "doc_id": doc_id,
            "title": title,
            "bank": bank,
            "chars": len(full_text),
            "score": quality["score"],
            "issues": quality["issues"],
            "needs_refetch": quality["score"] < 70,
            "completeness": completeness,
        })

    total = len(results)
    low_quality = [r for r in results if r["needs_refetch"]]
    avg_score = sum(r["score"] for r in results) / max(total, 1)

    return {
        "total_docs": total,
        "avg_score": round(avg_score, 1),
        "low_quality_count": len(low_quality),
        "documents": sorted(results, key=lambda x: x["score"]),
    }


# ═══════════════════════════════════════════════════════════════════
# Route: GET /{doc_id} — get document full content
# ═══════════════════════════════════════════════════════════════════

@router.get("/{doc_id}")
async def get_document_content(doc_id: str, db: Session = Depends(get_db)):
    """Get full text content of a document (v1 L3792-L3880)."""
    repo = DocumentRepository(db)
    meta = repo.get_meta(doc_id)
    if not meta or not meta.get("title"):
        raise HTTPException(404, "Document not found")

    doc_bank = meta.get("bank", "kb")
    bank_cfg = get_bank_config(doc_bank)
    hs_bank = bank_cfg["hindsight"]

    docs_result = await _hindsight_request(
        f"/v1/default/banks/{hs_bank}/documents",
        timeout=10
    )
    doc_list = docs_result.get("items", []) or docs_result.get("documents", [])

    hindsight_doc_id = None
    for d in doc_list:
        tags = d.get("tags", [])
        if f"doc_id:{doc_id}" in tags:
            hindsight_doc_id = d.get("id")
            break

    if not hindsight_doc_id:
        for fallback in OLD_HINDSIGHT_BANKS:
            if fallback == hs_bank:
                continue
            try:
                fb_result = await _hindsight_request(
                    f"/v1/default/banks/{fallback}/documents",
                    timeout=5
                )
                fb_list = fb_result.get("items", []) or fb_result.get("documents", [])
                for d in fb_list:
                    if f"doc_id:{doc_id}" in d.get("tags", []):
                        hindsight_doc_id = d.get("id")
                        hs_bank = fallback
                        break
            except Exception:
                pass
            if hindsight_doc_id:
                break

    if not hindsight_doc_id:
        try:
            title = meta.get("title", "")
            if title:
                recalled = await recall(title, limit=50, bank="kb", max_tokens=32768)
                if recalled:
                    full_text = "\n\n".join(r.get("text", "") for r in recalled)
                    if full_text and len(full_text) > 50:
                        return {
                            "doc_id": doc_id,
                            "id": doc_id,
                            "title": title,
                            "filename": meta.get("filename", ""),
                            "bank": meta.get("bank", "kb"),
                            "chunks": len(recalled),
                            "searchable": meta.get("searchable", 0),
                            "created": meta.get("created_at", ""),
                            "coverage_pct": meta.get("coverage_pct", 0),
                            "text": full_text,
                            "source": "recall",
                        }
        except Exception:
            pass
        raise HTTPException(404, "Document content not found (may not be indexed yet)")

    doc_detail = await _hindsight_request(
        f"/v1/default/banks/{hs_bank}/documents/{hindsight_doc_id}",
        timeout=10
    )
    full_text = doc_detail.get("original_text", "") or doc_detail.get("text", "") or ""
    chunks_count = doc_detail.get("memory_unit_count", 0)

    return {
        "doc_id": doc_id,
        "id": doc_id,
        "title": meta.get("title", "unknown"),
        "filename": meta.get("filename", ""),
        "bank": meta.get("bank", "kb"),
        "chunks": chunks_count,
        "searchable": meta.get("searchable", 0),
        "created": meta.get("created_at", ""),
        "coverage_pct": meta.get("coverage_pct", 0),
        "text": full_text,
    }


# ═══════════════════════════════════════════════════════════════════
# Route: GET /{doc_id}/content — V1 compatibility alias
# ═══════════════════════════════════════════════════════════════════

@router.get("/{doc_id}/content")
async def get_document_content_v1(doc_id: str, db: Session = Depends(get_db)):
    """V1 compatibility alias — delegates to get_document_content."""
    return await get_document_content(doc_id, db)


# ═══════════════════════════════════════════════════════════════════
# Route: PATCH /{doc_id} — edit document metadata
# ═══════════════════════════════════════════════════════════════════

@router.patch("/{doc_id}")
async def patch_document(
    doc_id: str,
    title: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Edit document title and category (v1 L4062-L4067)."""
    if not title and not category:
        raise HTTPException(400, "Must provide at least title or category")
    repo = DocumentRepository(db)
    updated = repo.update(doc_id, title=title, category=category)
    if updated is None:
        raise HTTPException(404, f"Document {doc_id} not found")
    return {"ok": True, "doc_id": doc_id, "title": title, "category": category}


# ═══════════════════════════════════════════════════════════════════
# Route: PATCH /{doc_id}/bank — change document bank
# ═══════════════════════════════════════════════════════════════════

@router.patch("/{doc_id}/bank")
async def patch_document_bank(
    doc_id: str,
    bank: str = Form(...),
    db: Session = Depends(get_db),
):
    """Change document bank assignment (v1 L4070-L4083)."""
    if bank not in BANKS:
        raise HTTPException(400, f"Invalid bank: {bank}, valid: {', '.join(BANKS.keys())}")
    repo = DocumentRepository(db)
    doc = repo.get(doc_id)
    if doc is None:
        raise HTTPException(404, f"Document {doc_id} not found")
    doc.bank = bank
    db.commit()
    return {"ok": True, "doc_id": doc_id, "bank": bank}


# ═══════════════════════════════════════════════════════════════════
# Route: DELETE /{doc_id} — delete document
# ═══════════════════════════════════════════════════════════════════

@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    db: Session = Depends(get_db),
    admin: bool = Depends(require_admin),
):
    """Delete document and all its vectors (v1 L4276-L4359)."""
    repo = DocumentRepository(db)
    doc = repo.get(doc_id)
    doc_hs_bank = doc.hs_bank if doc and doc.hs_bank else None
    doc_bank = doc.bank if doc else None

    if doc_hs_bank:
        search_banks = [doc_hs_bank]
        active_banks = await _get_active_hindsight_banks()
        if doc_hs_bank != "kb" and "kb" in active_banks:
            search_banks.append("kb")
    else:
        search_banks = await _get_active_hindsight_banks()

    all_items = []
    for bank_id in search_banks:
        try:
            bank_docs = await _hindsight_request(
                f"/v1/default/banks/{bank_id}/documents?limit=500",
                timeout=15,
            )
            for item in bank_docs.get("items", []):
                item["_bank"] = bank_id
            all_items.extend(bank_docs.get("items", []))
        except Exception as e:
            logger.warning("delete_document: failed to list bank %s: %s", bank_id, e)

    deleted_hs = 0
    for item in all_items:
        tags = item.get("tags", [])
        for t in tags:
            if t == f"doc_id:{doc_id}":
                try:
                    await _hindsight_request(
                        f"/v1/default/banks/{item['_bank']}/documents/{item['id']}",
                        "DELETE",
                        timeout=10,
                    )
                    deleted_hs += 1
                except Exception as e:
                    logger.warning("delete_document: HS delete failed %s: %s", item["id"][:16], e)
                break

    repo.delete(doc_id)

    if doc_bank:
        invalidate_bm25_cache(bank=doc_bank)
    invalidate_bm25_cache(bank="all")

    try:
        if doc_bank:
            db.execute(sa_text("DELETE FROM query_cache WHERE bank=:bank"), {"bank": doc_bank})
            db.execute(sa_text("DELETE FROM query_cache WHERE bank='all'"))
            db.commit()
            logger.info("CACHE invalidated for bank=%s after deleting %s", doc_bank, doc_id)
    except Exception as e:
        logger.warning("Cache invalidation after delete failed: %s", e)

    try:
        invalidate_for_doc(doc_id)
    except Exception:
        pass

    return {"ok": True, "deleted_hindsight_docs": deleted_hs}


# ═══════════════════════════════════════════════════════════════════
# Route: POST /{doc_id}/reparse — re-parse and re-index
# ═══════════════════════════════════════════════════════════════════

@router.post("/{doc_id}/reparse")
async def reparse_document(doc_id: str, db: Session = Depends(get_db)):
    """Re-parse existing document: delete old vectors, re-OCR, re-index (v1 L4360-L4555)."""
    repo = DocumentRepository(db)
    meta = repo.get_meta(doc_id)
    if not meta or not meta.get("filename"):
        raise HTTPException(404, f"Document {doc_id} not found or has no filename")

    filename = meta["filename"]
    doc_title = meta.get("title", filename_to_title(filename))
    doc_category = meta.get("category", "")

    upload_dir_path = Path(settings.upload_dir).resolve()
    base_name = Path(filename).name
    file_path = upload_dir_path / base_name

    resolved = file_path.resolve()
    if not str(resolved).startswith(str(upload_dir_path)):
        raise HTTPException(400, "Invalid file path")
    if not file_path.exists():
        prefixed_path = upload_dir_path / f"{doc_id[:8]}_{base_name}"
        if prefixed_path.exists():
            file_path = prefixed_path
        else:
            backup_dir = Path(settings.data_dir) / "storage" / "backups"
            backup_plain = backup_dir / base_name
            backup_prefixed = backup_dir / f"{doc_id[:8]}_{base_name}"
            if backup_plain.exists():
                file_path = backup_plain
            elif backup_prefixed.exists():
                file_path = backup_prefixed
            else:
                raise HTTPException(
                    404,
                    f"Original file {filename} not found in uploads/ or backups/. "
                    f"Please re-upload the file to trigger MinerU parsing."
                )

    with open(file_path, "rb") as f:
        content = f.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"File too large ({len(content) // 1024 // 1024}MB), max {MAX_FILE_SIZE // 1024 // 1024}MB")

    try:
        text = await parse_document(filename, content)
        text = text.replace("\x00", "")
        text = clean_watermarks(text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        traceback.print_exc()
        logger.error("reparse_document: parse failed for %s: %s", doc_id, e)
        raise HTTPException(500, f"Reparse error: {e}")

    if not text or len(text.strip()) < 10:
        raise HTTPException(400, "Re-parsed content too short")

    try:
        db.execute(sa_text("DELETE FROM parent_chunks WHERE doc_id = :did"), {"did": doc_id})
        db.execute(sa_text("DELETE FROM documents WHERE doc_id = :did"), {"did": doc_id})
        db.commit()
        logger.info("Deleted old document metadata: %s", doc_id)
    except Exception as e:
        logger.warning("Failed to delete old metadata: %s", e)

    old_bank = meta.get("bank", "kb")
    bank_cfg = get_bank_config(old_bank) if old_bank else get_bank_config("kb")
    hs_bank = bank_cfg.get("hindsight") or "kb"
    try:
        await _hindsight_request(
            f"/v1/default/banks/{hs_bank}/documents/{doc_id}",
            "DELETE",
            timeout=30,
        )
        logger.info("Deleted old vectors: %s", doc_id)
    except Exception as e:
        logger.warning("Failed to delete old vectors (continuing): %s", e)

    profile = profile_document(text)
    doc_type = profile.get("doc_type", "generic")
    pc_chunks = []
    if doc_type in ("gb_standard", "regulation") and profile.get("confidence", 0) >= 0.3:
        pc_chunks = heading_chunk(text, profile)

    if pc_chunks:
        covered_chars = sum(len(pc["parent"]) for pc in pc_chunks)
        coverage = covered_chars / max(len(text), 1)
        if coverage < 0.60:
            pc_chunks.extend([
                {
                    "child": text[i:i + 5000],
                    "parent": text[i:i + 5000],
                    "child_index": 0,
                    "parent_index": 0,
                    "section_hint": "",
                }
                for i in range(0, len(text), 5000)
            ])

    if not pc_chunks:
        doc_type = "generic"
        pc_chunks = parent_child_chunk(text, child_size=384, parent_size=2048, overlap=80)

    new_doc_id = str(uuid.uuid4())

    parent_map = {}
    for pc in pc_chunks:
        parent_map[pc["parent_index"]] = pc["parent"]

    try:
        for idx, ptext in parent_map.items():
            db.execute(
                sa_text("INSERT OR REPLACE INTO parent_chunks (doc_id, parent_idx, parent_text) VALUES (:did, :idx, :ptext)"),
                {"did": new_doc_id, "idx": idx, "ptext": ptext}
            )
        db.commit()
        logger.info("Reparse: Saved %d parent_chunks for %s", len(parent_map), new_doc_id)
    except Exception as e:
        logger.warning("Failed to save parent_chunks: %s", e)

    memory_items = []
    for i, pc in enumerate(pc_chunks):
        child_content = pc["child"].strip()
        if not child_content:
            continue
        enhanced_content = f"[{pc['section_hint']}] {child_content}" if pc["section_hint"] else child_content
        tags = [
            f"doc:{filename}",
            f"chunk:{i + 1}/{len(pc_chunks)}",
            f"doc_id:{new_doc_id}",
            f"title:{doc_title}",
            f"bank:{old_bank}",
            f"parent_idx:{pc['parent_index']}",
            f"strategy:{doc_type}",
        ]
        if doc_category:
            tags.append(f"cat:{doc_category}")
        memory_items.append({"content": enhanced_content, "tags": tags, "type": "world"})

    retained = 0
    hindsight_error = None
    if memory_items:
        BATCH_SIZE = 20
        for batch_start in range(0, len(memory_items), BATCH_SIZE):
            batch = memory_items[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (len(memory_items) + BATCH_SIZE - 1) // BATCH_SIZE
            dyn_timeout = max(120, min(len(batch) * 15, 600))
            logger.info(
                "Reparse batch %d/%d: %d chunks -> bank=%s, timeout=%ds",
                batch_num, total_batches, len(batch), hs_bank, dyn_timeout
            )
            try:
                result = await _hindsight_request(
                    f"/v1/default/banks/{hs_bank}/memories",
                    "POST",
                    {"items": batch},
                    timeout=dyn_timeout,
                )
                batch_retained = result.get("items_count", len(batch))
                retained += batch_retained
            except Exception as e:
                hindsight_error = str(e) or repr(e)
                logger.warning("Reparse batch %d FAILED: %s", batch_num, hindsight_error)
        if retained == 0 and hindsight_error:
            raise HTTPException(502, f"Re-index failed: {hindsight_error}")
        logger.info("Reparse total: %d/%d chunks stored", retained, len(memory_items))

    content_hash = hashlib.sha256(content).hexdigest()
    repo.save(new_doc_id, doc_title, doc_category, filename, content_hash, doc_type, old_bank, hs_bank)

    db.execute(
        sa_text("UPDATE documents SET bank = :bank, hs_bank = :hs_bank WHERE doc_id = :did"),
        {"bank": old_bank, "hs_bank": hs_bank, "did": new_doc_id}
    )
    db.commit()

    asyncio.create_task(_verify_searchable(new_doc_id, doc_title, len(text), hs_bank))

    return {
        "ok": True,
        "old_doc_id": doc_id,
        "new_doc_id": new_doc_id,
        "title": doc_title,
        "chunks": retained,
        "total_chars": len(text),
        "preview": text[:200] + ("..." if len(text) > 200 else ""),
    }
