"""Retrieval service — Dense + BM25 + RRF merge + Rerank.

Ported from: kb-web server.py expand_query_synonyms() L398-L427,
             build_bm25_index() L1425-L1528, bm25_search() L1529-L1549,
             rrf_merge() L1550-L1653, llm_rerank() L1655-L1715,
             recall() L1716-L1771, _find_rate_table_snippet() L2630-L2674
"""

import asyncio
import json
import logging
import re
import time as _time
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple

import httpx
import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import text

from app.config import settings
from app.models.database import SessionLocal
from app.services.cache_service import _bm25_caches, _get_bm25_cache, _BM25_TTL
from app.utils.tokenizer import tokenize, expand_keywords
from app.utils.text_cleaning import normalize_query, expand_amount_tiers

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── Bank 配置 ─────────────────────────────────────────────────────
_HARDCODED_BANKS = {
    "all":           {"name": "全部",           "hindsight": None,         "prompt": "通用政务信息化知识库"},  # [P0-2] 聚合查询，无专属hindsight bank
    "project_docs":  {"name": "项目资料",       "hindsight": "kb_project", "prompt": "你是政务信息化项目管理专家。熟悉项目管理办法、验收管理细则、财政投资规定、软件行业基准数据。回答时注重管理流程、审批要求和实操经验。"},
    "standards":     {"name": "规范",           "hindsight": "kb_standard","prompt": "你是政务信息化标准规范专家。精通GB/GA/T/EGAG/GDZW等国家及团体标准，覆盖等保测评、密码应用、监理服务、立项咨询、验收测评、会议系统、安防工程、数据中心等领域。回答时注重条款引用和合规要求。"},
    "industry_docs": {"name": "信息化行业文档", "hindsight": "kb_industry","prompt": "你是政务信息化行业专家。熟悉电子政务工程造价、软件造价评估、信创替代、验收测评实务、行业政策解读。回答时注重实操经验和行业惯例。"},
    "templates":     {"name": "方案模板",       "hindsight": "kb_template","prompt": "你是政务信息化项目方案编写专家。精通建设开发类和运维服务类项目方案的编写规范、章节结构、技术路线选型。回答时注重模板结构和编写要点。"},
    "tech_guides":   {"name": "技术指导书",     "hindsight": "kb_tech",    "prompt": "你是全栈技术专家。精通前端/后端/Agent/DevOps/安全/渗透测试/AI/LLM。回答注重实战经验、架构设计和攻防思路。"},
    "general":       {"name": "综合文件",       "hindsight": "kb_general", "prompt": "你是知识管理助手。擅长整理归纳各类知识，回答清晰有条理。"},
    "checklist":    {"name": "检查标准",       "hindsight": "kb_checklist", "prompt": "你是等保测评机构检查标准专家。回答时优先引用检查项、检查要求、检查方法、核查力度等表格字段。"},
    "xhs":          {"name": "小红书技术",     "hindsight": "kb_xhs",      "prompt": "你是互联网产品与技术内容分析专家。精通互联网产品评测、AI/Agent/DevOps 工具体验、技术趋势解读。回答时注重产品能力边界、真实体验和对比分析。善于从社区内容中提炼有实操价值的手法、技巧和避坑建议。"},
    "business":     {"name": "商业分析",       "hindsight": "kb_general",  "prompt": "你是商业与技术分析专家。精通AI产品评测、技术趋势分析、量化交易、金融知识。回答注重技术能力边界、实践经验和中立对比。"},
    "methodology":  {"name": "方法论",          "hindsight": "kb_general",  "prompt": "你是知识管理方法论专家。精通OKF知识组织框架、知识库设计、信息架构、SOP编写。回答注重结构化方法和最佳实践。"},
}
BANKS = dict(_HARDCODED_BANKS)


def _normalize_bank_config(raw: dict) -> dict:
    normalized = {}
    for key, cfg in (raw or {}).items():
        if not isinstance(cfg, dict):
            continue
        item = dict(cfg)
        if "label" in item and "name" not in item:
            item["name"] = item.pop("label")
        if "name" not in item:
            item["name"] = key
        if key != "all" and not item.get("hindsight"):
            item["hindsight"] = f"kb_{key}"
        if "prompt" not in item:
            item["prompt"] = f"你是{item['name']}领域专家。"
        normalized[key] = item
    return normalized


def _load_bank_overrides() -> dict:
    cfg_path = settings.banks_config_path
    if not cfg_path.exists():
        return {}
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return _normalize_bank_config(json.load(f))
    except Exception as e:
        logger.warning("Failed to load bank overrides from %s: %s", cfg_path, e)
        return {}


def reload_bank_config() -> dict:
    BANKS.clear()
    BANKS.update(_HARDCODED_BANKS)
    BANKS.update(_load_bank_overrides())
    return BANKS


reload_bank_config()

# ── Active Hindsight banks 缓存 ────────────────────────────────────
_active_hs_banks_cache = {"banks": None, "ts": 0}
_ACTIVE_HS_BANKS_TTL = 300  # 5 minutes

