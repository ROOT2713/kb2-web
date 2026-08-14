"""Checklist query regression tests.

Tests the checklist bank query endpoint (/api/query) with structured
Excel checklist data, verifying that BM25 + RRF + rerank correctly
retrieves checklist content and generates answers containing the
expected structured field names.

Architecture:
- In-memory SQLite DB (shared with all test fixtures via conftest.py)
- No real Hindsight / LLM / network — all external services monkeypatched
- TestClient POST /api/query with form data
"""

import pytest

# ══════════════════════════════════════════════════════════════════
# Test constants
# ══════════════════════════════════════════════════════════════════

CHECKLIST_DOC_ID = "excel-checklist-doc"
CHECKLIST_DOC_TITLE = "Excel检查表回归测试"

# Structured parent_chunks covering all required field names
# （"检查项/检查要求/核查力度/方案类/第35项/评分要点/安全计算环境/检查标准"）
PARENT_CHUNKS = [
    {
        "doc_id": CHECKLIST_DOC_ID,
        "parent_idx": 0,
        "parent_text": (
            "检查项：第35项 网络安全审计\n"
            "检查要求：应启用网络安全审计功能，对网络系统中的网络设备运行状况、"
            "网络流量、用户行为等进行日志记录，审计记录应至少保存6个月。\n"
            "核查力度：高——需现场核查日志配置和记录完整性\n"
            "方案类：安全计算环境\n"
            "评分要点：审计记录应包括事件的日期和时间、用户、事件类型、"
            "事件是否成功及其他与审计相关的信息，缺项扣分。\n"
            "检查标准：GB/T 22239-2019 8.1.4 安全审计"
        ),
    },
    {
        "doc_id": CHECKLIST_DOC_ID,
        "parent_idx": 1,
        "parent_text": (
            "检查项：第35项 入侵防范\n"
            "检查要求：应遵循最小安装的原则，仅安装需要的组件和应用程序；"
            "应关闭不需要的系统服务、默认共享和高危端口。\n"
            "核查力度：中——抽查关键服务器配置\n"
            "方案类：安全计算环境\n"
            "评分要点：系统安装组件检查、端口扫描验证、服务清单核对\n"
            "检查标准：GB/T 22239-2019 8.1.4.2"
        ),
    },
    {
        "doc_id": CHECKLIST_DOC_ID,
        "parent_idx": 2,
        "parent_text": (
            "检查项：第35项 安全计算环境-身份鉴别\n"
            "检查要求：应对登录用户进行身份标识和鉴别，身份标识具有唯一性，"
            "身份鉴别信息具有复杂度要求并定期更换。\n"
            "核查力度：高——核查密码策略、账户锁定策略配置\n"
            "方案类：安全计算环境-身份认证\n"
            "评分要点：密码复杂度（长度>=8、包含大小写字母数字特殊字符）、"
            "密码有效期<=90天、登录失败锁定机制\n"
            "检查标准：GB/T 22239-2019 8.1.4.1"
        ),
    },
    {
        "doc_id": CHECKLIST_DOC_ID,
        "parent_idx": 3,
        "parent_text": (
            "检查项：方案类 安全设计方案评审\n"
            "检查要求：安全设计方案应包含安全需求分析、安全架构设计、"
            "安全功能设计、安全产品选型等内容。\n"
            "核查力度：中——评审设计方案文档完整性\n"
            "方案类：安全方案评审\n"
            "评分要点：方案要素完整性、安全需求覆盖度、产品选型合理性\n"
            "检查标准：GB/T 25070-2019"
        ),
    },
    {
        "doc_id": CHECKLIST_DOC_ID,
        "parent_idx": 4,
        "parent_text": (
            "检查项：核查力度-高等级检查项汇总\n"
            "检查要求：对于标识为‘核查力度：高’的检查项，需进行全面的现场核查，"
            "包括但不限于配置核查、日志分析、渗透测试验证。\n"
            "核查力度：高——适用于三级及以上系统\n"
            "方案类：安全计算环境\n"
            "评分要点：核查力度高的检查项若未通过，单个扣分权重为2倍。\n"
            "检查标准：等保测评机构检查指引2023版"
        ),
    },
    {
        "doc_id": CHECKLIST_DOC_ID,
        "parent_idx": 5,
        "parent_text": (
            "检查项：评分要点-汇总评分规则\n"
            "检查要求：各检查项的评分要点按照符合/部分符合/不符合三级评定，"
            "最终得分=SUM(单项得分x权重)/总权重。\n"
            "核查力度：中——抽查评分表\n"
            "方案类：安全计算环境\n"
            "评分要点：符合=满分、部分符合=50%分数、不符合=0分\n"
            "检查标准：等保测评机构检查指引2023版 附件A"
        ),
    },
    {
        "doc_id": CHECKLIST_DOC_ID,
        "parent_idx": 6,
        "parent_text": (
            "检查项：安全计算环境-数据安全\n"
            "检查要求：应采用密码技术保证重要数据在传输和存储过程中的"
            "机密性和完整性。\n"
            "核查力度：高——核查加密算法和密钥管理\n"
            "方案类：安全计算环境-数据保护\n"
            "评分要点：传输加密（TLS1.2+）、存储加密（AES-256）、密钥管理规范\n"
            "检查标准：GB/T 22239-2019 8.1.4.4"
        ),
    },
    {
        "doc_id": CHECKLIST_DOC_ID,
        "parent_idx": 7,
        "parent_text": (
            "检查项：安全计算环境-访问控制\n"
            "检查要求：应对用户分配账户和权限，实现管理用户的权限分离。\n"
            "核查力度：中——核查用户权限矩阵\n"
            "方案类：安全计算环境-访问控制\n"
            "评分要点：最小权限原则、角色分离（管理员/审计员/操作员）、"
            "权限变更审批流程\n"
            "检查标准：GB/T 22239-2019 8.1.4.3"
        ),
    },
]

