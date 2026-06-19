"""Upload endpoint — document upload, parsing, chunking, indexing.

Ported from: kb-web server.py upload() L2675-L3039
"""

import asyncio
import hashlib
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
from app.models.document import ParentChunk
from app.repositories.document_repo import DocumentRepository
from app.repositories.vector_repo import HindsightStore
from app.services.cache_service import invalidate_bm25_cache
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

router = APIRouter()

MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 MB
MAX_BATCH_FILES = 20
MAX_BATCH_TOTAL_SIZE = 500 * 1024 * 1024  # 500 MB


def _get_doc_repo(db: Session) -> DocumentRepository:
    return DocumentRepository(db)


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    category: str = Form(""),
    bank: str = Form("general"),
    confirm_quality: str = Form(""),
    source: str = Form("manual"),
):
    """Upload a document: parse → chunk → embed → index → cache invalidate."""
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    # ── bank 兼容性与验证 ──
    if bank == "kb":
        bank = "general"
        logger.info("[MIGRATE] bank='kb' → 'general'")

    if bank == "all":
        bank = "general"  # "全部"默认归入综合文件

    bank_cfg = get_bank_config(bank)
    hs_bank = bank_cfg.get("hindsight") or "kb"

    # ── 读取文件内容 ──
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "文件为空")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"文件过大（{len(content) // 1024 // 1024}MB），上限 {MAX_FILE_SIZE // 1024 // 1024}MB")

    # ── 文档解析 ──
    try:
        text = await parse_document(file.filename, content)
        text = text.replace("\x00", "")  # PostgreSQL UTF8 不接受 0x00
        text = clean_pipeline(text, source_hint=file.filename)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("文档解析异常: %s", e)
        raise HTTPException(500, f"文档解析异常: {e}")

    if not text or len(text.strip()) < 10:
        raise HTTPException(400, "文档内容过短")

    # ── 质量评估 ──
    quality = assess_quality(text)
    if quality["score"] < 80 and confirm_quality != "true":
        return {
            "ok": False,
            "detail": f"文档解析质量较低（{quality['score']}%），可能存在乱码。建议检查后重新上传或使用 MinerU 解析。",
            "quality": {
                "score": quality["score"],
                "issues": quality["issues"],
                "needs_confirm": True,
            },
        }

    # ── 去重检测：按文件内容 SHA256 查重 ──
    content_hash = hashlib.sha256(content).hexdigest()
    db = SessionLocal()
    try:
        doc_repo = _get_doc_repo(db)
        existing = doc_repo.get_by_hash(content_hash)
        if existing:
            raise HTTPException(
                409,
                f"文档已存在（内容完全一致）。\n"
                f"已有文档：{existing.title}（{existing.filename}）\n"
                f"上传时间：{existing.created_at}\n"
                f"文档ID：{existing.doc_id}",
            )
    finally:
        db.close()

    # ── 标题：用户指定 > 内容第一行#标题 > 文件名去扩展名 ──
    doc_title = title.strip() or filename_to_title(file.filename, text)
    doc_category = category.strip()

    # ── Adaptive chunking: profile document first ──
    profile = profile_document(text)
    doc_type = profile.get("doc_type", "generic")
    logger.info(
        "Document profile: type=%s, confidence=%.2f, headings=%d",
        doc_type, profile.get("confidence", 0), len(profile.get("headings", [])),
    )

    pc_chunks = []
    if doc_type in ("gb_standard", "regulation") and profile.get("confidence", 0) >= 0.3:
        pc_chunks = heading_chunk(text, profile)

    # ── 覆盖率检测：heading-based分块可能遗漏大量文本 ──
    if pc_chunks:
        covered_chars = sum(len(pc["parent"]) for pc in pc_chunks)
        coverage = covered_chars / max(len(text), 1)
        logger.info("Heading chunking: %d chunks, coverage=%.1f%%", len(pc_chunks), coverage * 100)

        if coverage < 0.80:
            # 找出heading未覆盖的文本区域，用generic补齐
            covered_intervals = []
            for pc in pc_chunks:
                start = text.find(pc["parent"][:100])
                if start >= 0:
                    covered_intervals.append((start, start + len(pc["parent"])))
            covered_intervals.sort()

            # 合并重叠区间
            merged = []
            for s, e in covered_intervals:
                if merged and s <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], e))
                else:
                    merged.append((s, e))

            # 提取未覆盖区间（跳过太小的gap < 500字符）
            uncovered_segments = []
            prev_end = 0
            for s, e in merged:
                if s - prev_end > 500:
                    uncovered_segments.append(text[prev_end:s])
                prev_end = e
            if len(text) - prev_end > 500:
                uncovered_segments.append(text[prev_end:])

            # 对未覆盖段落做分块
            uncovered_text = "\n\n".join(uncovered_segments)
            if len(uncovered_text.strip()) > 500:
                GAP_PARENT = 5000
                gap_chunks = []
                paras = uncovered_text.split("\n\n")
                buf = ""
                for p in paras:
                    if len(buf) + len(p) + 2 > GAP_PARENT and buf:
                        gap_chunks.append({
                            "child": buf, "parent": buf,
                            "child_index": 0, "parent_index": 0, "section_hint": "",
                        })
                        buf = p
                    else:
                        buf = (buf + "\n\n" + p).strip() if buf else p
                if buf.strip():
                    gap_chunks.append({
                        "child": buf, "parent": buf,
                        "child_index": 0, "parent_index": 0, "section_hint": "",
                    })

                # 合并：heading chunks在前，fallback chunks在后
                max_parent = max(pc["parent_index"] for pc in pc_chunks) + 1
                for i, gc in enumerate(gap_chunks):
                    gc["parent_index"] = max_parent + i
                    gc["child_index"] = len(pc_chunks) + i
                    gc["section_hint"] = "[补充覆盖] " + gc["parent"][:80]
                pc_chunks.extend(gap_chunks)
                logger.info("  Fallback: +%d chunks (5K/块), total=%d", len(gap_chunks), len(pc_chunks))

    if not pc_chunks:
        # Excel 检查表走专用分块逻辑
        if file.filename and file.filename.lower().endswith(('.xlsx', '.xls')):
            pc_chunks = excel_row_chunk(text, doc_title=doc_title)
            doc_type = "excel_checklist"
            logger.info("Excel row-based chunking: %d chunks", len(pc_chunks))
        else:
            doc_type = "generic"
            pc_chunks = parent_child_chunk(
                text,
                child_size=settings.default_chunk_size,
                parent_size=settings.default_chunk_size * 4,
                overlap=settings.chunk_overlap,
                doc_title=doc_title,
            )
            logger.info("Paragraph-based chunking: %d chunks", len(pc_chunks))

    # 提取表格为独立chunks
    table_chunks = extract_table_chunks(text)
    if table_chunks:
        max_parent = max((pc["parent_index"] for pc in pc_chunks), default=-1) + 1
        max_child = max((pc["child_index"] for pc in pc_chunks), default=-1) + 1
        for idx, tc in enumerate(table_chunks):
            tc["parent_index"] = max_parent + idx
            tc["child_index"] = max_child + idx
        pc_chunks.extend(table_chunks)
        logger.info("Table extraction: +%d table chunks, total=%d", len(table_chunks), len(pc_chunks))

    doc_id = str(uuid.uuid4())

    # 构建 parent 映射
    parent_map = {}
    for pc in pc_chunks:
        parent_map[pc["parent_index"]] = pc["parent"]

    memory_items = []
    for i, pc in enumerate(pc_chunks):
        child_content = pc["child"].strip()
        if not child_content:
            continue
        enhanced_content = f"[{pc['section_hint']}] {child_content}" if pc["section_hint"] else child_content

        tags = [
            f"doc:{file.filename}",
            f"chunk:{i + 1}/{len(pc_chunks)}",
            f"doc_id:{doc_id}",
            f"title:{doc_title}",
            f"bank:{bank}",
            f"parent_idx:{pc['parent_index']}",
            f"strategy:{doc_type}",
        ]
        if doc_category:
            tags.append(f"cat:{doc_category}")
        memory_items.append({"content": enhanced_content, "tags": tags, "type": "world"})

    # ── 保存本地数据（不依赖Hindsight）──
    db = SessionLocal()
    try:
        doc_repo = _get_doc_repo(db)
        doc_repo.save(
            doc_id=doc_id,
            title=doc_title,
            category=doc_category,
            filename=file.filename,
            content_hash=content_hash,
            doc_type=doc_type,
            bank=bank,
            hs_bank=hs_bank,
        )
        # 保存 parent_chunks
        for idx, ptext in parent_map.items():
            pc = ParentChunk(doc_id=doc_id, parent_idx=idx, parent_text=ptext)
            db.merge(pc)
        db.commit()
        logger.info("Saved %d parent chunks for doc %s", len(parent_map), doc_id)
    except Exception as e:
        logger.warning("Failed to save parent_chunks for %s: %s", doc_id, e)
    finally:
        db.close()

    # ── 保存原件到 uploads/ 和 backups/ 目录 ──
    backup_name = Path(file.filename or "unknown.pdf").name
    backup_name = f"{doc_id[:8]}_{backup_name}"
    for save_dir in [settings.upload_dir, Path("./data/storage/backups")]:
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, backup_name)
        try:
            with open(save_path, "wb") as bf:
                bf.write(content)
        except Exception as e:
            logger.warning("Failed to save %s to %s: %s", backup_name, save_dir, e)

    # ── 上传到Hindsight（分批写入）──
    retained = 0
    hindsight_error = None
    hs = HindsightStore()
    if memory_items:
        BATCH_SIZE = 20
        for batch_start in range(0, len(memory_items), BATCH_SIZE):
            batch = memory_items[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (len(memory_items) + BATCH_SIZE - 1) // BATCH_SIZE
            logger.info(
                "Upload batch %d/%d: %d chunks → bank=%s",
                batch_num, total_batches, len(batch), hs_bank,
            )
            try:
                result = await hs.upsert(doc_id, batch, hs_bank)
                batch_retained = result
                retained += batch_retained
                logger.info("  Batch %d: stored %d/%d", batch_num, batch_retained, len(batch))
            except Exception as e:
                hindsight_error = str(e) or repr(e)
                logger.error("  Batch %d FAILED: %s", batch_num, hindsight_error)

        logger.info("Hindsight total: %d/%d chunks stored for doc %s", retained, len(memory_items), doc_id)

        # 上传成功后立即失效BM25缓存
        invalidate_bm25_cache(bank)
        invalidate_bm25_cache("all")

        if retained == 0 and hindsight_error:
            logger.error("Hindsight write ALL FAILED (local data preserved): %s", hindsight_error)

    # ── 更新 bank 到数据库 ──
    db = SessionLocal()
    try:
        from sqlalchemy import text as sa_text
        db.execute(sa_text("UPDATE documents SET bank = :bank WHERE doc_id = :doc_id"), {"bank": bank, "doc_id": doc_id})
        db.commit()
    finally:
        db.close()

    # ── 完整性验证：上传后召回比对 ──
    integrity = None
    hindsight_chunks_count = 0
    meta_chunks_count = len(parent_map)
    retried = False
    try:
        await asyncio.sleep(2)  # 等待 Hindsight 索引
        recalled_chunks = await recall(doc_title, limit=50, bank=hs_bank, max_tokens=32768)
        recalled_text = "\n".join(r.get("text", "") for r in recalled_chunks)
        hindsight_chunks_count = len(recalled_chunks)
        if recalled_text and len(recalled_text) > 200:
            coverage = min(100, round(hindsight_chunks_count / max(meta_chunks_count, 1) * 100, 1))
            integrity = {
                "original_chars": len(text),
                "recalled_chars": len(recalled_text),
                "coverage_pct": coverage,
                "hindsight_chunks": hindsight_chunks_count,
                "meta_chunks": meta_chunks_count,
                "status": "ok" if coverage >= 80 else ("partial" if coverage >= 50 else "low"),
            }
            # P2: 自动重试 - 当coverage低于80%时，重新发送缺失的chunks
            if coverage < 80 and retained < len(memory_items):
                logger.info("Coverage low (%d%%), retrying missing chunks...", coverage)
                missing_items = memory_items[retained:]
                try:
                    retry_result = await hs.upsert(doc_id, missing_items, hs_bank)
                    retry_retained = retry_result
                    if retry_retained > 0:
                        retried = True
                        retained += retry_retained
                        integrity["retried"] = True
                        integrity["retry_chunks"] = retry_retained
                        logger.info("Retry success: +%d chunks", retry_retained)
                except Exception as e:
                    logger.error("Retry failed: %s", e)
                    integrity["retry_failed"] = str(e)
        else:
            integrity = {
                "original_chars": len(text),
                "recalled_chars": len(recalled_text) if recalled_text else 0,
                "coverage_pct": 0,
                "hindsight_chunks": hindsight_chunks_count,
                "meta_chunks": meta_chunks_count,
                "status": "pending",
                "note": "索引尚未完成，请稍后查看",
            }
    except Exception as e:
        logger.error("Upload integrity check failed for %s: %s", doc_id, e)

    # ── 更新元数据到数据库 ──
    db = SessionLocal()
    try:
        doc_repo = _get_doc_repo(db)
        doc = doc_repo.get(doc_id)
        if doc:
            doc.original_text_length = len(text)
            if integrity:
                doc.coverage_pct = integrity.get("coverage_pct", 0.0)
                if integrity.get("status") == "ok":
                    doc.searchable = 1
            doc.verified_at = datetime.now(timezone.utc)
            db.commit()
            logger.info("Updated metadata for %s: searchable=%s, coverage=%.1f%%", doc_id[:8], doc.searchable, doc.coverage_pct)
    except Exception as e:
        db.rollback()
        logger.warning("Failed to update metadata for %s: %s", doc_id[:8], e)
    finally:
        db.close()

    # ── 异步验证：等 consolidation 后用标题做 recall，确认文档可被搜索 ──
    if integrity and integrity.get("status") in ("ok", "pending"):
        asyncio.create_task(_verify_searchable(doc_id, doc_title, len(text), hs_bank))

    # ── KG 索引：异步写入知识图谱 ──
    try:
        from scripts.kg_client import kg_index_document
        asyncio.create_task(asyncio.to_thread(kg_index_document, doc_id, doc_title, text, bank))
    except Exception as e:
        logger.warning("KG index task skipped: %s", e)

    # ── 上传成功后清除该 bank 的 BM25 缓存 ──
    invalidate_bm25_cache(bank=bank)

    # ── 上传成功后清除该 bank 的查询缓存 ──
    try:
        cdb = SessionLocal()
        from sqlalchemy import text as sa_text
        deleted = cdb.execute(sa_text("DELETE FROM query_cache WHERE bank=:bank"), {"bank": bank}).rowcount
        deleted_all = cdb.execute(sa_text("DELETE FROM query_cache WHERE bank='all'")).rowcount
        cdb.commit()
        cdb.close()
        if deleted + deleted_all > 0:
            logger.info("[CACHE] Invalidated %d bank-specific + %d all-bank cache entries after upload to %s",
                        deleted, deleted_all, bank)
    except Exception as e:
        logger.warning("Cache invalidation failed: %s", e)

    return {
        "ok": True,
        "doc_id": doc_id,
        "title": doc_title,
        "category": doc_category,
        "filename": file.filename,
        "chunks": retained,
        "total_chars": len(text),
        "preview": text[:200] + ("..." if len(text) > 200 else ""),
        "warning": f"仅成功入库 {retained}/{len(memory_items)} 个文本片段" if retained < len(memory_items) else None,
        "quality": {
            "score": quality["score"],
            "issues": quality["issues"],
            "needs_confirm": quality["score"] < 80,
        },
        "integrity": integrity,
        "doc_type": doc_type,
        "kg_indexed": True,
    }


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
            result = await upload_document(
                file=f,
                title=title_prefix,
                category=category,
                bank=bank,
                confirm_quality=confirm_quality,
                source=source,
            )
            if result.get("ok"):
                success_count += 1
                results.append({
                    "filename": f.filename,
                    "ok": True,
                    "doc_id": result.get("doc_id"),
                    "title": result.get("title"),
                    "chunks": result.get("chunks"),
                    "quality": result.get("quality"),
                })
            else:
                # quality gate returned ok=False (not an exception)
                failed_count += 1
                results.append({
                    "filename": f.filename,
                    "ok": False,
                    "detail": result.get("detail", "质量评估未通过"),
                    "quality": result.get("quality"),
                })
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