# ── 同义词缓存 ─────────────────────────────────────────────────────
_synonym_cache = {"rows": [], "ts": 0}
_SYNONYM_TTL = 300  # 5 min


def get_bank_config(bank_key: str) -> dict:
    """获取 bank 配置，不存在则返回默认"""
    if bank_key not in BANKS:  # [P0-3] 未知bank警告
        logger.warning("Unknown bank '%s', valid: %s", bank_key, list(BANKS.keys()))
    return BANKS.get(bank_key, BANKS["all"])


# ── Hindsight HTTP helper ──────────────────────────────────────────
async def _hindsight_request(endpoint: str, method: str = "GET", json_data: dict = None, timeout: int = 30) -> dict:
    """调用 Hindsight API"""
    hs_url = settings.hindsight_url
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            if method == "POST":
                resp = await client.post(f"{hs_url}{endpoint}", json=json_data)
            elif method == "DELETE":
                resp = await client.delete(f"{hs_url}{endpoint}")
            else:
                resp = await client.get(f"{hs_url}{endpoint}")
        except httpx.TimeoutException:
            raise Exception(f"Hindsight {method} {endpoint}: 请求超时（{timeout}s）")
        except httpx.ConnectError:
            raise Exception(f"Hindsight {method} {endpoint}: 无法连接（服务未启动？）")
        except Exception as e:
            raise Exception(f"Hindsight {method} {endpoint}: 网络异常: {e}")

        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("detail", "")
            except Exception:
                pass
            detail = detail or resp.text[:200] or f"HTTP {resp.status_code}"
            raise Exception(f"Hindsight {method} {endpoint} returned {resp.status_code}: {detail}")
        try:
            return resp.json()
        except Exception:
            raise Exception(f"Hindsight {method} {endpoint}: 响应不是有效 JSON: {resp.text[:200]}")


async def _get_active_hindsight_banks(min_docs: int = 1) -> list:
    """Discover which Hindsight banks have documents. Returns list of bank_ids."""
    now = _time.time()
    if _active_hs_banks_cache["banks"] and (now - _active_hs_banks_cache["ts"]) < _ACTIVE_HS_BANKS_TTL:
        return _active_hs_banks_cache["banks"]

    try:
        result = await _hindsight_request("/v1/default/banks", timeout=10)
        banks_data = result.get("banks", [])
        active = [b["bank_id"] for b in banks_data if b.get("fact_count", 0) >= min_docs]
        if not active:
            active = ["kb"]  # fallback
        _active_hs_banks_cache["banks"] = active
        _active_hs_banks_cache["ts"] = now
        logger.info("Active Hindsight banks: %s", active)
        return active
    except Exception as e:
        logger.warning("Failed to discover Hindsight banks: %s", e)
        return ["kb"]  # fallback


# ── LLM Chat helper (for rerank; will be replaced by generation.py in Batch 5) ──
async def _llm_chat(messages: list, stream: bool = False, max_retries: int = 3) -> str:
    """调用 LLM Chat API（带 429 重试）"""
    if not settings.llm_base_url or not settings.llm_api_key:
        raise ValueError("LLM_BASE_URL 或 LLM_API_KEY 未配置（.env）")
    llm_base_url = settings.llm_base_url
    llm_api_key = settings.llm_api_key
    llm_model = settings.llm_model

    last_error = None
    for attempt in range(max_retries):
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {llm_api_key}"},
                json={
                    "model": llm_model,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 3000,
                    "stream": stream,
                },
                timeout=120,
            )
            if stream:
                return resp

            # 429 限流 → 等待重试
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 5 * (attempt + 1)))
                logger.warning("llm_chat: 429 限流, 第%d次重试, 等待 %ds", attempt + 1, retry_after)
                await asyncio.sleep(retry_after)
                continue

            data = resp.json()
            # mimo API 容错：choices 字段缺失或格式异常时返回错误信息而非抛异常
            choices = data.get("choices")
            if not choices:
                error_info = data.get("error", {})
                error_msg = error_info.get("message", "") if isinstance(error_info, dict) else str(error_info)
                error_code = error_info.get("code", "") if isinstance(error_info, dict) else ""
                # 429 也可能在 JSON body 中而非 HTTP status
                if error_code == "429" or "limit" in error_msg.lower():
                    wait = 5 * (attempt + 1)
                    logger.warning("llm_chat: rate limit in body, 第%d次重试, 等待 %ds", attempt + 1, wait)
                    await asyncio.sleep(wait)
                    continue
                logger.warning("llm_chat: LLM API 无 choices. status=%d error=%s", resp.status_code, error_msg)
                raise ValueError(f"LLM API 返回异常: {error_msg or resp.text[:200]}")
            try:
                content = choices[0]["message"]["content"]
                # reasoning model: content 可能为空，检查 reasoning_content
                if not content and choices[0]["message"].get("reasoning_content"):
                    content = choices[0]["message"]["reasoning_content"]
                return content or "（模型返回空内容）"
            except (KeyError, IndexError, TypeError) as e:
                logger.warning("llm_chat: choices 格式异常: %s", e)
                raise ValueError(f"LLM API choices 格式异常: {e}")

    raise ValueError(f"LLM API 重试 {max_retries} 次后仍失败: {last_error or 'rate limit'}")


