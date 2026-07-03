"""Upload endpoint — document upload, parsing, chunking, indexing.

Ported from: kb-web server.py upload() L2675-L3039
"""

import asyncio
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import SessionLocal
from app.models.document import Document, ParentChunk
from app.models.concept import Concept
from app.models.upload_task import UploadTask
from app.services.concept_gen import generate_concepts_for_doc, infer_doc_concept_id, infer_domain, _BANK_TO_DOMAIN
from app.services.confidence import update_concept_confidence
from app.repositories.document_repo import DocumentRepository
from app.repositories.vector_repo import HindsightStore
from app.services.cache_service import invalidate_bm25_cache
from scripts.kg_client import kg_index_document
from app.services.chunking import (
    heading_chunk,
    parent_child_chunk,
    excel_row_chunk,
    extract_table_chunks,
)
from app.services.parsing import parse_document
from app.services.quality import assess_quality, profile_document
from app.services.retrieval import get_bank_config, recall
from app.utils.text_cleaning import clean_pipeline, filename_to_title

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter()

MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 MB
MAX_BATCH_FILES = 200
MAX_BATCH_TOTAL_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB

# ── P0-3: bank → OKF domain 映射 (定义在 concept_gen.py，此处引用) ──
# _infer_domain 已统一到 concept_gen.infer_domain()，此处保留别名
_infer_domain = infer_domain


def _get_doc_repo(db: Session) -> DocumentRepository:
    return DocumentRepository(db)
# -- UploadTask helpers --

def _create_upload_task(task_id: str, filename: str) -> UploadTask:
    db = SessionLocal()
    try:
        task = UploadTask(id=task_id, status="pending", filename=filename, progress=0.0, stage="queued")
        db.add(task)
        db.commit()
        db.refresh(task)
        return task
    finally:
        db.close()


def _update_upload_task(task_id: str, **kwargs):
    db = SessionLocal()
    try:
        task = db.query(UploadTask).filter(UploadTask.id == task_id).first()
        if task:
            for k, v in kwargs.items():
                setattr(task, k, v)
            db.commit()
    finally:
        db.close()


def _get_upload_task(task_id: str):
    db = SessionLocal()
    try:
        return db.query(UploadTask).filter(UploadTask.id == task_id).first()
    finally:
        db.close()


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    category: str = Form(""),
    bank: str = Form("general"),
    confirm_quality: str = Form(""),
    source: str = Form("manual"),
    published_date: str = Form(None),
    geo_scope: str = Form(None),
):
    """Upload a document: parse → chunk → embed → index → cache invalidate."""
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    # ── 防御性 sanitize：选择文件夹上传时 file.filename 可能含子目录路径（如 "上岗学习/xxx.doc"），
    # 后端解析/转换/落盘逻辑均按 basename 处理，这里统一去掉路径分量，避免 tempfile.mkdtemp 后
    # open(os.path.join(tmpdir, filename)) 因子目录不存在导致 FileNotFoundError。──
    if file.filename and ("/" in file.filename or "\\" in file.filename):
        original_filename = file.filename
        sanitized = file.filename.replace("\\", "/").rsplit("/", 1)[-1]
        file.filename = sanitized
        logger.info("[upload] sanitize filename: %r -> %r", original_filename, sanitized)

    # ── bank 兼容性与验证 ──
    if bank == "kb":
        bank = "general"
        logger.info("[MIGRATE] bank='kb' → 'general'")

    if bank == "all":
        bank = "general"  # "全部"默认归入综合文件

    # 自动路由 source=xhs → xhs bank
    if source == "xhs" and bank == "general":
        bank = "xhs"
        logger.info("[xhs] source=xhs auto-routed to bank=%s", bank)

    # 解析 published_date（YYYY-MM-DD 格式）
    parsed_pub_date = None
    if published_date and isinstance(published_date, str):
        try:
            from datetime import date
            parts = published_date.split("-")
            parsed_pub_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
            logger.info("[upload] published_date=%s parsed=%s", published_date, parsed_pub_date)
        except (ValueError, IndexError) as e:
            logger.warning("[upload] cannot parse published_date=%s: %s", published_date, e)

    # -- read file --
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "file empty")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"file too large ({len(content) // 1024 // 1024}MB), max {MAX_FILE_SIZE // 1024 // 1024}MB")

    # -- async task --
    task_id = str(uuid.uuid4())
    _create_upload_task(task_id, file.filename)

    asyncio.create_task(
        _process_upload_task(
            task_id=task_id, filename=file.filename, content=content,
            title=title, category=category, bank=bank,
            source=source, published_date=published_date, geo_scope=geo_scope,
        )
    )

    return {"task_id": task_id, "status": "pending", "filename": file.filename}


