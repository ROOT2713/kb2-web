"""Query endpoint — search + LLM answer generation.

Ported from: kb-web server.py query() L3043-L3692,
             web_search() L3695-L3720, web_search_api() L3723-L3788

Architecture:
  - query()         → main entry point orchestrating the pipeline
  - _build_search_context() → recall + BM25 + RRF + rerank
  - _generate_answer()      → LLM generation with prompt
  - _web_search()           → AnySearch CLI wrapper
  - web_search_api()        → /api/web-search endpoint
"""
from app.api.query_engine import (
    _build_search_context,
    _generate_answer,
    _assess_recall_confidence,
    _write_audit_log,
    _extract_high_signal_terms,
    _is_summary_doc,
    _sort_by_confidence,
    _sort_by_freshness,
    _clean_source_text,
    _extract_standard_base_and_year,
    _normalize_doc_title_for_standard,
    _normalize_standard_keyword,
    _keyword_suggestion_rules,
    _assemble_standard_contents_meta,
    _build_follow_up_questions,
    _extract_standard_hints_from_sources,
    _merge_persistent_suggestions,
    _build_persistent_suggestions,
    _suggestions_for_answer,
    _generate_query_suggestions,
    _STD_VERSION_PATTERN,
    _STD_PATTERN,
    _REJECT_MSG_KNOWLEDGE_GAP,
    _REJECT_MSG_LOW_COVERAGE,
)

import asyncio
import html as _html_mod
import logging
import json
import os
import re
import uuid
from collections import defaultdict

from fastapi import APIRouter, Form, HTTPException, Request
from sqlalchemy import text as sa_text

from app.models.database import SessionLocal
from app.services.session_manager import (
    get_session as session_get,
    create_or_update_session as session_update,
    release_session as session_release,
)
from app.middleware.jwt_auth import get_username_from_token
from app.models.audit import AuditLog
from app.services.standard_boost import extract_standard_numbers
from app.services.cache_service import (
    get_exact as cache_get_exact,
    get_semantic as cache_get_semantic,
    set_cache as cache_set,
    clear_all_cache,
)
from app.services.generation import chat, logic_validate
from app.services.retrieval import (
    BANKS,
    _get_active_hindsight_banks,
    _find_rate_table_snippet,
    apply_tiebreaker_sort,
    bm25_search,
    build_bm25_index,
    expand_query_synonyms,
    keyword_rerank,
    llm_rerank,
    cross_encoder_rerank,
    get_bank_config,
    recall,
    rrf_merge,
)
from app.utils.text_cleaning import (
    deai_postprocess,
    expand_amount_tiers,
    normalize_standard_numbers,
)
from app.utils.tokenizer import expand_keywords, extract_keyword_snippet

from app.config import settings

from app.services.fee_utils import (
    find_fee_relevant_chunks,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    _sh = logging.StreamHandler()
    _sh.setLevel(logging.INFO)
    _sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_sh)

router = APIRouter()