# ═══════════════════════════════════════════════════════════════════
# 同义词扩展
# ═══════════════════════════════════════════════════════════════════

def expand_query_synonyms(q: str) -> str:
    """D8: 术语同义词扩展——在查询前注入相关术语提升召回率"""
    try:
        now = _time.time()
        if now - _synonym_cache["ts"] > _SYNONYM_TTL:
            db = SessionLocal()
            try:
                _synonym_cache["rows"] = db.execute(
                    text("SELECT term, expansion FROM synonym_map")
                ).fetchall()
                _synonym_cache["ts"] = now
            finally:
                db.close()
        rows = _synonym_cache["rows"]
        if not rows:
            return q
        expansions = set()
        q_lower = q.lower()
        for r in rows:
            term = r[0]  # term
            expansion = r[1]  # expansion
            # Use word boundary matching to avoid false positives (e.g. "GB" matching "RGB")
            if re.search(r'(?<![A-Za-z])' + re.escape(term) + r'(?![A-Za-z])', q_lower, re.IGNORECASE):
                if expansion.lower() not in q_lower:
                    expansions.add(expansion)
        if expansions:
            q = q + " " + " ".join(expansions)
        return q
    except Exception:
        return q


# ═══════════════════════════════════════════════════════════════════
# 语义召回
# ═══════════════════════════════════════════════════════════════════