# Fixed answer returned by the monkeypatched chat() — MUST contain
# "检查项"/"检查要求"/"核查力度" (requirement 4 bullet 3).
FIXED_ANSWER = (
    "根据Excel检查表回归测试文档的记录，第35项检查涉及的检查项包括网络安全审计、"
    "入侵防范、身份鉴别等安全计算环境相关要求。"
    "检查要求方面：应启用网络安全审计功能并保存日志至少6个月；"
    "应遵循最小安装原则关闭不必要的服务和端口；"
    "应对登录用户进行身份标识和鉴别，身份标识具有唯一性。"
    "核查力度方面：涉及核心安全功能的检查项核查力度为高，"
    "需要进行现场配置核查和日志分析；非核心项核查力度为中。"
    "评分要点方面：审计记录完整性、系统安装组件检查、密码复杂度要求、"
    "权限分离等均为关键评分项。"
    "检查标准主要依据GB/T 22239-2019等级保护基本要求。"
)

# Keywords expected in answer or source snippets (requirement 9).
FIELD_KEYWORDS = ["检查项", "检查要求", "核查力度", "评分要点", "检查标准"]


# ══════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════

def _insert_test_data(db_session):
    """Insert one Document + multiple ParentChunks into the test DB."""
    from app.models.document import Document, ParentChunk

    doc = Document(
        doc_id=CHECKLIST_DOC_ID,
        title=CHECKLIST_DOC_TITLE,
        bank="industry",
        hs_bank="kb_checklist",
        doc_type="excel_checklist",
        searchable=1,
        category="安全检查表",
        filename="excel_checklist_regression.xlsx",
    )
    db_session.merge(doc)

    for pc in PARENT_CHUNKS:
        db_session.merge(ParentChunk(
            doc_id=pc["doc_id"],
            parent_idx=pc["parent_idx"],
            parent_text=pc["parent_text"],
        ))

    # Keep data visible within the test transaction while avoiding
    # duplicate-key failures if another SessionLocal used by the endpoint
    # de-associates the outer rollback transaction under StaticPool.
    db_session.flush()


