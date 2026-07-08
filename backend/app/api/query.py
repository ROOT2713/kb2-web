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

# ── Confidence Rejection Messages ──
_REJECT_MSG_KNOWLEDGE_GAP = "知识库中未找到与您问题直接相关的信息。请尝试换一种方式提问，或确认您的查询范围。"

_REJECT_MSG_LOW_COVERAGE = "知识库中未找到与您问题直接相关的信息。请尝试换一种方式提问，或确认您的查询范围。"

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


# ═══════════════════════════════════════════════════════════════════════
# 核心子函数
# ═══════════════════════════════════════════════════════════════════════


def _extract_high_signal_terms(query_keywords: list[str] | None) -> set[str]:
    """Extract high-signal terms from query keywords for query-doc relevance.

    Used by:
    - Phase F (速查卡过滤): skip concept summary injection for unrelated docs
    - Phase H (doc_facts 重排): move topically-matched docs to front

    Rules:
    - Chinese terms: length >= 2 AND length < 3 is allowed UNLESS in stoplist
      (2-char terms like '接线' '端子' '接地' are high-signal in technical queries)
      Old rule was >= 3, which filtered out all 2-char technical terms
    - Stoplist filters common 2-char middle-weight words
    - ASCII/alnum terms: length >= 2 (keeps 'RAG', 'GB/T', '25000' etc.)
    - All terms lowercased for case-insensitive matching
    """
    _CHINESE_2CHAR_STOP = frozenset({
        "系统", "方法", "要求", "标准", "规范", "技术", "管理", "信息", "服务",
        "文件", "工作", "内容", "规定", "可以", "需要", "进行", "相关", "以下",
        "其他", "包括", "说明", "定义", "方式", "条件", "功能", "使用", "数据",
        "应用", "设计", "配置", "安装", "测试", "检测",
        "不同", "什么", "为什么", "如何", "怎样", "哪个", "哪些", "之间",
        "比较", "区别", "差异", "相同", "不同", "一样",
        "提供", "支持", "具备", "包含", "属于",
        "一般", "通常", "主要", "基本", "整体",
        "情况", "场景", "过程", "流程", "步骤",
        "应该", "可以", "必须", "需要", "能够",
        "怎么", "如何", "怎样", "哪个", "哪些", "之间",
        "什么", "为什么",
        "工具", "功能", "用途", "特性",
        "注意", "说明", "备注", "参考", "资料",
    })
    high_signal: set[str] = set()
    for kw in (query_keywords or []):
        kw_s = kw.strip()
        if len(kw_s) >= 3:
            high_signal.add(kw_s.lower())
        elif len(kw_s) == 2 and kw_s not in _CHINESE_2CHAR_STOP:
            high_signal.add(kw_s.lower())
        elif any(c.isascii() and c.isalnum() for c in kw_s) and len(kw_s) >= 2:
            high_signal.add(kw_s.lower())
    return high_signal


# ═══════════════════════════════════════════════════════════════════
# 摘要文档检测
# ═══════════════════════════════════════════════════════════════════

_SUMMARY_INDICATORS = frozenset({
    "本文介绍了", "本文包含", "本文档包含", "摘要", "概  述", "概述",
    "前言", "范围", "scope", "page_count:", "总页数:", "总页数",
    "本文件规定了", "本文件适用于", "本文主要介绍",
    "基本信息", "文件信息", "文档描述",
})

_CLAUSE_PATTERN = re.compile(r'(第[一二三四五六七八九十百千零\d]+[条章节]|\d+\.\d+)')


def _is_summary_doc(chunk_text: str, doc_name: str) -> bool:
    """检测文档 chunk 是否为摘要/概述级内容（不含具体条款细节）。

    组合检测:
    1. 关键词命中: chunk_text 含 _SUMMARY_INDICATORS 中 ≥1 个
    2. 无条款结构: chunk_text 不含 第X条/X.X 等条款编号模式
    3. 长度约束: chunk_text < 300 字符（短文本）

    返回 True 表示应标记为「摘要级文档」。
    """
    text_clean = chunk_text.strip()
    if not text_clean:
        return False

    # 条款级文档: 包含章节号/条款号 → 非摘要
    if _CLAUSE_PATTERN.search(text_clean):
        return False

    # 标题本身含条款号 → 非摘要（如 "5.2 接地端子要求"）
    if _CLAUSE_PATTERN.search(doc_name):
        return False

    # 摘要关键词检测
    has_indicator = any(ind in text_clean for ind in _SUMMARY_INDICATORS)
    if not has_indicator:
        return False

    # 长文本但有摘要关键词 → 可能是完整文档的开头段，不是纯摘要
    if len(text_clean) >= 500:
        return False

    # 摘要→全文扩展检查（T0-1 已做）：如果 text 已被 parent_chunks 扩展 > 300 字符，非摘要
    # （扩展后的 text 已包含完整条款内容）
    return True


# ── 按置信度排序 ──
def _sort_by_confidence(results: list, top_k: int = 20) -> list:
    """按文档置信度排序（profile_confidence 降序）。"""
    from app.models.database import SessionLocal
    from sqlalchemy import text as sa_text

    doc_ids = set()
    for item in results:
        found = False
        for tag in item.get("tags", []):
            if tag.startswith("doc_id:"):
                doc_ids.add(tag[7:])
                found = True
                break
        if not found and item.get("doc_id"):
            doc_ids.add(str(item["doc_id"]))

    if not doc_ids:
        return results[:top_k]

    conf_map = {}
    try:
        db = SessionLocal()
        try:
            placeholders = ",".join(f":d{i}" for i in range(len(doc_ids)))
            params = {f"d{i}": did for i, did in enumerate(doc_ids)}
            rows = db.execute(
                sa_text(f"SELECT doc_id, profile_confidence FROM documents WHERE doc_id IN ({placeholders})"),
                params,
            ).fetchall()
            for r in rows:
                conf_map[r[0]] = r[1] if r[1] is not None else 0.5
        finally:
            db.close()
    except Exception:
        return results[:top_k]

    def _get_conf(item) -> float:
        for tag in item.get("tags", []):
            if tag.startswith("doc_id:"):
                return conf_map.get(tag[7:], 0.5)
        did = item.get("doc_id")
        if did:
            return conf_map.get(str(did), 0.5)
        return 0.5

    return sorted(results, key=_get_conf, reverse=True)[:top_k]


# ── 按新鲜度排序 ──
def _sort_by_freshness(results: list, top_k: int = 20) -> list:
    """按文档更新时间排序（updated_at 最近优先）。"""
    from app.models.database import SessionLocal
    from sqlalchemy import text as sa_text
    from datetime import datetime, timezone

    doc_ids = set()
    for item in results:
        found = False
        for tag in item.get("tags", []):
            if tag.startswith("doc_id:"):
                doc_ids.add(tag[7:])
                found = True
                break
        if not found and item.get("doc_id"):
            doc_ids.add(str(item["doc_id"]))

    if not doc_ids:
        return results[:top_k]

    time_map = {}
    default_time = datetime(2000, 1, 1, tzinfo=timezone.utc)
    try:
        db = SessionLocal()
        try:
            placeholders = ",".join(f":d{i}" for i in range(len(doc_ids)))
            params = {f"d{i}": did for i, did in enumerate(doc_ids)}
            rows = db.execute(
                sa_text(f"SELECT doc_id, updated_at, created_at FROM documents WHERE doc_id IN ({placeholders})"),
                params,
            ).fetchall()
            for r in rows:
                ts = r[1] or r[2] or default_time
                if hasattr(ts, "tzinfo") and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                time_map[r[0]] = ts
        finally:
            db.close()
    except Exception:
        return results[:top_k]

    def _get_time(item):
        for tag in item.get("tags", []):
            if tag.startswith("doc_id:"):
                return time_map.get(tag[7:], default_time)
        did = item.get("doc_id")
        if did:
            return time_map.get(str(did), default_time)
        return default_time

    return sorted(results, key=_get_time, reverse=True)[:top_k]