async def recall(query: str, limit: int = 5, bank: str = "kb", max_tokens: int = 4096,
                  max_chunks_per_doc: int = 8) -> list:
    """语义召回 — 支持多 bank 映射和并行查询

    max_chunks_per_doc: 每个文档最多保留的 chunk 数（默认 8），防止单文档淹没结果
    """
    # 1. Resolve frontend bank key → Hindsight bank name
    #    兼容：调用方可能传前端 key（industry_docs）或 Hindsight 名（kb_industry）
    bank_cfg = BANKS.get(bank, {})
    if not bank_cfg:
        # 传入的是 Hindsight bank 名，反查前端 key
        _reverse_map = {v.get("hindsight"): k for k, v in BANKS.items() if v.get("hindsight")}
        frontend_key = _reverse_map.get(bank)
        if frontend_key:
            bank_cfg = BANKS.get(frontend_key, {})
    hs_bank = bank_cfg.get("hindsight")

    # 2. "all" or "kb" (legacy) → query all active Hindsight banks in parallel
    if bank in ("all", "kb") or not hs_bank:
        active_banks = await _get_active_hindsight_banks()

        per_bank_limit = max(limit // len(active_banks), 10)

        async def _recall_one(hs: str):
            try:
                r = await _hindsight_request(
                    f"/v1/default/banks/{hs}/memories/recall",
                    "POST",
                    {"query": query, "max_tokens": max_tokens, "limit": per_bank_limit},
                    timeout=15,  # Reduced from 30s to prevent long waits
                )
                return r.get("results", [])
            except Exception as e:
                logger.warning("recall(%s) failed: %s", hs, e)
                return []

        tasks = [_recall_one(hs) for hs in active_banks]
        all_lists = await asyncio.gather(*tasks, return_exceptions=True)
        merged = []
        seen = set()
        doc_counts = {}
        for lst in all_lists:
            if isinstance(lst, Exception):
                logger.warning("recall task exception: %s", lst)
                continue
            for r in lst:
                key = r.get("text", "")[:80]
                if key not in seen:
                    # per-doc 限制
                    doc_id = None
                    for t in r.get("tags", []):
                        if t.startswith("doc_id:"):
                            doc_id = t[7:]
                            break
                    if doc_id:
                        if doc_counts.get(doc_id, 0) >= max_chunks_per_doc:
                            continue
                        doc_counts[doc_id] = doc_counts.get(doc_id, 0) + 1
                    seen.add(key)
                    merged.append(r)
        return merged[:limit]

    # 3. Specific bank → use resolved Hindsight bank name
    result = await _hindsight_request(
        f"/v1/default/banks/{hs_bank}/memories/recall",
        "POST",
        {"query": query, "max_tokens": max_tokens, "limit": limit},
    )
    results = result.get("results", [])
    # per-doc 限制
    if results and max_chunks_per_doc > 0:
        _dc_raw = {}
        _filtered = []
        for _r in results:
            _did = None
            for _t in _r.get("tags", []):
                if _t.startswith("doc_id:"):
                    _did = _t[7:]
                    break
            if _did:
                if _dc_raw.get(_did, 0) >= max_chunks_per_doc:
                    continue
                _dc_raw[_did] = _dc_raw.get(_did, 0) + 1
            _filtered.append(_r)
        results = _filtered
    return results


# ═══════════════════════════════════════════════════════════════════
# BM25 索引构建与搜索
# ═══════════════════════════════════════════════════════════════════

async def build_bm25_index(bank: str = "all") -> tuple:
    """构建 BM25 索引（多 bank 独立缓存）。主来源：meta.db parent_chunks（原始文档文本）"""
    now = _time.time()
    cache = _get_bm25_cache(bank)
    # ── 增量检测：TTL 未过期 + 最后更新时间未变 → 跳过重建 ──
    if cache["index"] and (now - cache["ts"]) < _BM25_TTL:
        try:
            _count_db = SessionLocal()
            if bank == "all":
                row = _count_db.execute(text("SELECT MAX(updated_at), COUNT(*) FROM documents WHERE searchable=1 AND status='active'")).fetchone()
            else:
                row = _count_db.execute(text("SELECT MAX(updated_at), COUNT(*) FROM documents WHERE searchable=1 AND status='active' AND bank=:bank"), {"bank": bank}).fetchone()
            _count_db.close()
            current_ts = str(row[0]) if row and row[0] else ""
            current_count = row[1] if row else 0
            cached_ts = cache.get("updated_at", "")
            if current_ts == cached_ts and current_count == cache.get("doc_count", 0):
                return cache["index"], cache["docs"]
            else:
                logger.info("BM25: docs changed (ts=%s→%s, count=%d→%d), rebuilding bank=%s",
                           cached_ts[:19], current_ts[:19], cache.get("doc_count", 0), current_count, bank)
        except Exception:
            pass  # 检测失败时正常走重建流程

    docs = []
    seen_texts = set()

    # ── 主来源: meta.db parent_chunks (原始文档文本，关键词密度高) ──
    try:
        pdb = SessionLocal()
        if bank == "all":
            rows = pdb.execute(text("""
                SELECT p.doc_id, p.parent_text, d.title
                FROM parent_chunks p
                JOIN documents d ON p.doc_id = d.doc_id
                WHERE length(p.parent_text) > 50
                  AND d.searchable = 1
                  AND d.status = 'active'
            """)).fetchall()
        else:
            bank_cfg = get_bank_config(bank)
            rows = pdb.execute(text("""
                SELECT p.doc_id, p.parent_text, d.title
                FROM parent_chunks p
                JOIN documents d ON p.doc_id = d.doc_id
                WHERE length(p.parent_text) > 50
                  AND d.bank = :bank
                  AND d.searchable = 1
                  AND d.status = 'active'
            """), {"bank": bank}).fetchall()
        pdb.close()

        added = 0
        for row in rows:
            parent_text = row[1] or ""
            if not parent_text.strip():
                continue
            dedup_key = parent_text[:80]
            if dedup_key in seen_texts:
                continue
            seen_texts.add(dedup_key)
            docs.append({"text": parent_text, "doc_id": row[0], "tags": [f"title:{row[2] or 'unknown'}"]})
            added += 1
        if added:
            logger.info("BM25: +%d parent_chunks from meta.db (primary source)", added)
    except Exception as e:
        logger.warning("BM25 parent_chunks failed: %s", e)

    # ── Fallback: Hindsight recall (仅当 parent_chunks 为空时) ──
    recall_queries = []
    if not docs:
        try:
            recall_queries = ["标准 规范", "安全 系统", "检测 验收"]
            if bank != "all":
                bank_cfg = get_bank_config(bank)
                hs_bank_for_bm25 = bank_cfg.get("hindsight") or "kb"
                bm25_hs_banks = [hs_bank_for_bm25] if hs_bank_for_bm25 else []
            else:
                bm25_hs_banks = await _get_active_hindsight_banks()
            tasks = []
            for q in recall_queries:
                for hs_bank in bm25_hs_banks:
                    tasks.append(recall(q, limit=200, bank=hs_bank, max_tokens=65536))
            results_list = await asyncio.gather(*tasks, return_exceptions=True)
            for results in results_list:
                if isinstance(results, Exception) or not results:
                    continue
                for r in results:
                    mem_text = r.get("text", "") or ""
                    if not mem_text.strip():
                        continue
                    dedup_key = mem_text[:80]
                    if dedup_key in seen_texts:
                        continue
                    seen_texts.add(dedup_key)
                    tags = r.get("tags", [])
                    doc_id = None
                    for t in tags:
                        if t.startswith("doc_id:"):
                            doc_id = t[7:]
                            break
                    docs.append({"text": mem_text, "doc_id": doc_id or "_unknown_", "tags": tags})
            if docs:
                logger.info("BM25: fallback to Hindsight recall, got %d chunks", len(docs))
        except Exception as e:
            logger.warning("BM25 recall fallback failed: %s", e)

    if not docs:
        return None, []

    tokenized = [tokenize(d["text"]) for d in docs]
    bm25 = BM25Okapi(tokenized)

    # 获取最后更新时间用于增量检测
    try:
        _ts_db = SessionLocal()
        if bank == "all":
            _max_ts = _ts_db.execute(text("SELECT MAX(updated_at) FROM documents WHERE searchable=1 AND status='active'")).fetchone()[0]
        else:
            _max_ts = _ts_db.execute(text("SELECT MAX(updated_at) FROM documents WHERE searchable=1 AND status='active' AND bank=:bank"), {"bank": bank}).fetchone()[0]
        _ts_db.close()
        _max_ts_str = str(_max_ts) if _max_ts else ""
    except Exception:
        _max_ts_str = ""

    _bm25_caches[bank] = {"index": bm25, "docs": docs, "ts": now, "doc_count": len(docs), "updated_at": _max_ts_str}
    logger.info("BM25 index built: %d chunks for bank=%s (from %d queries + meta.db)", len(docs), bank, len(recall_queries))
    return bm25, docs


def bm25_search(query: str, bm25, docs: list, top_k: int = 10) -> list:
    """BM25 关键词搜索（仅在 build_bm25_index 之后调用）"""
    if not bm25 or not docs:
        return []
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    scores = bm25.get_scores(query_tokens)
    # 按分数降序取 top_k*2 候选（多取一些，后面过滤）
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k * 2]
    # 保留分数为正，或在 top-3 以内的结果
    results = []
    for rank, idx in enumerate(top_indices):
        s = float(scores[idx])
        if s > 0 or (rank < 3 and s != 0):  # top-3 即使分数为负也保留
            results.append({
                "text": docs[idx]["text"], "doc_id": docs[idx]["doc_id"],
                "tags": docs[idx]["tags"], "bm25_score": s
            })
    return results[:top_k]