@router.post("")
async def query(
    request: Request,
    q: str = Form(...),
    bank: str = Form("all"),
    history: str = Form(""),
    rerank: str = Form("false"),
    rerank_mode: str = Form("default"),
    nocache: str = Form(""),
    session_id: str = Form(""),
    categories: str = Form(""),
):
    """搜索知识库 → 召回 → DeepSeek 合成答案（支持多 bank）"""
    if not q.strip():
        raise HTTPException(400, "问题不能为空")

    # bank 白名单校验
    if bank not in BANKS:
        valid = list(BANKS.keys())
        raise HTTPException(400, f"未知 bank '{bank}'，可选: {valid}")

    # ── 多轮域锁定：获取会话状态 ──
    session_doc_ids = None
    session_bank = None
    _user_supplied_session = bool(session_id)
    if session_id:
        session_state = session_get(session_id)
        if session_state:
            session_doc_ids = session_state["doc_ids"]
            session_bank = session_state["bank"]
            logger.info(
                "[SESSION] Locked session %s: %d doc_ids, bank=%s",
                session_id[:8], len(session_doc_ids), session_bank,
            )
        else:
            logger.info("[SESSION] Unknown/expired session %s, creating new", session_id[:8])
            session_id = ""  # reset so a new one is created below
    else:
        session_id = uuid.uuid4().hex[:12]  # generate new short session ID
        logger.info("[SESSION] New session %s", session_id[:8])

    # 多轮检测：用户提供了有效 session 或者历史记录非空 → 多轮查询
    _is_multi_turn = bool(session_id) or bool(history)

    # ── 审计日志跟踪变量 ──
    cache_hit = 0
    reject = None
    _t_start = 0.0

    # T6: 标准号规范化
    q = normalize_standard_numbers(q)

    # ── 缓存命中检查（L1精确 + L2语义）──
    if not nocache:
        try:
            cached = cache_get_exact(q, bank)
            if cached:
                # 写入审计日志（缓存命中路径）
                _write_audit_log(request, q, cached["answer"], cached.get("sources", []), cache_hit=1)
                logger.info("[CACHE] L1 exact hit for: %s", q[:50])
                cache_hit = 1
                return {
                    "answer": cached["answer"],
                    "sources": cached["sources"],
                    "cache_hit": "exact",
                    "session_id": session_id,
                    "suggestions": _build_persistent_suggestions(q, cached["sources"]),
                }
            cached = await cache_get_semantic(q, bank)
            if cached:
                # 写入审计日志（缓存命中路径）
                _write_audit_log(request, q, cached["answer"], cached.get("sources", []), cache_hit=1)
                logger.info("[CACHE] L2 semantic hit for: %s", q[:50])
                return {
                    "answer": cached["answer"],
                    "sources": cached["sources"],
                    "cache_hit": "semantic",
                    "similarity": cached.get("similarity"),
                    "session_id": session_id,
                    "suggestions": _build_persistent_suggestions(q, cached["sources"]),
                }
        except Exception as e:
            logger.info("[CACHE] Lookup error: %s", e)

    bank_cfg = get_bank_config(bank)
    bank_prompt = bank_cfg["prompt"]
    hs_bank = bank_cfg.get("hindsight") or "kb"

    # ── 查询扩展 ──
    q_recalled = expand_query_synonyms(q)
    if q_recalled != q:
        logger.info("[D8] 同义词扩展: '%s' → '%s'", q[:40], q_recalled[:60])
    else:
        q_recalled = q

    # D9: 多轮锚词注入 — 从 history 提取标准号/文号追加到 recall query
    # Guard: 只对短至中等查询（<50字）注入；对非常长的自我描述查询跳过
    if history and len(q) < 50:
        _hist_terms = extract_standard_numbers(history)
        if _hist_terms:
            # 避免冗余：如果当前查询已包含提取出的标准号，跳过
            _q_lower = q.lower()
            _new_terms = [t for t in sorted(set(_hist_terms)) if t.lower() not in _q_lower]
            if _new_terms:
                _hist_q = q_recalled + " " + " ".join(_new_terms)
                logger.info("[D9] 多轮锚词注入: '%s' + %s", q_recalled[:40], _new_terms)
                q_recalled = _hist_q

    # T7: 金额档位扩展 — 只用于BM25召回
    q_bm25 = expand_amount_tiers(q_recalled)
    if q_bm25 != q_recalled:
        logger.info("[T7] 金额档位扩展(BM25): '%s' → '%s'", q_recalled[:40], q_bm25[:60])
        _tier_extra = q_bm25[len(q_recalled):].strip().split()
    else:
        q_bm25 = q_recalled
        _tier_extra = []

    # ── KG 预检索 ──
    kg_info = {"matched_entities": [], "suggested_doc_ids": [], "disambiguated": False}
    try:
        from scripts.kg_client import kg_disambiguate
        kg_info = await asyncio.to_thread(kg_disambiguate, q)
        if kg_info.get("disambiguated"):
            logger.info(
                "[KG] Disambiguated '%s': %s",
                q, [e['name'] for e in kg_info['matched_entities']],
            )
    except Exception as e:
        logger.warning("KG disambiguate skipped: %s", e)

    # ── 提取查询关键词 ──
    import jieba as _jieba_mod
    # [FIX] q 在 FastAPI Form 中被误解码为 Latin-1（UTF-8字节→Latin-1字符），jira 分词需正确 Unicode
    _q_for_kw = q_recalled
    if len(_q_for_kw) > 0 and max(ord(c) for c in _q_for_kw[:10]) > 127:
        try:
            _q_for_kw = q_recalled.encode('latin-1').decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError, LookupError):
            pass
    query_keywords_raw = [w for w in _jieba_mod.cut(_q_for_kw) if len(w.strip()) > 1]
    query_keywords = expand_keywords(query_keywords_raw)
    if _tier_extra:
        query_keywords = list(set(query_keywords + _tier_extra))

    # ── 确定是否使用 rerank ──
    use_rerank = rerank.lower() == "true" or (bank == "checklist")

    # ── 确定 rerank_mode ──
    valid_modes = {"default", "multidim", "confidence", "freshness", "cross_encoder"}
    use_rerank_mode = rerank_mode if rerank_mode in valid_modes else "default"

    # ── Phase 1: 构建搜索上下文 ──
    ctx = await _build_search_context(
        q=q, bank=bank, history=history,
        use_rerank=use_rerank, rerank_mode=use_rerank_mode, hs_bank=hs_bank,
        q_recalled=q_recalled, q_bm25=q_bm25,
        query_keywords=query_keywords, _tier_extra=_tier_extra,
        kg_info=kg_info,
        session_doc_ids=session_doc_ids,
        categories=categories,
    )
    # ── 会话域锁定：更新文档ID白名单 ──
    # 将本次查询的 doc_facts 中的文档ID写入会话状态
    # 首次查询创建白名单，后续查询在此基础上追加
    if ctx.get("doc_facts") and session_id:
        session_doc_ids_from_ctx = set(ctx["doc_facts"].keys())
        if session_doc_ids_from_ctx:
            if session_doc_ids is None:
                # 首轮查询：锁 top-15 最相关文档（按 doc_facts 中 chunk 数排序）
                doc_chunk_counts = {doc_id: len(chunks) for doc_id, chunks in ctx["doc_facts"].items()}
                top_docs = set(sorted(doc_chunk_counts, key=doc_chunk_counts.get, reverse=True)[:15])
                session_update(session_id, top_docs, bank)
                session_doc_ids = top_docs
                logger.info(
                    "[SESSION] Initialized session %s with %d doc_ids (top-15 by chunk count)",
                    session_id[:8], len(session_doc_ids),
                )
            else:
                # 多轮查询：合并新旧 doc_ids，限制在 cap 以内
                MAX_SESSION_DOCS = 15
                merged = session_doc_ids | session_doc_ids_from_ctx
                if len(merged) > MAX_SESSION_DOCS:
                    # 优先保留当前轮次文档，再从旧文档按 chunk 排序补充
                    doc_chunk_counts = {doc_id: len(ctx["doc_facts"].get(doc_id, [])) for doc_id in session_doc_ids_from_ctx}
                    # 当前轮次文档
                    kept = set(session_doc_ids_from_ctx)
                    # 按 chunk 数排序旧文档
                    old_sorted = sorted(
                        [d for d in session_doc_ids if d not in kept],
                        key=lambda d: doc_chunk_counts.get(d, 0) if d in doc_chunk_counts else len(ctx.get("doc_facts", {}).get(d, [])),
                        reverse=True,
                    )
                    for d in old_sorted:
                        if len(kept) >= MAX_SESSION_DOCS:
                            break
                        kept.add(d)
                    merged = kept
                session_update(session_id, merged, bank)
                session_doc_ids = merged
                logger.info(
                    "[SESSION] Updated session %s: merged %d + %d = %d doc_ids (capped at %d)",
                    session_id[:8], len(session_doc_ids - session_doc_ids_from_ctx),
                    len(session_doc_ids_from_ctx), len(merged), MAX_SESSION_DOCS,
                )

    # ── Phase C1: Standard Number Exact Match Boost ──
    # Detect standard numbers in query (GB/T 22239, JJF 1059.1, etc.) and force-inject
    # matched DB docs into doc_facts. Fixes recall=0 cases where doc exists in DB
    # but Hindsight ranking pushes it out of top-5.
    try:
        from app.services.standard_boost import boost_exact_standards
        boost_db = SessionLocal()
        try:
            boost_stats = boost_exact_standards(
                boost_db, q, ctx["doc_facts"], ctx["title_map"], bank=bank,
            )
            if boost_stats["docs_injected"]:
                logger.info(
                    "[C1-StdBoost] Injected %d docs (%d chunks) for %d std numbers",
                    boost_stats["docs_injected"], boost_stats["chunks_injected"],
                    boost_stats["std_nums_detected"],
                )
        finally:
            boost_db.close()
    except Exception as e:
        logger.warning("[C1-StdBoost] Skipped due to error: %s", e)

    # ── Phase B #5: KG Traversal — 沿 KG 边做 2-hop BFS 拉取关联 concept ──
    kg_context_list = []
    kg_context_text = ""
    if ctx.get("doc_facts"):
        seed_doc_ids = list(ctx["doc_facts"].keys())[:5]  # top-5 docs as seeds
        try:
            graph_db = SessionLocal()
            from app.services.graph_traversal import get_kg_context_for_query
            kg_context_list, kg_context_text = get_kg_context_for_query(
                graph_db,
                seed_doc_ids,
                max_depth=2,
                max_nodes=10,
                max_chars=3000,
            )
            graph_db.close()
            if kg_context_list:
                logger.info(
                    "[KG-Traversal] Found %d related nodes from %d seed docs",
                    len(kg_context_list), len(seed_doc_ids),
                )
        except Exception as e:
            logger.warning("KG traversal failed: %s", e)

    # ── Confidence Gate (L1+L2): 召回置信度评估 — 三级门控 ──
    reject = _assess_recall_confidence(ctx, q, query_keywords, session_doc_ids, _is_multi_turn)
    if reject:
        logger.info(
            "[CONFIDENCE] Gate triggered: %s (q=%s, source_count=%d)",
            reject["reject_type"], q[:40], len(ctx.get("doc_facts", {}) or {}),
        )
        # 空结果不在缓存中存储，避免缓存污染
        return {
            "answer": reject["message"],
            "sources": [],
            "confidence_reject": reject["reject_type"],
            "session_id": session_id,
            "suggestions": _generate_query_suggestions(q, bank, bank_prompt, ctx.get("title_map", {})),
        }

    # ── Phase 2: 生成答案 ──
    gen = await _generate_answer(
        q=q, bank=bank, bank_prompt=bank_prompt,
        history=history,
        doc_facts=ctx["doc_facts"],
        query_keywords=ctx["query_keywords"],
        _tier_extra=ctx["_tier_extra"],
        title_map=ctx["title_map"],
        kg_context_text=kg_context_text,
    )

    answer = gen["answer"]
    sources = gen["sources"]
    validation_result = gen["validation_result"]
    suggestions = gen.get("suggestions")

    # ── Confidence Gate (L3): LLM 生成后质量校验 ──
    if (
        settings.confidence_reject_enabled
        and validation_result is not None
        and validation_result.get("score", 100) < settings.confidence_reject_threshold_l3_validate * 100
    ):
        logger.info(
            "[CONFIDENCE] Level 3 reject: validation_score=%d (threshold=%d)",
            validation_result.get("score", 100),
            int(settings.confidence_reject_threshold_l3_validate * 100),
        )
        # Level 3: 替换 answer 为拒答内容，保留 sources 供用户参考
        answer = _REJECT_MSG_KNOWLEDGE_GAP
        suggestions = _generate_query_suggestions(q, bank, bank_prompt, ctx.get("title_map", {}))

    # ── 缓存写入 ──
    # 有文档事实的查询可缓存；空结果不缓存；缓存命中时动态重建 suggestions
    if not nocache and ctx["doc_facts"]:
        try:
            doc_ids = set(ctx["doc_facts"].keys()) if ctx["doc_facts"] else set()
            await cache_set(q, bank, answer, sources, doc_ids)
            logger.info("[CACHE] Stored result for: %s", q[:50])
        except Exception as e:
            logger.info("[CACHE] Write error: %s", e)

    # ── 规范文件元数据 ──
    standard_contents = _assemble_standard_contents_meta(sources, bank=bank)

    result = {"answer": answer, "sources": sources}
    if validation_result and validation_result.get("issues"):
        result["quality_check"] = validation_result
    if suggestions:
        result["suggestions"] = suggestions
    if standard_contents:
        result["standard_contents"] = standard_contents
    if kg_context_list:
        result["kg_context"] = kg_context_list
    if session_id:
        result["session_id"] = session_id

    # ── 审计日志（使用共用工具函数）──
    _write_audit_log(request, q, answer, sources, cache_hit=1 if cache_hit else 0, reject=reject["reject_type"] if reject else None)

    return result