async def _build_search_context(
    q: str,
    bank: str,
    history: str,
    use_rerank: bool,
    rerank_mode: str,
    hs_bank: str,
    q_recalled: str,
    q_bm25: str,
    query_keywords: list,
    _tier_extra: list,
    kg_info: dict,
    session_doc_ids: set = None,
) -> dict:
    """
    构建搜索上下文 — recall + BM25 + RRF + rerank。

    返回:
        {
            "all_results": [...],       # 排序后的搜索结果列表
            "context_parts": [...],     # 上下文文本片段
            "sources": [...],           # 来源信息
            "doc_facts": {...},         # doc_id → [(text, doc_name, cleaned, parent_idx), ...]
            "query_keywords": list,
            "_tier_extra": list,
        }
    """
    # ── 构建 doc_id → bank 映射和 title 映射 ──
    db = SessionLocal()
    bank_map = {}
    title_map = {}
    try:
        rows = db.execute(sa_text("SELECT doc_id, bank, title FROM documents WHERE searchable=1 AND status='active'")).fetchall()
        bank_map = {r[0]: r[1] for r in rows}
        # title_map: 只用于展示来源文档名，不参与检索过滤，因此不限制 searchable=1
        # 避免 reparse/reindex 后 searchable 尚未置 1 时 title 为空
        title_rows = db.execute(sa_text("SELECT doc_id, title FROM documents WHERE status='active'")).fetchall()
        title_map = {r[0]: (r[1] or "") for r in title_rows}
    except Exception:
        pass
    finally:
        db.close()

    # ── 精确检索：关键词匹配 meta.db 标题 ──
    exact_results = []
    patterns = [
        r'GB/T\s*\d+[\.\-]\d+', r'GB\s*\d+[\.\-]\d+',
        r'T/EGAG\s*\d+[\.\-]\d+', r'GDZW\s*\d+[\.\-]\d+',
        r'粤府办〔\d+〕\d+号', r'穗政数〔\d+〕\d+号',
        r'ISO\s*\d+', r'[一-鿿]+〔\d+〕\d+号',
    ]
    exact_terms = set()
    for pat in patterns:
        exact_terms.update(re.findall(pat, q_recalled))

    if exact_terms:
        db = SessionLocal()
        try:
            conditions = " OR ".join(["title LIKE :t" + str(i) for i in range(len(exact_terms))])
            params = {f"t{i}": f"%{t}%" for i, t in enumerate(exact_terms)}
            title_rows = db.execute(
                sa_text(f"SELECT doc_id, title FROM documents WHERE searchable=1 AND status='active' AND ({conditions})"),
                params,
            ).fetchall()
        finally:
            db.close()

        for tr in title_rows:
            if bank != "all" and bank_map.get(tr[0]) != bank:
                continue
            if bank_map.get(tr[0]) == "skip":
                continue
            targeted = await recall(tr[1], limit=2, bank=hs_bank, doc_ids=session_doc_ids)
            for r in targeted:
                tags = r.get("tags", [])
                doc_tag = None
                for t in tags:
                    if t.startswith("doc_id:"):
                        doc_tag = t[7:]
                        break
                if doc_tag == tr[0]:
                    exact_results.append(r)

    # ── 标题模糊匹配 ──
    if not exact_results and not exact_terms:
        import jieba as _jieba_mod
        title_keywords = [w for w in _jieba_mod.cut(q_recalled) if len(w.strip()) >= 2]
        if title_keywords:
            try:
                tdb = SessionLocal()
                all_docs = tdb.execute(
                    sa_text("SELECT doc_id, title FROM documents WHERE searchable=1")
                ).fetchall()
                tdb.close()
                best_doc = None
                best_score = 0
                for row in all_docs:
                    doc_title_val = row[1] or ""
                    score = sum(1 for kw in title_keywords if kw in doc_title_val)
                    if score > best_score:
                        best_score = score
                        best_doc = row
                if best_doc and best_score >= 2 and best_doc[0]:
                    if bank == "all" or bank_map.get(best_doc[0]) == bank:
                        targeted = await recall(best_doc[1][:50], limit=3, bank=hs_bank, doc_ids=session_doc_ids)
                        for tr in targeted:
                            tr_doc_id = None
                            for t in tr.get("tags", []):
                                if t.startswith("doc_id:"):
                                    tr_doc_id = t[7:]
                                    break
                            if tr_doc_id == best_doc[0]:
                                exact_results.append(tr)
            except Exception as e:
                logger.warning("title fuzzy match: %s", e)

    # ── Hybrid Search: Dense + BM25 RRF 融合 ──
    all_recall_results = []
    if bank != "all" and hs_bank and hs_bank != "kb":
        try:
            all_recall_results = await recall(q_recalled, limit=40, bank=hs_bank)
        except Exception as e:
            logger.warning("recall(%s) failed: %s", hs_bank, e)
    else:
        active_banks = await _get_active_hindsight_banks()
        for _hs_bank in active_banks:
            try:
                bank_results = await recall(q_recalled, limit=40, bank=_hs_bank)
                all_recall_results.extend(bank_results)
            except Exception:
                pass

    # 指定bank时禁止fallback到旧kb bank
    if all_recall_results:
        raw_results = all_recall_results
    elif bank == "all":
        raw_results = await recall(q_recalled, limit=25, bank="kb")
    else:
        raw_results = []

    # ── BM25 关键词召回 ──
    bm25_merged = list(raw_results)
    bm25_hits = []
    try:
        bm25_index, bm25_docs = await build_bm25_index(bank)
        if bm25_index:
            bm25_hits = bm25_search(q_bm25, bm25_index, bm25_docs, top_k=30)
            bm25_merged = rrf_merge(raw_results, bm25_hits, k=60, query_keywords=query_keywords, bank=bank)
    except Exception as e:
        logger.warning("BM25 fallback: %s", e)

    # 精确结果排在最前面
    all_results = exact_results + bm25_merged

    # ── BM25 top结果强制注入 ──
    def _get_doc_key(item):
        doc_id = item.get("doc_id")
        parent_idx = None
        for t in item.get("tags", []):
            if not doc_id and t.startswith("doc_id:"):
                doc_id = t[7:]
            if t.startswith("parent_idx:"):
                try:
                    parent_idx = int(t.split(":", 1)[1])
                except (ValueError, IndexError):
                    pass
        return (doc_id, parent_idx)

    if bm25_hits:
        _injected = 0
        for bm25_hit in bm25_hits[:10]:
            hit_text = bm25_hit.get("text", "")
            hit_key = _get_doc_key(bm25_hit)
            _has_kw = query_keywords and any(kw in hit_text for kw in query_keywords)
            already_in = any(
                hit_key == _get_doc_key(r) and hit_key[0] is not None
                for r in all_results[:15]
            )
            if _has_kw and not already_in and _injected < 6:
                all_results.insert(0, bm25_hit)
                _injected += 1

    # ── KG 消歧增强 ──
    if kg_info.get("disambiguated") and kg_info.get("suggested_doc_ids"):
        seen_doc_ids = set()
        for ent in kg_info["matched_entities"]:
            for t in ent.get("tags", []):
                if t.startswith("doc:") and t[4:] in kg_info["suggested_doc_ids"] and t[4:] not in seen_doc_ids:
                    kid = t[4:]
                    seen_doc_ids.add(kid)
                    try:
                        targeted = await recall(ent["name"], limit=3, bank=hs_bank)
                        for tr in targeted:
                            tr_doc_id = None
                            for tt in tr.get("tags", []):
                                if tt.startswith("doc_id:"):
                                    tr_doc_id = tt[7:]
                                    break
                            if tr_doc_id == kid and tr not in all_results:
                                all_results.insert(0, tr)
                    except Exception:
                        pass

    # ── BM25精确命中保护 ──
    exact_bm25_hits = set()
    q_lower = q.lower()
    for r in all_results:
        r_text = (r.get("text", "") or "").lower()
        if q_lower in r_text:
            key = tuple(r.get("tags", []))
            exact_bm25_hits.add(key)

    # ── 轻量级关键词 Rerank（在任何精排之前）──
    if len(all_results) > 3:
        all_results = keyword_rerank(q, all_results, top_k=20)

    # ── 模式化 Rerank 精排 ──
    if use_rerank and len(all_results) > 2:
        if rerank_mode == "multidim":
            # 多维重排（keyword + dense + confidence + freshness + source_count）
            try:
                from app.services.rerank import multidim_rerank
                all_results = multidim_rerank(
                    all_results, query=q, bank=bank, top_k=20,
                )
            except Exception as e:
                logger.warning("multidim_rerank failed, falling back to llm: %s", e)
                # graceful degradation: fallback to LLM rerank
                try:
                    reranked = await asyncio.wait_for(
                        llm_rerank(q, all_results, top_k=15),
                        timeout=30,
                    )
                    if exact_bm25_hits:
                        protected, others = [], []
                        for r in reranked:
                            key = tuple(r.get("tags", []))
                            if key in exact_bm25_hits:
                                protected.append(r)
                            else:
                                others.append(r)
                        all_results = protected + others
                    else:
                        all_results = reranked
                except asyncio.TimeoutError:
                    logger.warning("LLM rerank timeout (30s), using RRF order")
                except Exception as e2:
                    logger.warning("LLM rerank fallback also failed: %s", e2)
        elif rerank_mode == "confidence":
            # 按置信度排序
            try:
                all_results = _sort_by_confidence(all_results)
            except Exception as e:
                logger.warning("confidence sort failed, fallback to default: %s", e)
                try:
                    reranked = await asyncio.wait_for(
                        llm_rerank(q, all_results, top_k=15),
                        timeout=30,
                    )
                    all_results = reranked
                except Exception:
                    pass
        elif rerank_mode == "freshness":
            # 按新鲜度排序（updated_at 最新优先）
            try:
                all_results = _sort_by_freshness(all_results)
            except Exception as e:
                logger.warning("freshness sort failed, fallback to default: %s", e)
                try:
                    reranked = await asyncio.wait_for(
                        llm_rerank(q, all_results, top_k=15),
                        timeout=30,
                    )
                    all_results = reranked
                except Exception:
                    pass
        elif rerank_mode == "cross_encoder":
            # Cross-encoder rerank via SiliconFlow (fast, cheap, calibrated)
            try:
                reranked = await asyncio.wait_for(
                    cross_encoder_rerank(q, all_results, top_k=15),
                    timeout=15,
                )
                if exact_bm25_hits:
                    protected = []
                    others = []
                    for r in reranked:
                        key = tuple(r.get("tags", []))
                        if key in exact_bm25_hits:
                            protected.append(r)
                        else:
                            others.append(r)
                    all_results = protected + others
                else:
                    all_results = reranked
            except asyncio.TimeoutError:
                logger.warning("[RERANK] Cross-encoder timeout (15s), falling back to RRF order")
            except Exception as e:
                logger.warning("[RERANK] Cross-encoder failed: %s, falling back to RRF order", e)
        else:
            # Default: LLM Rerank精排
            try:
                reranked = await asyncio.wait_for(
                    llm_rerank(q, all_results, top_k=15),
                    timeout=30,
                )
                if exact_bm25_hits:
                    protected = []
                    others = []
                    for r in reranked:
                        key = tuple(r.get("tags", []))
                        if key in exact_bm25_hits:
                            protected.append(r)
                        else:
                            others.append(r)
                    all_results = protected + others
                else:
                    all_results = reranked
            except asyncio.TimeoutError:
                logger.warning("LLM rerank timeout (30s), using RRF order")
            except Exception as e:
                logger.warning("LLM rerank skipped: %s", e)

    # ── Tiebreaker: 时间 + 地理层级排序（在 LLM Rerank 之后，doc_facts 之前）──
    # 核心原则：语义相似度永远是主排序，时间和地理只是 tiebreaker。
    # LLM Rerank 先做语义重排，tiebreaker 在段内做二级排序。
    if len(all_results) > 5:
        try:
            all_results = apply_tiebreaker_sort(all_results, query=q)
        except Exception as e:
            logger.warning("tiebreaker sort failed: %s", e)

    # ── 短摘要扩展：从 parent_chunks 取回全文（在 rerank 之后，D2-B 之前）──
    # [T0-1] 从 raw_results[:30] 移到此处，确保 rerank 后的全量结果都被覆盖
    try:
        _pdb = SessionLocal()
        for _ri, _r in enumerate(all_results):
            _text = _r.get("text", "") or ""
            if len(_text) >= 150:
                continue
            _doc_id = None
            _parent_idx = None
            for _t in _r.get("tags", []):
                if _t.startswith("doc_id:"):
                    _doc_id = _t[7:]
                elif _t.startswith("parent_idx:"):
                    try:
                        _parent_idx = int(_t.split(":", 1)[1])
                    except (ValueError, IndexError):
                        pass
            if not _doc_id:
                continue
            if _parent_idx is not None:
                _row = _pdb.execute(
                    sa_text("SELECT parent_text FROM parent_chunks WHERE doc_id=:did AND parent_idx=:pidx"),
                    {"did": _doc_id, "pidx": _parent_idx},
                ).fetchone()
            else:
                _row = _pdb.execute(
                    sa_text("SELECT parent_text FROM parent_chunks WHERE doc_id=:did ORDER BY parent_idx LIMIT 1"),
                    {"did": _doc_id},
                ).fetchone()
            if _row and _row[0]:
                _full_text = _row[0]
                if len(_full_text) > len(_text) * 2:
                    all_results[_ri] = {**_r, "text": _full_text}
        _pdb.close()
    except Exception as e:
        logger.warning("short summary enrichment (post-rerank) failed: %s", e)

    # ── D2-B: 金额类查询定向注入费率表chunk ──
    # 旧方案: LIMIT 3 parent_chunks → 命中封面/编委会，不含费率表。
    # 新方案: keyword scoring + formula-aware → 命中 idx=38-55 的真实费率表。
    _d2q = q
    try:
        _d2q = q.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    _fee_q = any(kw in _d2q for kw in [
        "造价", "取费", "费用", "费率", "收费",
        "验收测评", "验收评测", "检测费", "测评费", "评测费",
        "审计费", "管理费", "设计费", "监理费", "招标",
        "等保", "密评", "咨询费",
        "商密", "商用密码", "密码应用",
    ])
    if _fee_q:
        try:
            _fdocs = SessionLocal()
            _frows = _fdocs.execute(sa_text(
                "SELECT d.doc_id, d.title FROM documents d "
                "WHERE d.searchable=1 AND d.status='active' "
                "AND d.bank='industry_docs' "
                "AND (d.title LIKE '%造价%' OR d.title LIKE '%费用%' OR d.title LIKE '%取费%')"
            )).fetchall()
        except Exception:
            _frows = []
        finally:
            if '_fdocs' in locals():
                try:
                    _fdocs.close()
                except Exception:
                    pass
        _fee_docs = {r[0]: r[1] for r in _frows}

        # Build dedup set from existing results to avoid double-injecting same chunks
        _injected_keys = set()
        for r in all_results:
            _did = None
            for t in r.get("tags", []):
                if t.startswith("doc_id:"):
                    _did = t[7:]
                    break
            if _did:
                _txt = (r.get("text", "") or "")[:100]
                _injected_keys.add(f"{_did}:{hash(_txt)}")

        # Build amount keywords from query for scoring
        _amount_kw = [kw for kw in (_tier_extra or []) if "万" in kw]
        _amount_kw.extend(re.findall(r'\d+[\.\d]*\s*万', q))
        
        # Extract fee type keywords from query for boosting
        _fee_type_kw = []
        _fee_type_patterns = re.findall(r'(验收测评|验收评测|监理|设计|等保|咨询|审计|招标|检测|评测|评估|造价|管理费|商密|商用密码|密评|密码应用)', q)
        if _fee_type_patterns:
            _fee_type_kw = list(set(_fee_type_patterns))
            logger.info("[D2-B] Fee type detected: %s", _fee_type_kw)

        # Use fee-aware chunk selection — inject ALL fee docs
        _all_fee_ids = list(_fee_docs.keys())
        _fee_chunks_to_inject = []
        if _all_fee_ids:
            _fee_chunks_to_inject = find_fee_relevant_chunks(
                _all_fee_ids,
                amount_keywords=_amount_kw,
                max_chunks=8,
                fee_type_keywords=_fee_type_kw,
            )
        # Prepend in score-descending order, skip already-injected chunks
        for _chunk in reversed(_fee_chunks_to_inject):
            _dedup_key = f"{_chunk['doc_id']}:{hash(_chunk['text'][:100])}"
            if _dedup_key in _injected_keys:
                continue
            _injected_keys.add(_dedup_key)
            all_results.insert(0, {
                    "text": _chunk["text"],
                    "tags": [
                        f"doc_id:{_chunk['doc_id']}",
                        f"title:{_chunk['title']}",
                        "source:industry_fallback",
                    ],
                    "metadata": {
                        "doc_id": _chunk["doc_id"],
                        "title": _chunk["title"],
                        "source": "industry_fallback",
                    },
                })
        if _fee_chunks_to_inject:
            logger.info(
                "[D2-B] Injected %d fee chunks (from %d docs), top score=%d",
                len(_fee_chunks_to_inject), len(_all_fee_ids),
                _fee_chunks_to_inject[0]["score"] if _fee_chunks_to_inject else 0,
            )
        else:
            logger.info("[D2-B] No fee chunks found for query: %s", q[:60])

    # ── 清洗 + 过滤 + 去重合并 ──
    doc_facts = {}
    for r in all_results:
        text_val = r.get("text", "") or ""
        tags = r.get("tags", [])

        # 提取 doc_id
        doc_id = None
        for t in tags:
            if t.startswith("doc_id:"):
                doc_id = t[7:]
                break
        if not doc_id:
            meta = r.get("metadata") or {}
            doc_id = meta.get("doc_id") or meta.get("source_doc_id")
        if not doc_id:
            doc_id = r.get("document_id")
        if not doc_id:
            doc_id = f"_notag_{id(r)}"

        # 过滤 skip bank
        if bank_map.get(doc_id) == "skip":
            continue

        # 过滤指定 bank
        if bank != "all":
            mapped = bank_map.get(doc_id)
            if mapped is not None and mapped != bank:
                continue

        # 提取文档名
        doc_name = ""
        for t in tags:
            if t.startswith("title:"):
                doc_name = t[6:]
                break
        if not doc_name:
            meta = r.get("metadata") or {}
            doc_name = meta.get("title", "")
        if not doc_name or doc_name == "未知文档":
            meta_title = title_map.get(doc_id, "")
            if meta_title:
                doc_name = meta_title
        if not doc_name:
            doc_name = "未知文档"

        # 清理 Hindsight 元数据
        cleaned = re.sub(r'\s*\|\s*(When|Involving|Entities|Location|Type|Source):[^|]*', '', text_val).strip()
        if not cleaned:
            cleaned = text_val.strip()

        # 提取 parent_idx
        parent_idx = None
        for t in tags:
            if t.startswith("parent_idx:"):
                try:
                    parent_idx = int(t.split(":", 1)[1])
                except (ValueError, IndexError):
                    pass
                break

        if doc_id not in doc_facts:
            doc_facts[doc_id] = []
        doc_facts[doc_id].append((text_val, doc_name, cleaned, parent_idx))

    # ── T1-2: 版本感知 doc_facts 去重 ──
    # 同一标准号多版本时只保留最新版本（除非查询明确提及旧版年份）
    _query_has_year = bool(re.search(r'(?:19|20)\d{2}', q or ''))
    _version_map = {}
    for _did in list(doc_facts.keys()):
        _dname = doc_facts[_did][0][1] if doc_facts[_did] else ""
        _base, _year = _extract_standard_base_and_year(_dname)
        if _base and _year:
            _version_map[_did] = (_base, _year)

    _base_groups = defaultdict(list)
    for _did, (_base, _year) in _version_map.items():
        _base_groups[_base].append((_did, _year))

    _dids_to_drop = set()
    for _base, _entries in _base_groups.items():
        if len(_entries) <= 1:
            continue
        _entries.sort(key=lambda x: x[1], reverse=True)
        _newest_did = _entries[0][0]
        _newest_year = _entries[0][1]
        for _did, _year in _entries:
            if _did == _newest_did:
                continue
            _old_year_str = str(_year)
            if _query_has_year and _old_year_str in (q or ""):
                continue  # 查询明确要旧版，保留
            _dids_to_drop.add(_did)
            logger.info("[T1-2] Drop old version %s (base=%s, year=%d), keep %s (newest=%d)",
                        _did, _base, _year, _newest_did, _newest_year)

    for _did in _dids_to_drop:
        doc_facts.pop(_did, None)

    # ── Phase H: Query-doc title 相关度重排 ──
    # 当 bank="all" 触发多 bank 分散查询时，Dense (Hindsight) 返回的各 bank
    # top 结果可能包含与 query 主题完全无关的文档（BM25 IDF 分布变化后更明显）。
    # 修复: 把 doc_name 含高信号词的 doc 排到 doc_facts 前面，让 LLM 先看到主题相关的文档。
    _high_signal = _extract_high_signal_terms(query_keywords)

    if _high_signal and doc_facts:
        _matched = {}
        _content_matched = {}
        _unmatched = {}
        for _did, _facts in doc_facts.items():
            _dname = _facts[0][1].lower() if _facts else ""
            if any(_t in _dname for _t in _high_signal):
                _matched[_did] = _facts
            elif _facts:
                # Chunk text content matching: docs whose chunk text (not just title)
                # contains query keywords should also be boosted.
                # Fixes: GB 16806 chunk has "接线端子" but title "消防联动控制系统" doesn't.
                _chunks_text = " ".join([f[0].lower() for f in _facts])
                if any(_t in _chunks_text for _t in _high_signal):
                    _content_matched[_did] = _facts
                else:
                    _unmatched[_did] = _facts
            else:
                _unmatched[_did] = _facts
        # Title-matched first, content-matched second, unmatched last
        doc_facts = {**_matched, **_content_matched, **_unmatched}

    return {
        "all_results": all_results,
        "doc_facts": doc_facts,
        "query_keywords": query_keywords,
        "_tier_extra": _tier_extra,
        "bank_map": bank_map,
        "title_map": title_map,
    }