async def _process_upload_task(
    task_id: str, filename: str, content: bytes,
    title: str = "", category: str = "", bank: str = "general",
    source: str = "manual", published_date: str = None, geo_scope: str = None,
):
    _update_upload_task(task_id, status="processing", stage="parsing", progress=0.05)
    parsed_pub_date = None
    if published_date and isinstance(published_date, str):
        try:
            from datetime import date
            p = published_date.split("-")
            parsed_pub_date = date(int(p[0]), int(p[1]), int(p[2]))
        except (ValueError, IndexError):
            pass
    bank_cfg = get_bank_config(bank)
    hs_bank = bank_cfg.get("hindsight") or "kb"

    try:
        text = await parse_document(filename, content)
        text = text.replace("\x00", "")
        text = clean_pipeline(text, source_hint=filename)
    except ValueError as e:
        _update_upload_task(task_id, status="failed", stage="parsing", error_message=str(e))
        return
    except Exception as e:
        logger.exception("parse error: %s", e)
        _update_upload_task(task_id, status="failed", stage="parsing", error_message=str(e))
        return

    _update_upload_task(task_id, progress=0.15, stage="quality_check")
    from app.services.quality_gates import hard_check_g1
    eff_title = (title or "").strip() or (Path(filename).stem if filename else "")
    g1 = hard_check_g1(text or "", eff_title)
    if not g1["passed"]:
        _update_upload_task(task_id, status="failed", stage="quality_gate", error_message=str(g1["issues"]))
        return
    if not text or len(text.strip()) < 10:
        _update_upload_task(task_id, status="failed", stage="quality_gate", error_message="content too short")
        return

    text_norm = text.replace("\r\n", "\n").strip()
    norm_hash = hashlib.sha256(text_norm.encode("utf-8")).hexdigest()
    db = SessionLocal()
    try:
        if db.query(Document).filter(Document.content_hash == norm_hash, Document.status == "active").first():
            _update_upload_task(task_id, status="failed", stage="duplicate_check", error_message="hash dup")
            return
    finally:
        db.close()

    quality = assess_quality(text)
    if quality["score"] < 80:
        _update_upload_task(task_id, status="failed", stage="quality_check", error_message=f"quality {quality['score']}%")
        return
    db = SessionLocal()
    try:
        if _get_doc_repo(db).get_by_hash(norm_hash):
            _update_upload_task(task_id, status="failed", stage="duplicate_check", error_message="doc dup")
            return
    finally:
        db.close()

    _update_upload_task(task_id, progress=0.25, stage="chunking")
    doc_title = title.strip() or filename_to_title(filename, text)
    doc_category = category.strip()
    profile = profile_document(text)
    doc_type = profile.get("doc_type", "generic")
    pc_chunks = []
    if doc_type in ("gb_standard", "regulation") and profile.get("confidence", 0) >= 0.3:
        pc_chunks = heading_chunk(text, profile)
    if pc_chunks:
        cov = sum(len(pc["parent"]) for pc in pc_chunks) / max(len(text), 1)
        if cov < 0.80:
            iv = []
            for pc in pc_chunks:
                s = text.find(pc["parent"][:100])
                if s >= 0:
                    iv.append((s, s + len(pc["parent"])))
            iv.sort()
            mg = []
            for s, e in iv:
                if mg and s <= mg[-1][1]:
                    mg[-1] = (mg[-1][0], max(mg[-1][1], e))
                else:
                    mg.append((s, e))
            uc = []
            prev = 0
            for s, e in mg:
                if s - prev > 500:
                    uc.append(text[prev:s])
                prev = e
            if len(text) - prev > 500:
                uc.append(text[prev:])
            uct = "\n\n".join(uc)
            if len(uct.strip()) > 500:
                gc = []
                for p in uct.split("\n\n"):
                    if p.strip():
                        gc.append({"child": p[:12000], "parent": p[:12000], "child_index": 0, "parent_index": 0, "section_hint": ""})
                if gc:
                    mp = max(pc["parent_index"] for pc in pc_chunks) + 1
                    for i, g in enumerate(gc):
                        g["parent_index"] = mp + i
                        g["child_index"] = len(pc_chunks) + i
                    pc_chunks.extend(gc)
    if not pc_chunks:
        if filename.lower().endswith((".xlsx", ".xls")):
            pc_chunks = excel_row_chunk(text, doc_title=doc_title)
            doc_type = "excel_checklist"
        else:
            doc_type = "generic"
            pc_chunks = parent_child_chunk(text, child_size=settings.default_chunk_size, parent_size=settings.default_chunk_size * 4, overlap=settings.chunk_overlap, doc_title=doc_title)
    try:
        tc = extract_table_chunks(text)
    except Exception:
        tc = []
    if tc:
        mp2 = max((pc["parent_index"] for pc in pc_chunks), default=-1) + 1
        mc2 = max((pc["child_index"] for pc in pc_chunks), default=-1) + 1
        for i, t in enumerate(tc):
            t["parent_index"] = mp2 + i
            t["child_index"] = mc2 + i
        pc_chunks.extend(tc)

    _update_upload_task(task_id, progress=0.35, stage="building_index")
    doc_id = str(uuid.uuid4())
    from app.services.version_chain import detect_existing_doc, mark_superseded
    parent_map = {pc["parent_index"]: pc["parent"] for pc in pc_chunks}
    memory_items = []
    for i, pc in enumerate(pc_chunks):
        child = pc["child"].strip()
        if not child:
            continue
        hint = (pc.get("section_hint") or "").strip()
        enhanced = f"[文档:{doc_title}]" + (f"[章节:{hint}] {child}" if hint and hint != doc_title else f" {child}")
        tags = [f"doc:{filename}", f"chunk:{i+1}/{len(pc_chunks)}", f"doc_id:{doc_id}", f"title:{doc_title}", f"bank:{bank}", f"parent_idx:{pc['parent_index']}", f"strategy:{doc_type}"]
        if doc_category:
            tags.append(f"cat:{doc_category}")
        memory_items.append({"content": enhanced, "tags": tags, "type": "world"})

    db = SessionLocal()
    try:
        dr = _get_doc_repo(db)
        dr.save(doc_id=doc_id, title=doc_title, category=doc_category, filename=filename, content_hash=norm_hash, doc_type=doc_type, bank=bank, hs_bank=hs_bank, source=source, published_date=parsed_pub_date, geo_scope=geo_scope)
        for idx, pt in parent_map.items():
            db.merge(ParentChunk(doc_id=doc_id, parent_idx=idx, parent_text=pt))
        con_id = infer_doc_concept_id(title=doc_title, bank=bank, doc_type=doc_type, text=text[:2000])
        cpl = [{"parent_index": i, "parent": pt} for i, pt in parent_map.items()]
        generate_concepts_for_doc(db, doc_id, con_id, cpl, doc_type=doc_type, confidence=profile.get("confidence", 0.5))
        dr2 = db.query(Document).filter(Document.doc_id == doc_id).first()
        if dr2:
            dr2.profile_confidence = profile.get("confidence", 0.5)
            dr2.chunk_count = len(parent_map)
            dr2.domain = _infer_domain(bank, doc_type)
            if con_id:
                dr2.concept_id = con_id
        exd = detect_existing_doc(db=db, title=doc_title, bank=bank, doc_type=doc_type, content_hash=norm_hash)
        if exd:
            mark_superseded(db, old_doc_id=exd.doc_id, new_doc_id=doc_id, reason="new_version_upload")
            if dr2:
                dr2.supersedes = exd.doc_id
        db.commit()
        try:
            for c in db.query(Concept).filter(Concept.doc_id == doc_id, Concept.status == "active").all():
                update_concept_confidence(db, c.concept_id)
            db.commit()
        except Exception:
            pass
        try:
            from app.services.quality_gates import check_document
            check_document(db, doc_id, gates="G2")
        except Exception:
            pass
        try:
            from app.services.concept_summary import generate_summary
            summaries = db.query(Concept).filter(Concept.doc_id == doc_id, Concept.status == "active", (Concept.summary.is_(None)) | (Concept.summary == "")).order_by(Concept.parent_idx).limit(3).all()
            if summaries:
                tasks = [asyncio.wait_for(generate_summary(content=s.content or "", title=s.title or ""), timeout=10) for s in summaries]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for s, r in zip(summaries, results):
                    if isinstance(r, Exception):
                        continue
                    if r:
                        s.summary = r
                db.flush()
        except Exception:
            pass
    except Exception as e:
        db.rollback()
        logger.exception("save failed: %s", e)
        _update_upload_task(task_id, status="failed", stage="save", error_message=str(e))
        return
    finally:
        db.close()

    _update_upload_task(task_id, progress=0.55, stage="hindsight_indexing")
    hindsight_error = None
    retained = 0
    if memory_items:
        hs = HindsightStore()
        tc = sum(len(m.get("content", "")) for m in memory_items)
        BS = 10 if (tc > 500000 or any(len(m.get("content", "")) > 5000 for m in memory_items)) else 20
        for bs in range(0, len(memory_items), BS):
            batch = memory_items[bs:bs + BS]
            try:
                retained += await hs.upsert(doc_id, batch, hs_bank)
            except Exception as e:
                hindsight_error = str(e) or repr(e)
        invalidate_bm25_cache(bank)
        invalidate_bm25_cache("all")

    _update_upload_task(task_id, progress=0.75, stage="verification")
    integrity = None
    if memory_items and not hindsight_error:
        try:
            await asyncio.sleep(2)
            rc = await recall(doc_title, limit=50, bank=hs_bank, max_tokens=32768)
            rt = "\n".join(r.get("text", "") for r in rc)
            if rt and len(rt) > 200:
                cov = min(100, round(len(rc) / max(len(parent_map), 1) * 100, 1))
                integrity = {"original_chars": len(text), "recalled_chars": len(rt), "coverage_pct": cov, "hindsight_chunks": len(rc), "meta_chunks": len(parent_map), "status": "ok" if cov >= 80 else ("partial" if cov >= 50 else "low")}
                if cov < 80 and retained < len(memory_items):
                    try:
                        rr = await hs.upsert(doc_id, memory_items[retained:], hs_bank)
                        if rr > 0:
                            retained += rr
                            integrity["retried"] = True
                    except Exception as e:
                        integrity["retry_failed"] = str(e)
        except Exception as e:
            logger.error("integrity fail: %s", e)

    _update_upload_task(task_id, progress=0.9, stage="finalizing")
    db = SessionLocal()
    try:
        doc = _get_doc_repo(db).get(doc_id)
        if doc:
            doc.original_text_length = len(text)
            if integrity:
                doc.coverage_pct = integrity.get("coverage_pct", 0.0)
                if integrity.get("status") == "ok":
                    doc.searchable = 1
            doc.verified_at = datetime.now(timezone.utc)
            doc.last_confirmed = datetime.now(timezone.utc)
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

    if integrity and integrity.get("status") in ("ok", "pending"):
        asyncio.create_task(_verify_searchable(doc_id, doc_title, len(text), hs_bank))
    asyncio.create_task(asyncio.to_thread(kg_index_document, doc_id, doc_title, text, bank))
    invalidate_bm25_cache(bank=bank)

    result_dict = {"ok": True, "doc_id": doc_id, "title": doc_title, "category": doc_category, "filename": filename, "chunks": retained, "total_chars": len(text), "preview": text[:200] + ("..." if len(text) > 200 else ""), "quality": {"score": quality["score"], "issues": quality["issues"], "needs_confirm": quality["score"] < 80}, "integrity": integrity, "doc_type": doc_type, "kg_indexed": True}
    _update_upload_task(task_id, status="done", progress=1.0, stage="complete", result_doc_id=doc_id, result=json.dumps(result_dict, ensure_ascii=False))
    logger.info("[upload] task %s complete: doc=%s", task_id[:8], doc_id[:8])