# ═══════════════════════════════════════════════════════════════════
# 轻量级关键词密度 Reranker（零依赖，纯 Python）
# ═══════════════════════════════════════════════════════════════════

def keyword_rerank(query: str, candidates: list, top_k: int = 20) -> list:
    """基于关键词密度的轻量级重排序。运行在 RRF 之后、LLM Rerank 之前。

    该步骤只做温和重排，不做硬截断到单一词面结果：先保留原始 RRF
    前若干名和每文档首个候选，再用关键词得分补齐，避免 dense 语义召回被
    二次词面排序完全淘汰。
    """
    if not candidates or not query:
        return candidates[:top_k]

    query_tokens = tokenize(query)
    if not query_tokens:
        return candidates[:top_k]

    def _doc_id(item: dict) -> str:
        if item.get("doc_id"):
            return str(item.get("doc_id"))
        for tag in item.get("tags", []):
            if tag.startswith("doc_id:"):
                return tag[7:]
        return ""

    scored = []
    for original_rank, item in enumerate(candidates):
        text = item.get("text", "")
        text_lower = text.lower()
        text_len = max(len(text), 1)

        # 1. 关键词覆盖率（0-1）
        hits = sum(1 for t in query_tokens if t in text_lower)
        coverage = hits / len(query_tokens) if query_tokens else 0

        # 2. 关键词密度（归一化到 0-1）
        total_hits = sum(text_lower.count(t) for t in query_tokens)
        density = min(total_hits / (text_len / 100), 1.0)

        # 3. 标题匹配度（梯度：命中词数/总词数 × 0.3）
        title = ""
        for t in item.get("tags", []):
            if t.startswith("title:"):
                title = t[6:].lower()
                break
        title_hits = sum(1 for t in query_tokens if t in title) if title else 0
        title_boost = (title_hits / len(query_tokens) * 0.3) if query_tokens else 0

        # 4. 文本长度质量（200-2000 字符最优）
        if 200 <= text_len <= 2000:
            length_quality = 1.0
        elif text_len < 200:
            length_quality = text_len / 200
        else:
            length_quality = max(0.5, 1.0 - (text_len - 2000) / 10000)

        # 5. 原始 RRF 排名保序项，避免语义召回被词面得分完全覆盖
        rank_prior = 1.0 / (original_rank + 1)

        # 综合评分：词面信号 + RRF先验
        score = (
            coverage * 0.30
            + density * 0.20
            + title_boost
            + length_quality * 0.10
            + rank_prior * 0.25
        )
        scored.append((score, original_rank, item))

    keep: list[dict] = []
    seen_ids: set[int] = set()

    def _add(item: dict) -> None:
        ident = id(item)
        if ident not in seen_ids:
            seen_ids.add(ident)
            keep.append(item)

    # 保留原始 RRF 前若干名，保护 dense/RRF 多样性
    for item in candidates[: min(8, len(candidates))]:
        _add(item)

    # 每个文档至少保留首个候选，避免单一大文档挤掉其他文档
    seen_docs: set[str] = set()
    for item in candidates:
        did = _doc_id(item)
        if did and did not in seen_docs:
            seen_docs.add(did)
            _add(item)
        if len(keep) >= top_k:
            break

    # 再按关键词得分补齐
    scored.sort(key=lambda x: x[0], reverse=True)
    for _, _, item in scored:
        _add(item)
        if len(keep) >= top_k:
            break

    return keep[:top_k]