def _keyword_suggestion_rules(q: str) -> list:
    """返回 [(用户短语tuple, 知识库术语, 改写建议问题), ...]"""
    q_lower = q.lower()
    rules = [
        (("隐私信息", "隐私数据", "个人资料"), "个人敏感信息", "个人敏感信息包括哪些类别？"),
        (("敏感数据", "敏感信息"), "个人敏感信息", "个人敏感信息的定义和分类是什么？"),
        (("收费", "费用", "取费"), "取费标准", "验收测评服务取费标准是什么？"),
        (("测试依据", "测评依据", "检测依据"), "测试依据", "软件测评应依据哪些标准和规范？"),
        (("等保", "等级保护"), "等级保护测评", "等级保护测评要求包括哪些内容？"),
        (("密评", "密码应用"), "商用密码应用安全性评估", "商用密码应用安全性评估怎么做？"),
    ]
    results = []
    for user_terms, kb_term, refined_query in rules:
        for ut in user_terms:
            if ut.lower() in q_lower or ut in q:
                results.append((user_terms, kb_term, refined_query))
                break
    return results


# ── 模块级标准号正则 ──
_STD_PATTERN = re.compile(
    r'(GB\s*/?\s*T?\s*\d+(?:[\.\—\-–]\s*\d{1,4})?'
    r'|ISO(?:\s*/\s*IEC)?\s*\d+(?:[\.\—\-–]\s*\d{1,4})?'
    r'|(?:YD|SJ|GA|HJ|CJJ|JGJ|WS)\s*/?\s*T?\s*\d+(?:[\.\—\-–]\s*\d{1,4})?'
    r'|T\s*/\s*EGAG\s*\d+(?:[\.\—\-–]\s*\d{1,4})?'
    r'|TEGAG\s*\d+(?:[\.\—\-–]\s*\d{1,4})?'
    r'|GDZW\s*\d+(?:[\.\—\-–]\s*\d{1,4})?'
    r'|STC[\w\-]+'
    r'|DB\d+[\w\-]*'
    r'|[一-鿿]+〔\d+〕\d+号)'
)