@router.get("/tasks/{task_id}")
async def get_upload_task(task_id: str):
    task = _get_upload_task(task_id)
    if not task:
        raise HTTPException(404, f"task {task_id} not found")
    resp = {"task_id": task.id, "status": task.status, "filename": task.filename, "progress": task.progress, "stage": task.stage, "created_at": task.created_at.isoformat() if task.created_at else None, "updated_at": task.updated_at.isoformat() if task.updated_at else None}
    if task.error_message:
        resp["error_message"] = task.error_message
    if task.result_doc_id:
        resp["doc_id"] = task.result_doc_id
    if task.result and task.status == "done":
        try:
            resp["result"] = json.loads(task.result)
        except (json.JSONDecodeError, TypeError):
            resp["result"] = task.result
    return resp


@router.post("/precheck")
async def upload_precheck(payload: dict):
    """Precheck files before upload — detect duplicates by content_hash / title / standard_number.

    Request body:
      {
        "items": [
          {"filename": "...", "sha1": "SHA256hex...", "title": "...", "bank": "standards"},
          ...
        ]
      }

    Note: `sha1` field is actually SHA-256 (hashed with crypto.subtle.digest('SHA-256')),
    matching the backend's `content_hash` (hashlib.sha256).

    Response:
      {
        "results": [
          {
            "filename": "...",
            "status": "new" | "dup_hash" | "dup_title" | "dup_standard",
            "existing_doc_id": "..." (only when dup),
            "existing_title": "..." (only when dup),
            "reason": "..."  (human-readable Chinese)
          },
          ...
        ],
        "summary": {"new": N, "dup_hash": N, "dup_title": N, "dup_standard": N}
      }
    """
    from app.services.version_chain import _extract_standard_number

    items = payload.get("items") or []
    if not isinstance(items, list):
        raise HTTPException(400, "items must be a list")
    if len(items) > MAX_BATCH_FILES:
        raise HTTPException(400, f"单次最多预检 {MAX_BATCH_FILES} 个文件")

    db = SessionLocal()
    results = []
    summary = {"new": 0, "dup_hash": 0, "dup_title": 0, "dup_standard": 0}

    try:
        # 预加载活跃文档的 hash / title / 标准号索引（O(N) 一次扫描，N≈148）
        active_docs = db.query(Document).filter(Document.status == "active").all()
        hash_map: dict[str, Document] = {}
        title_map: dict[tuple[str, str], Document] = {}
        std_map: dict[tuple[str, str], Document] = {}
        for d in active_docs:
            d_hash = getattr(d, "content_hash", "") or ""
            d_title = getattr(d, "title", "") or ""
            d_bank = getattr(d, "bank", "") or ""
            if d_hash:
                hash_map[str(d_hash)] = d
            if d_title and d_bank:
                title_map[(str(d_bank), str(d_title))] = d
            if d_title:
                std = _extract_standard_number(str(d_title))
                if std and d_bank:
                    std_map[(str(d_bank), std)] = d

        for it in items:
            fname = (it.get("filename") or "").strip()
            sha1 = (it.get("sha1") or "").strip().lower()
            title = (it.get("title") or "").strip() or filename_to_title(fname)
            bank = (it.get("bank") or "general").strip()

            entry = {"filename": fname, "title": title}

            # L1: content_hash 精确匹配
            if sha1 and sha1 in hash_map:
                d = hash_map[sha1]
                entry.update({
                    "status": "dup_hash",
                    "existing_doc_id": d.doc_id,
                    "existing_title": d.title,
                    "reason": "文件内容已存在（hash 完全相同）",
                })
                summary["dup_hash"] += 1
                results.append(entry)
                continue

            # L2: 同 bank + 同标准号
            std = _extract_standard_number(title)
            if std and (bank, std) in std_map:
                d = std_map[(bank, std)]
                entry.update({
                    "status": "dup_standard",
                    "existing_doc_id": d.doc_id,
                    "existing_title": d.title,
                    "reason": f"同标准号已存在: {std}",
                })
                summary["dup_standard"] += 1
                results.append(entry)
                continue

            # L3: 同 bank + 同标题
            if title and (bank, title) in title_map:
                d = title_map[(bank, title)]
                entry.update({
                    "status": "dup_title",
                    "existing_doc_id": d.doc_id,
                    "existing_title": d.title,
                    "reason": "同知识库下已存在同名文档",
                })
                summary["dup_title"] += 1
                results.append(entry)
                continue

            entry.update({"status": "new", "reason": "未发现重复"})
            summary["new"] += 1
            results.append(entry)
    finally:
        db.close()

    return {"results": results, "summary": summary}


