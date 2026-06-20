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
import logging
import os
import re
from collections import defaultdict

from fastapi import APIRouter, Form, HTTPException
from sqlalchemy import text as sa_text

from app.models.database import SessionLocal
from app.services.cache_service import (
    get_exact as cache_get_exact,
    get_semantic as cache_get_semantic,
    set_cache as cache_set,
)
from app.services.generation import chat, logic_validate
from app.services.retrieval import (
    BANKS,
    _get_active_hindsight_banks,
    _find_rate_table_snippet,
    bm25_search,
    build_bm25_index,
    expand_query_synonyms,
    keyword_rerank,
    llm_rerank,
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

logger = logging.getLogger(__name__)

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════
# 核心子函数
# ═══════════════════════════════════════════════════════════════════════


async def _build_search_context(
    q: str,
    bank: str,
    history: str,
    use_rerank: bool,
    hs_bank: str,
    q_recalled: str,
    q_bm25: str,
    query_keywords: list,
    _tier_extra: list,
    kg_info: dict,
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
        rows = db.execute(sa_text("SELECT doc_id, bank, title FROM documents")).fetchall()
        bank_map = {r[0]: r[1] for r in rows}
        title_map = {r[0]: (r[2] or "") for r in rows}
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
                sa_text(f"SELECT doc_id, title FROM documents WHERE {conditions}"),
                params,
            ).fetchall()
        finally:
            db.close()

        for tr in title_rows:
            if bank != "all" and bank_map.get(tr[0]) != bank:
                continue
            if bank_map.get(tr[0]) == "skip":
                continue
            targeted = await recall(tr[1], limit=2, bank=hs_bank)
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
                        targeted = await recall(best_doc[1][:50], limit=3, bank=hs_bank)
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
            if bm25_hits:
                bm25_merged = rrf_merge(raw_results, bm25_hits, k=60, query_keywords=query_keywords, bank=bank)
    except Exception as e:
        logger.warning("BM25 fallback: %s", e)

    # ── 短摘要检测：从 parent_chunks 取回原文 ──
    try:
        _pdb = SessionLocal()
        for _ri, _r in enumerate(raw_results[:30]):
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
                    raw_results[_ri] = {**_r, "text": _full_text}
        _pdb.close()
    except Exception as e:
        logger.warning("short summary enrichment failed: %s", e)

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

    # ── 轻量级关键词 Rerank（在 LLM Rerank 之前） ──
    if len(all_results) > 3:
        all_results = keyword_rerank(q, all_results, top_k=20)

    # ── LLM Rerank精排 ──
    if use_rerank and len(all_results) > 2:
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
    # 如果有 standard_hints，把首选 refined_query 升级为带规范名的搜索
    if standard_hints and refined_query:
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


async def _generate_answer(
    q: str,
    bank: str,
    bank_prompt: str,
    history: str,
    doc_facts: dict,
    query_keywords: list,
    _tier_extra: list,
    title_map: dict,
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
    sources = []

    for doc_id, facts in doc_facts.items():
        top_facts = facts[:3]
        doc_name = top_facts[0][1]

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

        context_parts.append(f"[来源: {doc_name}]\n{combined}")

        merged_text = "；".join([c for _, _, c, _ in facts[:3]])
        if parent_texts_for_doc:
            parent_preview = "\n\n".join(parent_texts_for_doc[:2])
            if len(parent_preview) > len(merged_text):
                merged_text = parent_preview

        snippet = extract_keyword_snippet(merged_text, query_keywords, 1500) if query_keywords else merged_text[:3000]
        doc_rank = list(doc_facts.keys()).index(doc_id) if doc_id in doc_facts else 99
        relevance_score = round(max(0.1, 1.0 - doc_rank * 0.08), 3)
        sources.append({
            "doc": doc_name,
            "doc_id": doc_id if not doc_id.startswith("_notag_") else None,
            "score": relevance_score,
            "chunk": f"{len(facts)} 条相关",
            "text": snippet[:3000],
        })

    # ── 限制 context 总量 ──
    total_chars = sum(len(p) for p in context_parts)
    if total_chars > 10000:
        kept = []
        chars = 0
        n_docs = len(context_parts)
        per_doc_min = min(800, 8000 // max(n_docs, 1))
        for p in context_parts:
            if chars + len(p) > 10000:
                if per_doc_min > 0 and len(p) > per_doc_min:
                    kept.append(p[:per_doc_min] + "...")
                    chars += per_doc_min
                break
            kept.append(p)
            chars += len(p)
        context_parts = kept

    context = "\n\n---\n\n".join(context_parts)
    sources = sources[:12]

    # ── T7补充：金额类查询定向注入费率表 ──
    _has_rate = any(t in p for p in context_parts for t in ["3%", "3\\"])
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
            "【重要提示】本查询涉及具体金额的费用计算。文档中可能包含按投资总额分档的费率表"
            "（如100万以下、100万~300万、300万以上等不同档位的费率），请优先查找并引用费率表中的具体百分比，"
            "而不是自行估算。关键规则：1) 'X万以下'包含X万本身——例如'100万以下'包含100万元整，应使用该档位费率；"
            "2) 必须精确匹配金额所属档位——例如查询金额为'100万'时，应使用'100万以下'档位的费率（3%），"
            "绝不能错用'100万~300万'档位的费率（4%）。\n\n"
        )

    prompt = f"""{bank_prompt}

【回答原则】
1. 以「文档内容」为主要依据，优先引用文档中的具体内容和数据
2. 可以基于文档内容进行综合推理和归纳总结，但不得编造文档中不存在的具体数字、条款号或标准编号
3. 每个关键论断标注来源文档名称
4. 重要：如果下面的「文档内容」中已经包含与问题相关的段落、条款或数据，你必须基于这些内容回答，绝不能说"未收录""未找到"。只有当文档内容与问题完全无关（没有任何段落涉及问题主题）时，才可以说"未收录"
5. 多个文档存在矛盾时，列出不同说法并各自标注来源
6. 如果文档内容只覆盖了问题的部分方面，先回答已有部分，再说明哪些方面知识库未涉及

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
    }


# ═══════════════════════════════════════════════════════════════════════
# API 端点
# ═══════════════════════════════════════════════════════════════════════


@router.post("")
async def query(
    q: str = Form(...),
    bank: str = Form("all"),
    history: str = Form(""),
    rerank: str = Form("false"),
    nocache: str = Form(""),
):
    """搜索知识库 → 召回 → DeepSeek 合成答案（支持多 bank）"""
    if not q.strip():
        raise HTTPException(400, "问题不能为空")

    # bank 白名单校验
    if bank not in BANKS:
        valid = list(BANKS.keys())
        raise HTTPException(400, f"未知 bank '{bank}'，可选: {valid}")

    # T6: 标准号规范化
    q = normalize_standard_numbers(q)

    # ── 缓存命中检查（L1精确 + L2语义）──
    if not nocache:
        try:
            cached = cache_get_exact(q, bank)
            if cached:
                logger.info("[CACHE] L1 exact hit for: %s", q[:50])
                return {
                    "answer": cached["answer"],
                    "sources": cached["sources"],
                    "cache_hit": "exact",
                    "suggestions": _build_persistent_suggestions(q, cached["sources"]),
                }
            cached = await cache_get_semantic(q, bank)
            if cached:
                logger.info("[CACHE] L2 semantic hit for: %s", q[:50])
                return {
                    "answer": cached["answer"],
                    "sources": cached["sources"],
                    "cache_hit": "semantic",
                    "similarity": cached.get("similarity"),
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
    query_keywords_raw = [w for w in _jieba_mod.cut(q_recalled) if len(w.strip()) > 1]
    query_keywords = expand_keywords(query_keywords_raw)
    if _tier_extra:
        query_keywords = list(set(query_keywords + _tier_extra))

    # ── 确定是否使用 rerank ──
    use_rerank = rerank.lower() == "true" or (bank == "checklist")

    # ── Phase 1: 构建搜索上下文 ──
    ctx = await _build_search_context(
        q=q, bank=bank, history=history,
        use_rerank=use_rerank, hs_bank=hs_bank,
        q_recalled=q_recalled, q_bm25=q_bm25,
        query_keywords=query_keywords, _tier_extra=_tier_extra,
        kg_info=kg_info,
    )

    # ── Phase 2: 生成答案 ──
    gen = await _generate_answer(
        q=q, bank=bank, bank_prompt=bank_prompt,
        history=history,
        doc_facts=ctx["doc_facts"],
        query_keywords=ctx["query_keywords"],
        _tier_extra=ctx["_tier_extra"],
        title_map=ctx["title_map"],
    )

    answer = gen["answer"]
    sources = gen["sources"]
    validation_result = gen["validation_result"]
    suggestions = gen.get("suggestions")

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
    return result


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