def _normalize_doc_title_for_standard(title: str) -> str:
    """标准化文档标题中 + 和 _ 分隔符。"""
    return title.replace("+", " ").replace("_", "/").replace("∕", "/")


def _normalize_standard_keyword(raw: str) -> str:
    """规范化标准号关键词，统一空格和 GB/T 写法。"""
    kw = re.sub(r"\s+", " ", raw).strip()
    kw = re.sub(r"GB\s*/\s*T", "GB/T", kw, flags=re.IGNORECASE)
    kw = re.sub(r"GB\s+T", "GB/T", kw, flags=re.IGNORECASE)
    kw = re.sub(r"T\s*/\s*EGAG", "T/EGAG", kw, flags=re.IGNORECASE)
    kw = re.sub(r"ISO\s*/\s*IEC", "ISO/IEC", kw, flags=re.IGNORECASE)
    kw = re.sub(r"\s*([\—\-–])\s*", r"\1", kw)
    return kw


# ═══════════════════════════════════════════════════════════════════
# 版本感知 — 标准号版本提取
# ═══════════════════════════════════════════════════════════════════

_STD_VERSION_PATTERN = re.compile(
    r'(?P<prefix>'
    r'GB(?:/T)?\s*\d+(?:[\.\—\-–]\s*\d{1,4})?'
    r'|ISO(?:\s*/\s*IEC)?\s*\d+(?:[\.\—\-–]\s*\d{1,4})?'
    r'|YD\s*/?\s*T?\s*\d+'
    r'|SJ\s*/?\s*T?\s*\d+'
    r'|GA\s*/?\s*T?\s*\d+'
    r'|HJ\s*/?\s*T?\s*\d+'
    r'|CJJ\s*/?\s*T?\s*\d+'
    r'|JGJ\s*/?\s*T?\s*\d+'
    r'|WS\s*/?\s*T?\s*\d+'
    r'|T\s*/\s*EGAG\s*\d+'
    r'|TEGAG\s*\d+'
    r'|GDZW\s*\d+'
    r'|STC[\w\-]+'
    r'|DB\d+[\w\-]*'
    r')'
    r'\s*[\-–—]?\s*'
    r'(?P<year>(?:19|20)\d{2})?'
)


def _extract_standard_base_and_year(doc_name: str) -> tuple[str | None, int | None]:
    """从文档标题中提取标准号基准 + 年份。

    例如:
      "GB 50462-2015 数据中心基础设施施工及验收标准" → ("GB50462", 2015)
      "GB 50462-2024 数据中心基础设施施工及验收标准" → ("GB50462", 2024)
      "T/EGAG 010-2022 监理服务规范" → ("TEGAG010", 2022)
      "粤府办〔2020〕9号 管理办法" → ("粤府办", 2020)
      "小红书笔记" → (None, None)

    返回:
        (base_standard, year): base_standard = 去除空格/分隔符的标准号基准
                               year = 4位数字年份或 None
    """
    if not doc_name:
        return None, None
    normalized = _normalize_doc_title_for_standard(doc_name)
    m = _STD_VERSION_PATTERN.search(normalized)
    if not m:
        # 尝试匹配中文年份格式: 粤府办〔2020〕9号
        cn_m = re.search(r'([一-鿿]+)〔(\d{4})〕', doc_name)
        if cn_m:
            return (cn_m.group(1).strip(), int(cn_m.group(2)))
        return None, None

    prefix = re.sub(r'\s*', '', m.group('prefix'))  # "GB/T 50462" → "GB/T50462"
    year_str = m.group('year')
    year = int(year_str) if year_str else None
    return (prefix, year)


def _assemble_standard_contents_meta(sources: list, bank: str = "all") -> list[dict]:
    """从 sources 中识别规范文件，查询 parent_chunks 获取元数据。

    返回 [{title, doc_id, total_chars, sections_count, preview}, ...]
    仅使用 sources 中已有 doc_id 作为锚点，避免标题模糊匹配跨 bank 泄漏。

    性能优化（2026-06-20）：先 regex 过滤候选 doc_id，再用一条聚合 SQL
    一次性拿到 documents 元数据 + parent_chunks 聚合 + preview，
    把原来 per-source 3 次 SQL（最多 12×3=36 次）压到 1 次。
    """
    # ── Step 1: 纯 Python 过滤，收集候选 doc_id（保持 sources 出现顺序）──
    candidate_ids = []
    seen = set()
    title_fallback: dict[str, str] = {}
    for src in sources:
        title = src.get("doc") or src.get("title") or ""
        doc_id = src.get("doc_id")
        if not title or not doc_id or doc_id in seen:
            continue
        normalized = _normalize_doc_title_for_standard(title)
        if not _STD_PATTERN.search(normalized):
            continue
        seen.add(doc_id)
        candidate_ids.append(doc_id)
        title_fallback[doc_id] = title

    if not candidate_ids:
        return []

    # ── Step 2: 一次聚合 SQL 拿全部元数据 ──
    # SQLite 支持 IN (:p0, :p1, ...) 用命名占位符。SUBSTR(...) 子查询
    # 取 parent_idx 最小的那段，模拟原来的 LIMIT 1 ORDER BY preview 行为。
    placeholders = ", ".join(f":id{i}" for i in range(len(candidate_ids)))
    params: dict = {f"id{i}": did for i, did in enumerate(candidate_ids)}
    sql = (
        "SELECT d.doc_id, d.title, "
        "       COALESCE(SUM(LENGTH(pc.parent_text)), 0) AS total_chars, "
        "       COUNT(pc.parent_idx) AS sections_count, "
        "       (SELECT SUBSTR(parent_text, 1, 200) FROM parent_chunks "
        "        WHERE doc_id = d.doc_id ORDER BY parent_idx LIMIT 1) AS preview "
        "FROM documents d "
        "LEFT JOIN parent_chunks pc ON pc.doc_id = d.doc_id "
        f"WHERE d.doc_id IN ({placeholders}) AND d.searchable = 1"
    )
    if bank != "all":
        sql += " AND d.bank = :bank"
        params["bank"] = bank
    sql += " GROUP BY d.doc_id, d.title"

    db = SessionLocal()
    try:
        rows = db.execute(sa_text(sql), params).fetchall()
    except Exception as e:
        logger.warning("Failed to assemble standard meta: %s", e)
        return []
    finally:
        db.close()

    # ── Step 3: 按原始 sources 顺序拼装结果 ──
    by_id = {row[0]: row for row in rows}
    results: list[dict] = []
    for did in candidate_ids:
        row = by_id.get(did)
        if not row:
            continue
        results.append({
            "title": row[1] or title_fallback.get(did, ""),
            "doc_id": did,
            "total_chars": row[2] or 0,
            "sections_count": row[3] or 0,
            "preview": row[4] or "",
        })
    return results


def _build_follow_up_questions(q: str) -> list[str]:
    """返回常驻兜底追问列表。"""
    return [
        f"{q} 的标准术语是什么？",
        f"{q} 涉及哪些标准或规范？",
        f"请按知识库中的标准名称重新检索：{q}",
    ]


def _extract_standard_hints_from_sources(sources: list, q: str, limit: int = 6) -> list[dict]:
    """从 sources 中提取规范文件，生成 standard_hints 列表。

    从 source 的 doc/title 字段提取 GB/T、GB、STC、DB 等规范号，
    生成 {title, doc_id, reason, recommended_query}，去重并保持 sources 顺序。
    """
    standard_hints = []
    seen_std = set()
    for src in sources:
        title = src.get("doc") or src.get("title") or ""
        doc_id = src.get("doc_id")
        normalized_title = _normalize_doc_title_for_standard(title)
        m = _STD_PATTERN.search(normalized_title)
        doc_keyword = _normalize_standard_keyword(m.group(1)) if m else None
        if not doc_keyword or doc_keyword in seen_std:
            continue
        seen_std.add(doc_keyword)
        recommended = f"{doc_keyword} {q[:40]}"
        reason = f"该{doc_keyword}规范包含相关内容，建议带上规范名称搜索，结果更准确"
        standard_hints.append({
            "title": title,
            "doc_id": doc_id,
            "reason": reason,
            "recommended_query": recommended,
        })
        if len(standard_hints) >= limit:
            break
    return standard_hints


def _merge_persistent_suggestions(base: dict | None, persistent: dict) -> dict:
    """合并 persistent suggestions 和 base suggestions。

    standard_hints 按 (doc_id, title, recommended_query) 去重；
    确保 follow_up_questions 存在。
    """
    result = dict(persistent)
    if base:
        # 合并 standard_hints，按 key 去重
        def _hint_key(hint: dict):
            title = (hint.get("title") or "").strip()
            return title or hint.get("doc_id")

        existing_keys = set()
        merged_hints = []
        for hint in persistent.get("standard_hints", []):
            key = _hint_key(hint)
            if key not in existing_keys:
                existing_keys.add(key)
                merged_hints.append(hint)
        for hint in base.get("standard_hints", []):
            key = _hint_key(hint)
            if key not in existing_keys:
                existing_keys.add(key)
                merged_hints.append(hint)
        result["standard_hints"] = merged_hints

        # 合并 base 中的其他字段
        for key in ("refined_query", "term_hints", "related_docs"):
            if key in base and base[key]:
                result[key] = base[key]

    # 确保 follow_up_questions 存在
    if "follow_up_questions" not in result:
        result["follow_up_questions"] = []
    return result