@router.post("/batch")
async def upload_batch(
    files: Optional[List[UploadFile]] = File(default=None),
    title_prefix: str = Form(""),
    category: str = Form(""),
    bank: str = Form("general"),
    confirm_quality: str = Form(""),
    source: str = Form("manual"),
):
    """Batch upload: receive multiple files and process them serially.

    Returns a summary with per-file results.  Any single-file failure does
    not abort the remaining files.
    """
    if not files:
        raise HTTPException(400, "至少需要上传一个文件")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(400, f"单次最多上传 {MAX_BATCH_FILES} 个文件")

    total_size = 0
    for f in files:
        try:
            size = getattr(f, "size", None)
            if size is None:
                current = f.file.tell()
                f.file.seek(0, os.SEEK_END)
                size = f.file.tell()
                f.file.seek(current)
            total_size += int(size or 0)
        except Exception:
            logger.debug("Unable to determine size for batch file %s", f.filename)
    if total_size > MAX_BATCH_TOTAL_SIZE:
        raise HTTPException(
            400,
            f"批量文件总大小过大（{total_size // 1024 // 1024}MB），上限 {MAX_BATCH_TOTAL_SIZE // 1024 // 1024}MB",
        )

    results: list = []
    success_count = 0
    failed_count = 0

    for f in files:
        try:
            f.file.seek(0)
            f_content = await f.read()
            if not f_content:
                failed_count += 1
                results.append({"filename": f.filename, "ok": False, "detail": "文件为空"})
                continue
            task_id = str(uuid.uuid4())
            _create_upload_task(task_id, f.filename)
            asyncio.create_task(
                _process_upload_task(
                    task_id=task_id, filename=f.filename, content=f_content,
                    title=title_prefix, category=category, bank=bank,
                    source=source, published_date=None, geo_scope=None,
                )
            )
            success_count += 1
            results.append({"filename": f.filename, "ok": True, "task_id": task_id, "status": "pending"})
        except HTTPException as e:
            failed_count += 1
            results.append({
                "filename": f.filename,
                "ok": False,
                "detail": e.detail,
                "status_code": e.status_code,
            })
        except Exception as e:
            logger.exception("Batch upload failed for %s: %s", f.filename, e)
            failed_count += 1
            results.append({
                "filename": f.filename,
                "ok": False,
                "detail": "服务器内部错误",
                "status_code": 500,
            })

    return {
        "ok": success_count > 0,
        "total": len(files),
        "success": success_count,
        "failed": failed_count,
        "results": results,
    }


async def _verify_searchable(doc_id: str, doc_title: str, text_len: int, hs_bank: str):
    """异步验证：等 consolidation 后用标题做 recall，确认文档可被搜索"""
    try:
        await asyncio.sleep(60)  # 等待 Hindsight consolidation
        recalled = await recall(doc_title[:50], limit=5, bank=hs_bank)
        found = False
        for r in recalled:
            for t in r.get("tags", []):
                if t.startswith("doc_id:") and t[7:] == doc_id:
                    found = True
                    break
            if found:
                break
        if found:
            logger.info("[VERIFY] doc %s searchable ✓", doc_id[:8])
        else:
            logger.warning("[VERIFY] doc %s NOT found after 60s", doc_id[:8])
    except Exception as e:
        logger.warning("[VERIFY] doc %s check failed: %s", doc_id[:8], e)