def _install_monkeypatches(monkeypatch):
    """Install all monkeypatches that isolate the query endpoint from
    real external services (Hindsight, LLM, network).
    """
    import app.api.query as query_mod
    import app.services.retrieval as retrieval_mod

    # ── recall -> always empty (no dense vector recall) ──
    async def _mock_recall(query, limit=5, bank="kb", max_tokens=4096):
        return []

    # ── llm_rerank -> passthrough (keep BM25+RRF order) ──
    async def _mock_llm_rerank(query, candidates, top_k=15):
        return candidates[:top_k]

    # ── chat -> fixed answer containing field keywords ──
    async def _mock_chat(messages, stream=False, max_retries=3,
                         temperature=0.3, max_tokens=3000):
        return FIXED_ANSWER

    # ── cache lookups -> always miss ──
    def _mock_cache_get_exact(query, bank):
        return None

    async def _mock_cache_get_semantic(query, bank, threshold=0.82):
        return None

    async def _mock_cache_set(query, bank, answer, sources, doc_ids):
        pass

    # ── active Hindsight banks -> empty (no multi-bank recall) ──
    async def _mock_get_active_hindsight_banks(min_docs=1):
        return []

    # ── _hindsight_request -> safe stub (prevents real Hindsight calls
    #    inside build_bm25_index / recall) ──
    async def _mock_hindsight_request(endpoint, method="GET",
                                      json_data=None, timeout=30):
        if "stats" in endpoint:
            return {"total_nodes": 0, "total_documents": 0, "total_links": 0}
        if "documents" in endpoint and method == "GET":
            return {"items": []}
        if "memories" in endpoint:
            return {"items_count": 0}
        return {"status": "ok"}

    monkeypatch.setattr(query_mod, "recall", _mock_recall)
    monkeypatch.setattr(query_mod, "llm_rerank", _mock_llm_rerank)
    monkeypatch.setattr(query_mod, "chat", _mock_chat)
    monkeypatch.setattr(query_mod, "cache_get_exact", _mock_cache_get_exact)
    monkeypatch.setattr(query_mod, "cache_get_semantic", _mock_cache_get_semantic)
    monkeypatch.setattr(query_mod, "cache_set", _mock_cache_set)
    monkeypatch.setattr(query_mod, "_get_active_hindsight_banks",
                        _mock_get_active_hindsight_banks)
    monkeypatch.setattr(retrieval_mod, "_hindsight_request",
                        _mock_hindsight_request)

    # ── Clear BM25 caches to avoid cross-test contamination ──
    retrieval_mod._bm25_caches.clear()


# ══════════════════════════════════════════════════════════════════
# Parametrized query cases
# ══════════════════════════════════════════════════════════════════

QUERY_CASES = [
    "第35项 检查要求",
    "方案类 检查项",
    "核查力度 高",
    "评分要点",
    "安全计算环境 检查标准",
]


# ══════════════════════════════════════════════════════════════════
# Test class
# ══════════════════════════════════════════════════════════════════

class TestChecklistQueryRegression:
    """Regression tests for checklist bank query endpoint.

    Uses autouse fixture to insert test data, install monkeypatches,
    and clear BM25 caches before each test.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, db_session, monkeypatch):
        """Insert data, install patches, clear caches before each test."""
        _insert_test_data(db_session)
        _install_monkeypatches(monkeypatch)

    @pytest.mark.parametrize("query_text", QUERY_CASES)
    def test_checklist_query_returns_fields(self, client, query_text):
        """POST /api/query with bank=checklist returns 200,
        non-empty sources referencing the checklist document,
        and answer/source snippets containing structured field names.
        """
        resp = client.post("/api/query", data={
            "q": query_text,
            "bank": "industry",
            "nocache": "true",
        })

        # ── 8a: HTTP 200 ──
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:500]}"
        )

        data = resp.json()

        # ── 8b: json has answer + sources ──
        assert "answer" in data, f"Missing 'answer' in response: {list(data.keys())}"
        assert "sources" in data, f"Missing 'sources' in response: {list(data.keys())}"

        answer = data["answer"]
        sources = data["sources"]

        # ── 8c: sources must be non-empty ──
        assert len(sources) > 0, (
            f"No sources returned for query '{query_text}'"
        )

        # ── 8d: at least one source references the checklist doc ──
        checklist_source_found = False
        for src in sources:
            doc_name = src.get("doc", "")
            doc_id_val = src.get("doc_id") or ""
            text_val = src.get("text", "") or ""
            combined = f"{doc_name} {doc_id_val} {text_val}"
            if CHECKLIST_DOC_ID in combined or CHECKLIST_DOC_TITLE in combined:
                checklist_source_found = True
                break
        assert checklist_source_found, (
            f"No source references '{CHECKLIST_DOC_ID}' or "
            f"'{CHECKLIST_DOC_TITLE}'. "
            f"First 3 sources: {sources[:3]}"
        )

        # ── 8e: answer or source snippet contains at least one
        #        of the structured field keywords ──
        keyword_found = False

        # Check answer first
        for kw in FIELD_KEYWORDS:
            if kw in answer:
                keyword_found = True
                break

        # Fallback: check source texts
        if not keyword_found:
            for src in sources:
                text_val = src.get("text", "") or ""
                for kw in FIELD_KEYWORDS:
                    if kw in text_val:
                        keyword_found = True
                        break
                if keyword_found:
                    break

        assert keyword_found, (
            f"Neither answer nor source snippets contain any of "
            f"{FIELD_KEYWORDS}. "
            f"Answer preview: {answer[:200]}... "
            f"First source snippets: "
            f"{[s.get('text','')[:100] for s in sources[:2]]}"
        )