def _build_persistent_suggestions(q: str, sources: list | None = None) -> dict:
    """构建常驻建议：包含 standard_hints 和 follow_up_questions。"""
    if sources is None:
        sources = []
    return {
        "standard_hints": _extract_standard_hints_from_sources(sources, q),
        "follow_up_questions": _build_follow_up_questions(q),
    }


def _suggestions_for_answer(q, bank, bank_prompt, title_map, sources, answer) -> dict:
    """构建 answer 的 suggestions，始终包含常驻兜底建议。

    如果 answer 包含低置信标记，额外调用 _generate_query_suggestions 获取完整建议再合并。
    否则只返回 persistent 建议。
    """
    persistent = _build_persistent_suggestions(q, sources)

    no_answer_markers = ("未收录", "未找到", "未直接命中", "未明确", "没有相关信息", "未涉及")
    if any(marker in answer for marker in no_answer_markers):
        base = _generate_query_suggestions(q, bank, bank_prompt, title_map, sources)
        return _merge_persistent_suggestions(base, persistent)

    return persistent


def _generate_query_suggestions(
    q: str,
    bank: str,
    bank_prompt: str = "",
    title_map: dict | None = None,
    source_docs: list | None = None,
) -> dict:
    """
    基于规则和数据库真实文档生成查询改写建议。
    不调用 LLM，避免延迟和幻觉。
    返回: {refined_query, term_hints, related_docs, standard_hints, follow_up_questions}
    """
    if title_map is None:
        title_map = {}
    if source_docs is None:
        source_docs = []

    # ── 规则匹配 ──
    matched_rules = _keyword_suggestion_rules(q)

    # ── 提取中文关键词片段 ──
    import jieba as _jieba_mod2
    keywords_in_q = [w for w in _jieba_mod2.cut(q) if len(w.strip()) > 1]

    # ── 从 rules 收集 kb_term ──
    kb_terms = [kb for _, kb, _ in matched_rules]
    if not kb_terms and keywords_in_q:
        kb_terms = keywords_in_q[:5]

    # ── 构建 term_hints ──
    term_hints = []
    seen_hints = set()
    for user_terms, kb_term, _ in matched_rules:
        for ut in user_terms:
            if ut in q and (ut, kb_term) not in seen_hints:
                seen_hints.add((ut, kb_term))
                term_hints.append({"user_term": ut, "kb_term": kb_term})

    # ── 查询数据库获取相关文档 ──
    related_docs = []
    seen_titles = set()
    if kb_terms:
        db = SessionLocal()
        try:
            like_clauses = []
            params = {}
            for i, kw in enumerate(kb_terms[:5]):
                like_clauses.append(f"title LIKE :kw{i}")
                params[f"kw{i}"] = f"%{kw}%"
            conditions = " OR ".join(like_clauses)
            sql = f"""SELECT doc_id, title FROM documents
                WHERE searchable=1 AND bank != 'skip' AND ({conditions})"""
            if bank != "all":
                sql += " AND bank=:bank"
                params["bank"] = bank
            sql += " LIMIT 5"
            rows = db.execute(sa_text(sql), params).fetchall()
            for row in rows:
                title_val = row[1] or ""
                if title_val not in seen_titles:
                    seen_titles.add(title_val)
                    related_docs.append({"doc_id": str(row[0]), "title": title_val})
        except Exception:
            pass
        finally:
            db.close()

    # ── 低质量答案场景：优先把已召回 sources 中的真实文档也作为规范提醒候选 ──
    for src in source_docs[:5]:
        title_val = src.get("doc") or src.get("title") or ""
        doc_id_val = src.get("doc_id")
        if title_val and title_val not in seen_titles:
            seen_titles.add(title_val)
            related_docs.append({"doc_id": str(doc_id_val) if doc_id_val else None, "title": title_val})

    # ── 首选改写问题 ──
    # 只有当匹配了规则时才生成具体改写建议；无规则匹配时不构造无意义建议
    refined_query = None
    if matched_rules:
        refined_query = matched_rules[0][2]

    # ── 构建 standard_hints：从 related_docs 提取规范标识，推荐带规范名搜索 ──
    standard_hints = []
    seen_std = set()

    def _doc_priority(doc: dict) -> tuple:
        title = doc.get("title", "")
        normalized = _normalize_doc_title_for_standard(title)
        has_standard_no = 0 if _STD_PATTERN.search(normalized) else 1
        # 标准号文档优先；其次保留原顺序，避免编造相关性
        return (has_standard_no,)

    for doc in sorted(related_docs[:8], key=_doc_priority)[:5]:
        title = doc.get("title", "")
        normalized_title = _normalize_doc_title_for_standard(title)
        # 尝试提取规范标识符（GB/T、STC、DB 等开头的标准号）
        m = _STD_PATTERN.search(normalized_title)
        doc_keyword = _normalize_standard_keyword(m.group(1)) if m else title.split("《")[0].split(" ")[0].strip()[:30] if title else ""
        if not doc_keyword or doc_keyword in seen_std:
            continue
        seen_std.add(doc_keyword)
        # 构建推荐搜索语句：规范标识符 + 改写问题（或原始问题关键词）
        if refined_query:
            recommended = f"{doc_keyword} {refined_query}"
        else:
            kb_first = kb_terms[0] if kb_terms else q[:20]
            recommended = f"{doc_keyword} {kb_first}"
        reason = f"该{doc_keyword}规范包含相关内容，建议带上规范名称搜索，结果更准确"
        standard_hints.append({
            "title": title,
            "doc_id": doc.get("doc_id"),
            "reason": reason,
            "recommended_query": recommended,
        })
    # 仅当规则改写不存在时，才用 standard_hints 的首项作为 refined_query 兜底；
    # 若规则改写存在，保持规则原貌——避免被无关 standard_hints[0] 文档名污染。
    if standard_hints and not refined_query:
        refined_query = standard_hints[0]["recommended_query"]

    # ── 兜底追问 ──
    follow_up_questions = _build_follow_up_questions(q)

    return {
        "refined_query": refined_query,
        "term_hints": term_hints,
        "related_docs": related_docs,
        "standard_hints": standard_hints,
        "follow_up_questions": follow_up_questions,
    }


_AGENT_PREFIX_RE = re.compile(
    r'^\s*\[文档:[^\]]+\](?:\[章节:[^\]]+\])?\s*'
)


def _clean_source_text(text: str) -> str:
    """清洗用于前端来源卡片展示的文本"""
    if not text:
        return ""
    # 1. 剥离 agent 前缀 [文档:xxx][章节:xxx]
    text = _AGENT_PREFIX_RE.sub('', text)
    # 2. 解析 HTML 实体
    text = _html_mod.unescape(text)
    # 3. 清理 Hindsight 元数据
    text = re.sub(r'\s*\|\s*(?:When|Involving|Entities|Location|Type|Source|Confidence):[^|\n]*', '', text)
    # 4. 去掉残留的 HTML 标签
    from app.utils.text_cleaning import clean_html_residuals
    text = clean_html_residuals(text)
    # 5. 规范化空白
    from app.utils.text_cleaning import normalize_whitespace
    text = normalize_whitespace(text)
    # 6. 过滤短垃圾（<50字符）
    if len(text.strip()) < 50:
        return ""
    return text.strip()