# ═══════════════════════════════════════════════════════════════════
# RRF 融合
# ═══════════════════════════════════════════════════════════════════

def rrf_merge(dense_results: list, bm25_results: list, k: int = 60, query_keywords: list = None, bank: str = "all") -> list:
    """Reciprocal Rank Fusion 融合两路召回结果

    使用 (doc_id, text[:30]) 复合key，保留chunk级多样性，
    避免同一文档的不同chunk被合并丢失（如接地电阻表被CPU介绍覆盖）。

    query_keywords: 查询关键词列表，BM25结果的text包含关键词时加权2.0倍
    """
    chunk_scores = {}
    chunk_data = {}

    def _make_key(r, is_bm25=False):
        doc_id = None
        if is_bm25:
            doc_id = r.get("doc_id")
        else:
            for t in r.get("tags", []):
                if t.startswith("doc_id:"):
                    doc_id = t[7:]
                    break
        text = r.get("text", "")[:80]
        return f"{doc_id or 'x'}_{text}"

    # Dense 结果按排名打分
    for rank, r in enumerate(dense_results):
        key = _make_key(r)
        chunk_scores[key] = chunk_scores.get(key, 0) + 1.0 / (k + rank + 1)
        if key not in chunk_data:
            chunk_data[key] = r

    # BM25 结果按排名打分（含关键词加权 + Excel结构化文档加权 + 标准号文档加权）
    _EXCEL_STRUCTURE_KEYWORDS = ["检查项", "检查要求", "评分要点", "核查力度", "检查内容", "评分标准", "检查标准", "核查要点"]
    _STD_TITLE_PAT = re.compile(r'(GB|ISO|YD|SJ|GA|HJ|CJJ|JGJ|WS)\s*/?\s*T?\s*\d+')
    for rank, r in enumerate(bm25_results):
        key = _make_key(r, is_bm25=True)
        text = r.get("text", "")
        title = r.get("title", "") or r.get("doc", "")
        keyword_boost = 1.0
        if query_keywords and any(kw in text for kw in query_keywords):
            keyword_boost = 2.0
        # Excel类结构化文档加权：包含检查项/评分要点等关键词时 1.5x
        if any(kw in text for kw in _EXCEL_STRUCTURE_KEYWORDS):
            keyword_boost *= 1.5
        # 标准号文档加权：标题包含标准号时 1.3x
        if _STD_TITLE_PAT.search(title):
            keyword_boost *= 1.3
        chunk_scores[key] = chunk_scores.get(key, 0) + keyword_boost / (k + rank + 1)
        if key not in chunk_data:
            chunk_data[key] = r

    # 按 RRF 分数排序
    sorted_keys = sorted(chunk_scores.keys(), key=lambda x: chunk_scores[x], reverse=True)
    merged = [chunk_data[k] for k in sorted_keys]

    # ── 文档级关键词密度加权 ──
    if query_keywords:
        doc_kw_hits = defaultdict(int)
        doc_total_chunks = defaultdict(int)
        for item in merged:
            did = None
            for t in item.get("tags", []):
                if t.startswith("doc_id:"):
                    did = t[7:]
                    break
            if not did:
                continue
            doc_total_chunks[did] += 1
            text = item.get("text", "")
            hits = sum(1 for kw in query_keywords if kw in text)
            doc_kw_hits[did] += hits

        for item in merged:
            did = None
            for t in item.get("tags", []):
                if t.startswith("doc_id:"):
                    did = t[7:]
                    break
            if did and doc_total_chunks[did] > 0:
                density = doc_kw_hits[did] / doc_total_chunks[did]
                if density >= 1.0:
                    key = _make_key(item)
                    chunk_scores[key] = chunk_scores.get(key, 0) * 1.5

        sorted_keys = sorted(chunk_scores.keys(), key=lambda x: chunk_scores[x], reverse=True)
        merged = [chunk_data[k] for k in sorted_keys]

    # ── RRF per-doc score cap: 防止大文档靠chunk数量碾压小文档 ──
    # 任何文档的累计 RRF 得分上限为 _MAX_DOC_SCORE，超出部分的低分 chunk 归零
    _MAX_DOC_SCORE = 1.5  # ≈ rank1(1/61≈0.0164) + rank2(0.0161) + ... ~90 chunks
    _doc_accum = defaultdict(float)
    for _key in list(chunk_scores.keys()):
        _item = chunk_data[_key]
        _did = None
        for _t in _item.get("tags", []):
            if _t.startswith("doc_id:"):
                _did = _t[7:]
                break
        if not _did:
            _did = f"_no_{_item.get('text', '')[:20]}"
        _prev = _doc_accum[_did]
        _new = min(chunk_scores[_key], _MAX_DOC_SCORE - _prev) if _prev < _MAX_DOC_SCORE else 0.0
        chunk_scores[_key] = _new
        _doc_accum[_did] += _new
    sorted_keys = sorted(chunk_scores.keys(), key=lambda x: chunk_scores[x], reverse=True)
    merged = [chunk_data[k] for k in sorted_keys if chunk_scores[k] > 0]

    # ── 文档多样性保障 ──
    # 限制每个文档最多取N个chunks，防止大文档完全淹没小文档
    doc_counts = defaultdict(int)  # doc_id → 已取数量
    diverse = []
    max_per_doc = 10 if bank == "checklist" else 3  # Excel检查表允许更多chunks

    for item in merged:
        did = None
        for t in item.get("tags", []):
            if t.startswith("doc_id:"):
                did = t[7:]
                break
        if not did:
            did = f"_no_{id(item)}"

        if doc_counts[did] < max_per_doc:
            diverse.append(item)
            doc_counts[did] += 1

    return diverse