@router.post("/cache-clear")
async def clear_llm_cache():
    """清除所有 L1/L2 查询缓存 + BM25 缓存"""
    count = await clear_all_cache()
    logger.info("[CACHE] User triggered cache clear: %d entries", count)
    return {"status": "ok", "cleared": count, "message": f"已清除 {count} 条缓存"}


@router.get("/standard-full/{doc_id}")
async def get_standard_full_text(doc_id: str, bank: str = "all"):
    """返回规范文件的完整正文（从 parent_chunks 组装）。"""
    db = SessionLocal()
    try:
        params = {"doc_id": doc_id}
        doc_sql = "SELECT doc_id, title FROM documents WHERE doc_id=:doc_id AND searchable=1"
        if bank != "all":
            doc_sql += " AND bank=:bank"
            params["bank"] = bank
        title_row = db.execute(sa_text(doc_sql), params).fetchone()
        if not title_row:
            raise HTTPException(404, f"文档 {doc_id} 未找到")
        title = title_row[1] or "未知文档"

        chunks = db.execute(
            sa_text(
                "SELECT parent_idx, parent_text FROM parent_chunks "
                "WHERE doc_id=:doc_id ORDER BY parent_idx"
            ),
            {"doc_id": doc_id},
        ).fetchall()

        if not chunks:
            raise HTTPException(404, f"文档 {doc_id} 未找到或无内容")

        full_text = "\n\n".join(text for _, text in chunks if text)
        total_chars = len(full_text)

        return {
            "doc_id": doc_id,
            "title": title,
            "full_text": full_text,
            "total_chars": total_chars,
            "sections_count": len(chunks),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to fetch standard full text for %s: %s", doc_id, e)
        raise HTTPException(500, f"获取规范正文失败: {e}")
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════
# 联网搜索
# ═══════════════════════════════════════════════════════════════════════


async def _web_search(query: str, max_results: int = 3) -> tuple:
    """通过 AnySearch CLI 联网搜索，返回 (结果文本, 是否成功)"""
    try:
        skill_dir = os.path.expanduser("~/.agents/skills/anysearch")
        cli_path = os.path.join(skill_dir, "scripts", "anysearch_cli.py")
        if not os.path.exists(cli_path):
            return "", False

        proc = await asyncio.create_subprocess_exec(
            "python3", cli_path, "search", query, "--max_results", str(max_results),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode == 0 and stdout:
            result = stdout.decode("utf-8", errors="replace").strip()
            # 检测 AnySearch 错误（配额耗尽等）
            error_keywords = ["daily_free_quota_exhausted", "quota_exhausted", "配额已用尽", "充值后继续"]
            if any(kw in result for kw in error_keywords):
                logger.warning("AnySearch quota exhausted, falling back to LLM")
                return "", False
            return result, True
        return "", False
    except Exception as e:
        logger.warning("web_search failed: %s", e)
        return "", False


@router.post("/web-search")
async def web_search_api(
    q: str = Form(...),
    bank: str = Form("all"),
    context: str = Form(""),
):
    """联网搜索 — 用户对知识库结果不满意时，结合页面上下文联网搜索回答"""
    if not q.strip():
        raise HTTPException(400, "问题不能为空")

    bank_cfg = get_bank_config(bank)
    bank_prompt = bank_cfg["prompt"]

    # 联网搜索
    web_results, search_ok = await _web_search(q, max_results=5)
    fallback_mode = False

    if search_ok and web_results:
        web_context = f"\n\n【联网搜索结果】\n{web_results}\n"
        prompt = f"""{bank_prompt}

用户在一个知识库问答系统中搜索了以下问题，但对知识库返回的结果不满意，需要联网搜索补充。

【用户原始问题】
{q}

【当前页面已有的知识库答案】
{context[:3000] if context else '(无)'}
{web_context}
请综合以上信息，优先参考联网搜索结果，结合知识库已有内容，给出完整、准确的回答。
- 引用具体条款和数据
- 标注信息来源
直接回答，用中文。"""
    else:
        fallback_mode = True
        prompt = f"""{bank_prompt}

用户在知识库中搜索了以下问题，但知识库没有找到满意答案，联网搜索也不可用。
请基于你的专业知识，直接回答用户的问题。

【用户问题】
{q}

【页面上下文】
{context[:2000] if context else '(无)'}

要求：
- 基于你的知识给出准确、实用的回答
- 引用具体法规、标准条款（如果知道）
- 标注"（基于AI知识，非实时数据）"
- 如果不确定，坦诚说明
直接回答，用中文。"""

    try:
        answer = await chat([
            {"role": "system", "content": bank_prompt},
            {"role": "user", "content": prompt},
        ])
    except Exception as e:
        answer = f"回答失败: {e}"

    return {"answer": answer, "web_searched": search_ok, "fallback_mode": fallback_mode}