async def _generate_answer(
    q: str,
    bank: str,
    bank_prompt: str,
    history: str,
    doc_facts: dict,
    query_keywords: list,
    _tier_extra: list,
    title_map: dict,
    kg_context_text: str = "",
) -> dict:
    """
    生成LLM答案 — 构建上下文 + 组装prompt + LLM调用 + 后处理。

    返回: {"answer": str, "sources": list, "validation_result": dict|None}
    """
    if not doc_facts:
        # T7: 金额类查询跨bank兜底
        if _tier_extra:
            _snippet, _dtitle = _find_rate_table_snippet(_tier_extra, bank)
            if _snippet:
                doc_facts["tier_rate"] = [(_snippet, _dtitle or "费率表", _snippet[:800], None)]
                logger.info("[T7] Early-return inject: %s (%s)", _dtitle, _tier_extra[0])
        if not doc_facts:
            suggestions = _generate_query_suggestions(q, bank, bank_prompt, title_map)
            return {
                "answer": "知识库中未找到直接匹配的内容。可以根据下面的提示换一种问法继续检索。",
                "sources": [],
                "validation_result": None,
                "suggestions": suggestions,
            }

    # ── 批量查询 parent 上下文 ──
    parent_text_cache = {}
    parent_keys_to_fetch = set()
    for doc_id, facts in doc_facts.items():
        for _, _, _, pidx in facts[:3]:
            if pidx is not None:
                parent_keys_to_fetch.add((doc_id, pidx))

    if parent_keys_to_fetch:
        try:
            pdb = SessionLocal()
            for did, pidx in parent_keys_to_fetch:
                row = pdb.execute(
                    sa_text("SELECT parent_text FROM parent_chunks WHERE doc_id=:did AND parent_idx=:pidx"),
                    {"did": did, "pidx": pidx},
                ).fetchone()
                if row:
                    parent_text_cache[(did, pidx)] = row[0]
            pdb.close()
        except Exception as e:
            logger.warning("parent_chunks query failed: %s", e)

    # ── 按文档合并：每个文档取 top-2 fact，拼接 ──
    context_parts = []
    _summary_context_parts = []  # T1-3: 摘要文档的 context 后置
    sources = []
    _summary_doc_ids = set()  # T1-3: 检测为摘要的 doc_id

    for doc_id, facts in doc_facts.items():
        top_facts = facts[:3]
        doc_name = top_facts[0][1]

        # T1-3: 摘要文档检测（取首个 chunk 判断）
        if doc_id not in _summary_doc_ids and top_facts:
            _first_chunk = top_facts[0][0]
            if _is_summary_doc(_first_chunk, doc_name):
                _summary_doc_ids.add(doc_id)

        seen_texts = set()
        fact_summaries = []
        for _, _, cleaned, _ in top_facts:
            key = cleaned[:80]
            if key not in seen_texts:
                seen_texts.add(key)
                fact_summaries.append(cleaned)
        fact_combined = "；".join(fact_summaries) if fact_summaries else ""

        parent_texts_for_doc = []
        seen_parent = set()
        for _, _, _, pidx in top_facts:
            if pidx is not None and (doc_id, pidx) in parent_text_cache:
                pt = parent_text_cache[(doc_id, pidx)]
                if pt[:80] not in seen_parent and pt[:80] not in seen_texts:
                    seen_parent.add(pt[:80])
                    parent_texts_for_doc.append(pt)

        parts = []
        if fact_combined:
            parts.append(f"[摘要] {fact_combined}")
        if parent_texts_for_doc:
            parts.extend(parent_texts_for_doc[:2])
        combined = "\n\n".join(parts) if parts else None
        if not combined:
            continue

        # Phase C1-RPO: 关键词命中密度信号（检索层结构化输出，零 prompt 改动）
        # 让 LLM 感知检索质量 — 检索内容与 query 的关键词重合度
        _kw_signal = ""
        logger.info("[RPO-debug] query_keywords=%s, combined_len=%d", query_keywords[:5] if query_keywords else "EMPTY", len(combined or ""))
        if query_keywords and combined:
            _combined_lower = combined.lower()
            _kw_hits = sum(1 for kw in query_keywords if kw.lower() in _combined_lower)
            _kw_pct = min(_kw_hits / max(len(query_keywords), 1), 1.0)
            _kw_signal = f" (相关度: {int(_kw_pct*100)}% | 关键词匹配: {_kw_hits}/{len(query_keywords)})"
            logger.info("[RPO-kw] doc=%s hits=%d/%d pct=%.0f%%", doc_name[:40], _kw_hits, len(query_keywords), _kw_pct*100)
        # T1-3: 摘要文档标记 + 后置
        _summary_tag = " [摘要概要]" if doc_id in _summary_doc_ids else ""
        _context_entry = f"[来源: {doc_name}{_summary_tag}{_kw_signal}]\n{combined}"
        if doc_id in _summary_doc_ids:
            _summary_context_parts.append(_context_entry)
        else:
            context_parts.append(_context_entry)

        merged_text = "；".join([c for _, _, c, _ in facts[:3]])
        if parent_texts_for_doc:
            parent_preview = "\n\n".join(parent_texts_for_doc[:2])
            if len(parent_preview) > len(merged_text):
                merged_text = parent_preview

        # SourceCard: 取费档位标签检测
        _fee_tier = ""
        _fees = ["取费", "费率", "费用", "收费标准", "概算", "造价", "计价"]
        if any(f in doc_name for f in _fees):
            _fee_tier = "💰 取费"

        # SourceCard: 关键词命中数
        _kw_matches = 0
        if query_keywords:
            _text_lower = (combined or "").lower()
            _kw_matches = sum(1 for kw in query_keywords if kw.lower() in _text_lower)

        snippet = extract_keyword_snippet(merged_text, query_keywords, 1500) if query_keywords else merged_text[:3000]
        doc_rank = list(doc_facts.keys()).index(doc_id) if doc_id in doc_facts else 99
        relevance_score = round(max(0.1, 1.0 - doc_rank * 0.08), 3)
        sources.append({
            "doc": doc_name,
            "doc_id": doc_id if not doc_id.startswith("_notag_") else None,
            "score": relevance_score,
            "chunk": f"{len(facts)} 条相关",
            "text": _clean_source_text(snippet[:3000]),
            "fee_tier": _fee_tier,
            "keyword_matches": _kw_matches,
        })

    # ── T1-3: 摘要文档后置（非摘要在前，摘要在后）──
    context_parts.extend(_summary_context_parts)

    # ── 限制 context 总量 ──
    total_chars = sum(len(p) for p in context_parts)
    if total_chars > 15000:
        kept = []
        chars = 0
        n_docs = len(context_parts)
        per_doc_min = min(1200, 12000 // max(n_docs, 1))
        for p in context_parts:
            if chars + len(p) > 15000:
                if per_doc_min > 0 and len(p) > per_doc_min:
                    kept.append(p[:per_doc_min] + "...")
                    chars += per_doc_min
                break
            kept.append(p)
            chars += len(p)
        context_parts = kept

    context = "\n\n---\n\n".join(context_parts)
    sources = sources[:12]

    # ── [P1] 文档元数据信息卡（独立block，不污染来源标签）──
    # 在 context 中附加每个文档的版本/地域信息，让 LLM 在需要时参考。
    # 设计原则：独立结构化block，不做 inline 标签（避免V8退化）。
    _meta_lines = []
    _doc_ids_meta = list(doc_facts.keys())[:12]
    if _doc_ids_meta:
        try:
            _meta_db = SessionLocal()
            try:
                _placeholders = ",".join(f":d{i}" for i in range(len(_doc_ids_meta)))
                _params = {f"d{i}": d for i, d in enumerate(_doc_ids_meta)}
                _meta_rows = _meta_db.execute(
                    sa_text(f"SELECT doc_id, published_date, geo_scope FROM documents WHERE doc_id IN ({_placeholders})"),
                    _params
                ).fetchall()
                _meta_map = {r[0]: (r[1], r[2]) for r in _meta_rows}
                _meta_lines.append("## 文档信息卡（版本/地域参考）")
                for _d_id in _doc_ids_meta:
                    _d_name = doc_facts[_d_id][0][1] if doc_facts[_d_id] else _d_id
                    _pd, _gs = _meta_map.get(_d_id, (None, None))
                    _parts = []
                    if _pd:
                        _year = str(_pd)[:4]
                        _parts.append(f"{_year}版")
                    if _gs:
                        _parts.append(f"地域:{_gs}")
                    if _parts:
                        _meta_lines.append(f"- {_d_name} ({', '.join(_parts)})")
            finally:
                _meta_db.close()
        except Exception:
            pass
    if _meta_lines:
        context += "\n\n" + "\n".join(_meta_lines)

    # ── Phase C2: Core Claims 速查卡 — 注入命中文档的 concept.summary ──
    # 对每个出现在 doc_facts 中的文档，拉取其 top-3 个有 summary 的 concept，
    # 构建一个"速查卡"段落，让 LLM 在阅读原文 chunks 之前先获得结构化核心事实。
    #
    # Phase F 修复: 速查卡 query-doc 相关度过滤
    # 当 retrieval top-doc 与 query 主题不相关时（BM25 通用词误命中），
    # 速查卡会放大错误——LLM 先读到错误 doc 的 summary 后直接否定。
    # 修复: doc_name 必须包含至少 1 个高信号词才注入速查卡。
    _high_signal_terms = _extract_high_signal_terms(query_keywords)

    core_claims_context = ""
    try:
        cc_db = SessionLocal()
        try:
            cc_parts = []
            _cc_skipped = 0
            for doc_id in list(doc_facts.keys())[:8]:  # 最多 8 个文档
                doc_name = title_map.get(doc_id, doc_id[:50])
                # Phase F: 相关度过滤 — doc_name 必须含至少 1 个 query 高信号词
                if _high_signal_terms:
                    _d_lower = doc_name.lower()
                    if not any(_t in _d_lower for _t in _high_signal_terms):
                        _cc_skipped += 1
                        continue
                rows = cc_db.execute(
                    sa_text(
                        "SELECT title, summary FROM concepts "
                        "WHERE doc_id=:did AND status='active' "
                        "AND summary IS NOT NULL AND summary != '' "
                        "ORDER BY concept_id LIMIT 3"
                    ),
                    {"did": doc_id},
                ).fetchall()
                if not rows:
                    continue
                doc_name = title_map.get(doc_id, doc_id[:50])
                summaries = []
                for title, summary in rows:
                    label = (title or "")[:40]
                    s = (summary or "")[:250]
                    if s:
                        summaries.append(f"  · {label}: {s}")
                if summaries:
                    cc_parts.append(f"[速查卡: {doc_name}]\n" + "\n".join(summaries))
            if cc_parts:
                core_claims_context = (
                    "【知识速查卡 — 以下是从相关文档中提取的核心事实摘要，"
                    "帮助您快速理解文档核心内容后再回答用户问题】\n"
                    + "\n\n".join(cc_parts)
                )
        finally:
            cc_db.close()
    except Exception as e:
        logger.warning("[C2-CoreClaims] Failed to inject core claims: %s", e)

    # ── Phase B #5: KG context 注入 ──
    if kg_context_text:
        context = (
            "【知识图谱关联上下文 — 以下内容来自文档间的引用/继承关系，"
            "可能包含相关但未直接命中的知识点】\n"
            + kg_context_text
            + "\n\n---\n\n"
            + context
        )

    # ── C2 速查卡 注入（最顶层，让 LLM 先读凝练事实） ──
    if core_claims_context:
        context = core_claims_context + "\n\n---\n\n" + context

    # ── T7补充：金额类查询定向注入费率表（仅当 D2-B 未注入时触发）──
    # D2-B 已在 _build_search_context 中用评分感知注入 top-8 fee chunk，
    # 此处只作为兜底：检查 context 中是否已被 D2-B 注入（有 %、费率、计费额等特征），
    # 已注入则跳过 T7 避免重复。
    _has_rate = any(t in p for p in context_parts for t in ["%", "费率", "计费额", "收费基价"])
    if _tier_extra and not _has_rate:
        _snippet, _dtitle = _find_rate_table_snippet(_tier_extra, bank)
        if _snippet:
            _tier_label = _tier_extra[0]
            _inject = f"[来源: {_dtitle}] {_tier_label}\n{_snippet}"
            context = _inject + "\n\n---\n\n" + context
            sources.insert(0, {"doc": _dtitle or "费率表", "chunk": _tier_label, "text": _snippet[:200]})
            logger.info("[T7] Context inject: %s (%s)", _dtitle, _tier_label)

    # ── 追问上下文注入 ──
    history_context = ""
    if history.strip():
        try:
            history_context = (
                f"\n\n【对话历史】\n{history.strip()}\n\n"
                "请结合上述对话历史理解当前问题。如果当前问题是追问，基于历史上下文中断的地方继续回答。"
            )
        except Exception:
            pass

    # ── T7: 金额档位提示 ──
    _tier_hint = ""
    if _tier_extra:
        _tier_hint = (
            "【费用计算引导】\n"
            "本查询涉及具体金额的费用计算，文档中可能包含以下计费方式，"
            "请根据文档原文中的费率表和公式选择正确的计算方法：\n\n"
            "① 直线内插法（设计费、监理费等计费额与收费基价对照表）：\n"
            "   公式：y = y₁ + (x-x₁)/(x₂-x₁) × (y₂-y₁)\n"
            "   其中 (x₁,y₁) 和 (x₂,y₂) 为计费额所在档位上下界及对应的收费基价\n"
            "   示例（原文）：计费额5000万在3000万~5000万档，对应基价103.8万~163.9万\n"
            "\n"
            "② 费率比例法（验收测评费、等保评测费、云平台评测费、政务APP评测费等）：\n"
            "   公式：V = D × g × (1-Z)\n"
            "   其中 D=建设规模（万元），g=费率（%），Z=计费调衡系数（%）\n"
            "   注意：D 的单位是万元，计算结果 V 也是万元\n"
            "\n"
            "③ 阶梯费率法（建设单位管理费等）：\n"
            "   按投资额所在档位，逐档累加计算\n"
            "   示例（原文表5-41）：1000万以下2%，1001~5000万1.5%，5001~10000万1.2%\n"
            "   1000万项目 = 1000×2% = 20万元\n"
            "   5000万项目 = 20 + (5000-1000)×1.5% = 80万元\n"
            "   10000万项目 = 80 + (10000-5000)×1.2% = 140万元\n"
            "\n"
            "④ 固定单价法（源代码审计、安全测评等）：\n"
            "   公式：V = 单价 × 数量 × (1-Z)\n"
            "   或 V = c × (1-Z)（一口价）\n"
            "\n"
            "【核心规则】\n"
            "1. 'X万以下'包含X万本身——例如'100万以下'包含100万元整\n"
            "2. 'X万以上'不包含X万——例如'100万以上'从100.01万开始\n"
            "3. 文档中每个费率表后面通常跟着计算公式和具体算例，\n"
            "   请直接使用文档原公式进行计算，不要自行发明公式\n"
            "4. 如果文档中有示例计算，按照示例的步骤执行\n"
            "5. 必须标注每个关键数字的来源（文档名称+表号）\n"
            "6. 注意区分计费额（计费基数是投资额的一段区间）和直接按投资额×费率\n"
            "7. **费用类型匹配优先于格式便利**：当用户问题含具体费用类型（如\"验收测评费\"）时，必须优先使用名称匹配该费用类型的费率表，即使其他表看起来更简单，不得改用名称不相关的其他计费方式\n"
            "8. 金额覆盖范围不明确时，按【回答原则】第7条处理\n\n"
        )

    # ── 费用规则条件注入：仅当用户问题涉及费用/计费时加载 ──
    _fee_rules = ""
    # Note: q is already decoded by FastAPI Form(), but curl -d raw Chinese
    # can vary by encoding. Use raw q directly (no latin-1 re-encode).
    _d2q_fee = q
    if any(kw in _d2q_fee for kw in [
        "造价", "取费", "费用", "费率", "收费",
        "验收测评", "验收评测", "检测费", "测评费", "评测费",
        "审计费", "管理费", "设计费", "监理费", "招标",
        "等保", "密评", "咨询费",
        "商密", "商用密码", "密码应用",
    ]):
        _fee_rules = (
            "5. **计费类查询强制计算规则**：当「文档内容」中包含费率表（分档百分比/基价表）、计算公式（V=Dxgx(1-Z)/直线内插等）或具体计费数据时，你必须基于文档中的公式和数据执行以下操作：\n"
            "   a. 从文档中找出**名称最匹配**的费率表（如用户问验收测评费 优先找名称含验收测评或验收评测的费率表，不得改用名称不相关的监理费/设计费表）\n"
            "   b. **禁止说未提供、未找到、未单独列出、未直接给出**——只要文档内容中出现了费率表、百分比数值和V=公式，你就必须使用它们进行计算。一句未提供就跳到其他费用类型是严重的错误\n"
            "   c. 如果金额覆盖范围不明确，在结果中标注假设条件，但必须完成计算\n"
            "   d. 常见的4种计费公式必须识别并使用：\u2460直线内插法 y=y1+(x-x1)/(x2-x1)x(y2-y1) \u2461费率比例法 V=Dxgx(1-Z) \u2462阶梯费率法（逐档累加）\u2463固定单价法 V=单价x数量x(1-Z)\n"
            "   e. **D(投资额)≠D(功能点数)**：同一文档中可能同时出现两种D。当用户提供万元金额时，必须使用建设规模D对应的费率和V=Dxgx(1-Z)公式，不得使用功能点数对应的评测系数。功能点数评测系数仅当用户提供了功能点数(FP)时才适用。\n"
            "   f. **含g%和Z%列的表优先**：文档中的费率表（表5-49、5-45、5-47等）即使同一段落出现了功能点数说明，其行数据中的D代表建设规模(万元)。只需将用户金额匹配到对应档位，使用V=Dxgx(1-Z)即可计算。\n"
            "   g. **注意区分\"验收评测费率\"与\"全流程评测费率\"**：表5-49下可能包含两套费率——\n"
            "      - \"验收评测费率表\"：g值约2.8%~3.0%，适用于验收评测场景\n"
            "      - \"全流程评测费率表\"：g值约6%~12%，适用于全流程评测场景\n"
            "      用户问验收评测费时，必须使用\"验收评测费率\"列的数据，不得使用\"全流程评测费率\"（g值过高会导致结果错误）。\n"
        )
        logger.info("[FEE_RULES] Injected fee calculation rules (query contains fee keywords)")

    prompt = f"""{bank_prompt}

【回答原则】
1. 以「文档内容」为主要依据，优先引用文档中的具体内容和数据
2. **多个文档存在矛盾时**：必须同时列出各方说法，各自标注来源文档名称，在报告末尾注明"建议进一步核实"或"建议以最新发布的XXX为准"。绝对禁止：选择其中一个说法忽略其他、自行折中得出文档中不存在的中间值、或只引用文档标题不给出实质差异
3. 每个关键论断标注来源文档名称
4. 可以基于文档内容进行综合推理和归纳总结，但不得编造文档中不存在的具体数字、条款号或标准编号
{_fee_rules}6. **禁止因「文档没有单独成节/专门定义/直接对比」而拒答**：只要同一文档或关联文档中出现了用户所问术语、概念或相关条款的内容，即使没有以"XX的定义""XX与XX的区别""XX的说明"等专门章节形式存在，也必须基于现有内容给出实质性回答：
   a. 用户问A和B的区别 → 文档中有A的条款和B的条款，但没有"AB对比章"→ 必须分别列出A的规定和B的规定，基于差异做对比回答，禁止说"文档没有直接对比"
   b. 用户问A的定义 → 文档在多个条款里提到了A的不同侧面 → 必须汇总拼接成完整描述，禁止说"文档未单独定义"
   c. 用户问A的要求 → 文档相关章节有A的技术参数/安装要求/功能指标 → 必须逐条列出，禁止说"文档未涉及"
   d. **绝对禁止**：说"未找到""未直接命中""未明确定义""没有相关信息""文档未涉及"[术语]——只要chunks中有该关键词命中，就说明文档涉及了该内容

7. 如果文档内容只覆盖了问题的部分方面，先回答已有部分，再说明哪些方面知识库未涉及
8. **用户提问不准确/不规范时的兜底处理**：用户的问题可能使用了口语化、非标准术语或缺少必要限定条件，此时按以下原则处理而非直接拒绝回答：
   a. 术语映射：用户使用口语表述时，自动映射到文档中的标准术语再检索（如"人工测评"→"人工测试"、"价格"→"取费标准"），回答中使用标准术语并在括号中补充用户原文
   b. 条件补全：用户问题缺少关键的限定条件（如只给金额没写是总投资还是软件开发费、只给标准号没写具体条款），基于文档中最可能匹配的场景回答，同时在回答中明确标注"此处假设xxx"让用户确认
   c. 多重理解：当用户问题有多个合理解读时（如"验收测评费"可能指软件验收测评、系统验收评测、等保测评），逐种解读逐一回答，并标注各自的适用场景和文档依据
   d. 宽泛/描述不清问题：当用户问题过于宽泛或缺少关键信息时（如"做一个系统的验收测试多少钱"缺少投资额和系统类型），你必须先将文档中涉及的**可用费用类型和格式**展示给用户，再**必须**在回答末尾用"请问……？"邀请补充。禁止直接说"请明确"。示例：先给出3种场景的结构化说明，然后以「要获得精确结果，请问项目的投资总额和系统类型是什么？我可以据此使用对应的费率表计算。」结尾。

   重要：如果问句中没有具体的金额数字（万元）或系统类型，回答的最后一段必须是邀请补充的话——判断依据是用户问题不包含明确的投资额数字。
   e. **禁止行为**：不得因用户提问不准确而拒绝回答、说"请明确定义"或简单说"未收录"。必须先基于最佳理解给出实质性回答，再附条件说明

【去AI味要求】
你的回答必须像真人撰写的专业报告，严禁以下AI味表达：
- 禁用"综上所述"、"总而言之"、"值得注意的是"——直接写结论或内容
- 禁用"此外"、"另外"——改为具体连接，如"在安全层面"、"从运维角度"
- 禁用"不仅...而且..."——拆为两句或用"同时"
- 禁用"具有重要意义"、"发挥着重要作用"——写清楚具体是什么意义/作用
- 禁用"不断提升"、"日益完善"——写具体提升了多少、完善了什么
- 禁用"相关人员"、"相关部门"——写具体角色/部门名称
- 禁用"在...方面"、"一定程度上"——改为具体场景和程度
- 段落结构要有变化，不要每段都以"首先/其次/最后"开头
- 主语必须明确：每句话的主语是具体角色、系统或部门，不能是"这"、"它"、"该"
- 专业术语全文统一，不要混用同义词

【逻辑校验要求】
回答前必须自查以下逻辑问题：
- 数字一致性：文中所有数字必须与文档来源完全一致，不得四舍五入或估算
- 标准号准确性：引用的GB/T、行业标准编号必须与文档原文一致，不得张冠李戴
- 因果关系：结论必须能从文档内容推导出来，不得过度推断
- 条件限定：文档说"建议"不能写成"要求"，文档说"在X条件下"不能省略条件

基于以下文档内容回答问题：

{_tier_hint}文档内容：
{context}
{history_context}

问题：{q}

请用中文回答，引用具体条款和数据，并标注信息来源。"""

    try:
        answer = await chat([
            {"role": "system", "content": bank_prompt},
            {"role": "user", "content": prompt},
        ])
    except Exception as e:
        answer = f"答案生成失败: {e}"

    # ── 去AI味后处理 + 逻辑校验 ──
    validation_result = None
    suggestions = None
    try:
        original_answer = answer
        answer = deai_postprocess(answer)
        if answer != original_answer:
            logger.info("[DEAI] 去AI味后处理已应用")

        # 始终构建 suggestions，包含常驻兜底建议；低置信答案额外合并完整建议
        suggestions = _suggestions_for_answer(q, bank, bank_prompt, title_map, sources, answer)

        if sources and context:
            validation_result = logic_validate(answer, context, sources)
            if validation_result["issues"]:
                for issue in validation_result["issues"]:
                    logger.info("[LOGIC] %s: %s", issue["severity"].upper(), issue["detail"])
    except Exception as e:
        validation_result = None
        suggestions = _build_persistent_suggestions(q, sources)
        logger.warning("quality-gate 后处理异常: %s", e)

    return {
        "answer": answer,
        "sources": sources,
        "validation_result": validation_result,
        "suggestions": suggestions,
        "kg_context_text": kg_context_text,
    }


def _write_audit_log(request, q: str, answer: str, sources: list, cache_hit: int = 0, reject: str = None):
    """写入审计日志（独立工具函数，供缓存命中路径和主路径共用）"""
    try:
        _auth_header = request.headers.get("Authorization", "")
        _username = "unknown"
        if _auth_header.startswith("Bearer "):
            _u = get_username_from_token(_auth_header[7:])
            if _u:
                _username = _u
        _audit_db = SessionLocal()
        try:
            _audit_db.add(AuditLog(
                user_id=_username,
                query=q,
                answer=answer,
                sources=json.dumps(sources, ensure_ascii=False)[:2000] if sources else None,
                cache_hit=cache_hit,
                rejected=reject,
            ))
            _audit_db.commit()
        except Exception:
            pass
        finally:
            _audit_db.close()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# 置信度评估
# ═══════════════════════════════════════════════════════════════════════


def _assess_recall_confidence(
    ctx: dict,
    q: str,
    query_keywords: list,
    session_doc_ids: set = None,
    is_multi_turn: bool = False,
) -> dict | None:
    """三级门控置信度评估。

    Args:
        ctx: _build_search_context() 返回值
        q: 原始查询
        query_keywords: 查询关键词列表

    Returns:
        None 表示通过门控（可以继续生成答案）；
        dict 表示拒绝，格式: {"reject_type": str, "message": str}
    """
    if not settings.confidence_reject_enabled:
        return None

    doc_facts = ctx.get("doc_facts", {}) or {}
    source_count = len(doc_facts)
    # ── Level 1: doc_facts 为空 → 直接拒答 ──
    if source_count <= settings.confidence_reject_threshold_l1:
        logger.info(
            "[CONFIDENCE] Level 1 reject: source_count=%d (threshold=%d)",
            source_count,
            settings.confidence_reject_threshold_l1,
        )
        return {
            "reject_type": "knowledge_gap",
            "message": _REJECT_MSG_KNOWLEDGE_GAP,
        }

    # ── Level 1.5: 内容实质性检测 ──
    # 检测 top-k chunk 的文本是否包含实质性条款内容，
    # 而非仅引用/提及（如"按GB 50058的规定"但没有具体技术条款）
    if source_count > 0:
        _all_chunk_texts = []
        for doc_fact_list in doc_facts.values():
            for fact in doc_fact_list:
                text = fact[0] if isinstance(fact, (list, tuple)) and len(fact) > 0 else ""
                if text:
                    _all_chunk_texts.append(text)

        # 取前5个chunk的文本做检测（匹配度最高的chunk）
        _combined_chunks = " ".join(_all_chunk_texts[:5]).lower()

        # 检测是否是纯引用模式：包含"按XX标准"句式但无具体条款内容
        # 标准引用句式信号
        _has_citation_pattern = bool(re.search(
            r'(按|根据|按照|参照|引用|符合|采用)(?:.{0,30}?)(?:标准|规范|规程|导则|指南|要求)',
            _combined_chunks
        ))
        # 实质性条款内容信号
        _substance_re = re.compile(
            r"(?:第[0-9零一二三四五六七八九十百千]+[条章节款]|"
            r"(?:[0-9]+[.][0-9]+(?:[.][0-9]+)?[条款]|"
            r"(?:[0-9.]+(?:℃|mm|kV|m2|%|Pa|Hz|Ω|V|A|W))|"
            r"(?:应符合|不应小于|不得大于|必须设置|应满足)))"
        )
        _has_substantive_content = bool(_substance_re.search(_combined_chunks))

        if _has_citation_pattern and not _has_substantive_content:
            # 精确匹配 bypass：如果查询的标准号直接在文档标题中 → 文档确在KB内，跳过 L1.5
            q_lower = q.lower()
            _has_exact_doc_match = False
            for doc_fact_list in doc_facts.values():
                for fact in doc_fact_list:
                    doc_name = fact[1] if isinstance(fact, (list, tuple)) and len(fact) > 1 else ""
                    if doc_name and (q_lower in doc_name.lower() or doc_name.lower() in q_lower):
                        _has_exact_doc_match = True
                        break
                if _has_exact_doc_match:
                    break
            if not _has_exact_doc_match:
                # 只引用了标准名但无实质条款 → 属于"文档中提及但未包含正文"模式
                logger.info(
                    "[CONFIDENCE] Level 1.5 substance gate: citation pattern without content, no exact doc match (q=%s, source_count=%d)",
                    q, source_count,
                )
                return {
                    "reject_type": "low_coverage",
                    "message": _REJECT_MSG_LOW_COVERAGE,
                }

    if not is_multi_turn:
        _location_pattern = re.compile(
            r'(?:[^\s]{1,5}[省市区域]|'
            r'广州|北京|深圳|上海|浙江|杭州|东莞|佛山|南沙|珠海|中山|'
            r'江苏|南京|四川|成都|湖北|武汉|福建|厦门|天津|重庆)'
        )
        _query_locations = _location_pattern.findall(q)
        _en_locations = ['gdpr', 'european', 'california', 'new york', 'london', 'tokyo']
        _query_locations += [loc for loc in _en_locations if loc in q.lower()]

        if _query_locations:
            _doc_names_lower = set()
            for doc_fact_list in doc_facts.values():
                for fact in doc_fact_list:
                    doc_name = fact[1] if isinstance(fact, (list, tuple)) and len(fact) > 1 else ""
                    if doc_name:
                        _doc_names_lower.add(doc_name.lower())
            _doc_names_text = " ".join(_doc_names_lower)
            _has_any_location = False
            for loc in _query_locations:
                if loc.lower() in _doc_names_text:
                    _has_any_location = True
                    break
            if not _has_any_location:
                # 检查 chunk_text 正文（标题不含地点但正文可能包含）
                _all_chunk_texts_body = " ".join([
                    fact[0] for doc_fact_list in doc_facts.values()
                    for fact in doc_fact_list
                    if isinstance(fact, (list, tuple)) and len(fact) > 0 and fact[0]
                ]).lower()
                for loc in _query_locations:
                    if loc.lower() in _all_chunk_texts_body:
                        _has_any_location = True
                        break
            if not _has_any_location:
                logger.info(
                    "[CONFIDENCE] Level 2 location mismatch: q_locations=%s not in docs",
                    _query_locations,
                )
                return {
                    "reject_type": "low_coverage",
                    "message": _REJECT_MSG_LOW_COVERAGE,
                }

    # ── 域锁定状态：跳过 L2 coverage 检查（模糊追问在域锁定下覆盖率低是正常的）──
    if session_doc_ids:
        return None

    # ── Level 2: 召回极少或质量差 → 计算覆盖率和精确匹配 ──
    # coverage: 顶部的 top-K chunk 中关键词覆盖率（避免跨文档碎片拼凑）
    all_texts = []
    for doc_fact_list in doc_facts.values():
        for fact in doc_fact_list:
            text = fact[0] if isinstance(fact, (list, tuple)) and len(fact) > 0 else ""
            all_texts.append(text)

    # 只看 top-3 chunk 的联合文本（最高质量的部分）
    top_texts = all_texts[:3]
    combined_text = " ".join(top_texts).lower()

    kw_match_count = sum(1 for kw in query_keywords if kw.lower() in combined_text)
    coverage = kw_match_count / max(len(query_keywords), 1)

    # 是否包含精确匹配（查询标准号在文档名称中）
    q_lower = q.lower()
    has_exact_match = False
    for doc_fact_list in doc_facts.values():
        for fact in doc_fact_list:
            doc_name = fact[1] if isinstance(fact, (list, tuple)) and len(fact) > 1 else ""
            if q_lower in doc_name.lower() or doc_name.lower() in q_lower:
                has_exact_match = True
                break
        if has_exact_match:
            break

    # B02 强化: 如果 source_count 很高（≥3）但关键词密度低（<0.3），降级拒答
    # 场景：有很多文档匹配查询词，但只是引用/提及，没有具体技术内容
    if source_count >= 3 and coverage < 0.3 and not has_exact_match:
        logger.info(
            "[CONFIDENCE] Level 2 keyword density reject: source_count=%d, coverage=%.2f, kw=%d",
            source_count, coverage, len(query_keywords),
        )
        return {
            "reject_type": "low_coverage",
            "message": _REJECT_MSG_LOW_COVERAGE,
        }

    # 混合拒答条件: source_count 少 OR 覆盖率低 → 拒答
    if (
        source_count < 2
        or (coverage < settings.confidence_reject_threshold_l2_coverage and not has_exact_match)
    ):
        logger.info(
            "[CONFIDENCE] Level 2 reject: source_count=%d, coverage=%.2f, exact_match=%s",
            source_count,
            coverage,
            has_exact_match,
        )
        return {
            "reject_type": "low_coverage",
            "message": _REJECT_MSG_LOW_COVERAGE,
        }

    return None


# ═══════════════════════════════════════════════════════════════════════
# API 端点
# ═══════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════


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