# ═══════════════════════════════════════════════════════════════════
# LLM Rerank
# ═══════════════════════════════════════════════════════════════════

async def llm_rerank(query: str, candidates: list, top_k: int = 15) -> list:
    """用LLM对候选文档按查询相关性重新排序。

    延迟策略：只在候选>=3个时触发，拼接候选文本前200字符，
    让LLM输出排序后的索引列表，延迟<2s。
    """
    if len(candidates) <= 2:
        return candidates[:top_k]

    # 构造候选摘要（含文档标题 + 扩大到500字符）
    snippets = []
    for i, c in enumerate(candidates[:20]):  # 最多20个候选（确保结构化文档能进入rerank）
        text = c.get("text", "")[:500].replace("\n", " ")
        # 提取文档标题（从tags中查找title标签）
        doc_title = ""
        for t in c.get("tags", []):
            if t.startswith("title:"):
                doc_title = t[6:]
                break
        if not doc_title:
            doc_title = c.get("doc_name", "") or c.get("source", "")
        title_prefix = f"《{doc_title}》: " if doc_title else ""
        snippets.append(f"[{i}] {title_prefix}{text}")

    prompt = f"""你是一个文档排序助手。请根据查询的相关性，对以下候选文档片段排序。

重要规则：
1. 优先选择标题和内容都与查询最直接相关的文档
2. 区分近义词差异，例如"接地端子"（电气连接器件）和"接地电阻"（电气参数）是不同概念
3. 查询中包含标准号时，标准文档优先于一般性指导文档
4. 当多个文档是同一标准的不同版本（如GB50462-2015和GB50462-2024），优先选择最新版本（年份数字最大的），除非查询明确要求旧版本

查询: {query}

候选文档:
{chr(10).join(snippets)}

请只输出排序后的索引号列表（从最相关到最不相关），用逗号分隔。
例如: 3,0,7,1,5
只输出数字，不要解释。"""

    try:
        result = await _llm_chat([{"role": "user", "content": prompt}], stream=False)
        # 解析排序结果
        indices = [int(x.strip()) for x in result.strip().split(",") if x.strip().isdigit()]
        # 按LLM排序重组结果
        reranked = []
        seen = set()
        for idx in indices:
            if 0 <= idx < len(candidates) and idx not in seen:
                reranked.append(candidates[idx])
                seen.add(idx)
        # 补充LLM未提及的候选
        for i, c in enumerate(candidates):
            if i not in seen and len(reranked) < top_k:
                reranked.append(c)
        return reranked[:top_k]
    except Exception as e:
        logger.warning("LLM rerank failed: %s", e)
        return candidates[:top_k]


# ═══════════════════════════════════════════════════════════════════
# 费率表片段查找
# ═══════════════════════════════════════════════════════════════════

def _find_rate_table_snippet(tier_keywords: list, bank: str = "all") -> tuple:
    """在 meta.db 中查找费率表片段。返回 (snippet, title) 或 (None, None)。
    bank: 指定bank过滤，"all"不过滤。[HOTFIX-0606] 防止跨bank数据泄漏。"""
    try:
        _db = SessionLocal()
        _filtered = [kw for kw in tier_keywords if "万" in kw]
        if not _filtered:
            return None, None
        # Use parameterized LIKE to prevent SQL injection
        _params = {}
        _conditions_parts = []
        for i, kw in enumerate(_filtered):
            key = f"kw{i}"
            _conditions_parts.append(f"p.parent_text LIKE :{key}")
            _params[key] = f"%{kw}%"
        _conditions = " OR ".join(_conditions_parts)
        _bank_filter = ""
        if bank and bank != "all":
            _bank_filter = " AND d.bank = :bank"
            _params["bank"] = bank
        _sql = f"""
            SELECT d.doc_id, d.title, p.parent_text
            FROM documents d
            JOIN parent_chunks p ON d.doc_id = p.doc_id
            WHERE ({_conditions})
              AND (INSTR(p.parent_text, '3%') > 0 OR INSTR(p.parent_text, '3\\%') > 0)
              {_bank_filter}
            LIMIT 3
        """
        _rows = _db.execute(text(_sql), _params).fetchall()
        _db.close()
        for _did, _dtitle, _ptext in _rows:
            if any(t in _ptext for t in ["3%", "times 3", "3\\"]):
                _snippet = None
                for _kw in tier_keywords:
                    if "万" not in _kw:
                        continue
                    _pos = _ptext.find(_kw)
                    if _pos >= 0:
                        _next = _ptext.find("投资总额在", _pos + len(_kw))
                        _snippet = _ptext[_pos:_next] if _next > 0 else _ptext[_pos:_pos+150]
                        break
                if not _snippet:
                    _pos = _ptext.find("软件费用")
                    _snippet = _ptext[max(0,_pos-200):min(len(_ptext),_pos+500)] if _pos >= 0 else _ptext[:800]
                return _snippet, _dtitle
    except Exception as e:
        logger.warning("_find_rate_table_snippet failed: %s", e)
    return None, None


# ═══════════════════════════════════════════════════════════════════
# Tiebreaker: 时间 + 地理层级排序（应用层，不改 Hindsight 语义排序）
# ═══════════════════════════════════════════════════════════════════

_GEO_ORDER = {"national": 0, "provincial": 1, "city": 2, "enterprise_group": 3, "enterprise": 4}
_GEO_KEYWORDS = {"标准", "规范", "规程", "指南", "法规", "办法", "细则", "要求",
                 "GB", "GB/T", "GBZ", "DB", "ISO", "YD", "SJ"}


def _extract_doc_id_from_tags(tags: list) -> str | None:
    """Extract doc_id from hindsight result tags."""
    if not tags:
        return None
    for t in tags:
        if t.startswith("doc_id:"):
            return t[7:]
    return None


def _check_geo_query(query: str) -> bool:
    """Check if the query likely needs geo-based sorting."""
    for kw in _GEO_KEYWORDS:
        if kw in query:
            return True
    return False


def apply_tiebreaker_sort(
    results: list,
    query: str = "",
) -> list:
    """对搜索结果应用 tiebreaker 排序。

    核心原则：语义相似度永远是主排序，时间和地理只是 tiebreaker。

    算法：
    1. 从 Hindsight 标签中提取 doc_id
    2. 批次查询 DB 获取 published_date 和 geo_scope
    3. 按 semantic_score 分成 10 个 score_band
    4. 段内排序：published_date DESC → geo_scope 层级 → 原始 score 兜底
    5. geo tiebreaker 仅在 query 含标准/规范/法规等关键词时启用

    Args:
        results: RRF merge 后的搜索结果列表
        query: 用户查询

    Returns:
        排序后的结果列表
    """
    if not results:
        return results

    # Batch query documents table for published_date and geo_scope
    doc_ids = set()
    for r in results:
        did = _extract_doc_id_from_tags(r.get("tags", []))
        if did:
            doc_ids.add(did)

    doc_meta = {}
    if doc_ids:
        try:
            db = SessionLocal()
            id_list = list(doc_ids)
            # SQLite: batch query with IN clause
            placeholders = ",".join(f":id{i}" for i in range(len(id_list)))
            params = {f"id{i}": d for i, d in enumerate(id_list)}
            rows = db.execute(
                text(
                    f"SELECT doc_id, published_date, geo_scope "
                    f"FROM documents WHERE doc_id IN ({placeholders})"
                ),
                params,
            ).fetchall()
            db.close()
            for row in rows:
                doc_meta[row[0]] = {
                    "published_date": row[1],
                    "geo_scope": row[2],
                }
        except Exception as e:
            logger.warning("tiebreaker: batch query failed: %s", e)

    use_geo = _check_geo_query(query)

    # Extract score from recall results (use score field or fall back to 0.5)
    scored = []
    for r in results:
        score = r.get("score", 0.5) or 0.5
        did = _extract_doc_id_from_tags(r.get("tags", []))
        meta = doc_meta.get(did, {})
        pub_date = meta.get("published_date")
        geo = meta.get("geo_scope")
        geo_rank = _GEO_ORDER.get(geo, 99) if geo else 99  # NULL last

        scored.append({
            "result": r,
            "score": score,
            "score_band": int(score * 10),  # 0-9
            "pub_date_num": -int(pub_date.replace("-", "")) if pub_date else 0,  # newer=more negative, NULL=0
            "geo_rank": geo_rank,
        })

    # Sort: score_band DESC → published_date DESC (newest first, NULL last) → geo_rank ASC → score DESC
    scored.sort(
        key=lambda x: (
            -x["score_band"],      # primary: semantic score band (higher first)
            x["pub_date_num"],      # tiebreaker 1: newer first (-20260624 < -20250101 < 0)
            x["geo_rank"] if use_geo else 0,  # tiebreaker 2: geo scope (only for standard queries)
            -x["score"],            # final: original score within band
        )
    )

    return [s["result"] for s in scored]
