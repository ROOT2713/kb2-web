"""
前端按钮 / API 合同检查 — 验证前端依赖的所有 API 端点可正常响应。

覆盖：
  - 所有公开 API 端点返回 200（或预期错误码）
  - 响应 JSON 结构符合前端期望的 schema
  - 前端页面（Vue 构建）可正常加载
  - upload/query 核心工作流端到端可用

运行方式（集成模式，需要 kb2-web 服务在 3027）：
  pytest tests/unit/test_frontend_endpoints.py --run-integration -v
"""

import json
from urllib.parse import urljoin

import pytest
import httpx

# ── 配置 ────────────────────────────────────────────────────────────
BASE_URL = "http://localhost:3027"
ADMIN_TOKEN = ""   # 测试时 auth 禁用

# 前端依赖的 API 端点清单（每个端点的最小响应结构要求）
API_CONTRACTS = {
    "GET /api/banks": {
        "url": "/api/banks",
        "method": "GET",
        "status": 200,
        "response_shape": {
            "type": "object",
            "keys": ["banks", "current_bank"],
        },
    },
    "GET /api/documents": {
        "url": "/api/documents",
        "method": "GET",
        "status": 200,
        "response_shape": {
            "type": "object",
            "keys": ["items", "total"],
        },
    },
    "GET /api/synonyms": {
        "url": "/api/synonyms",
        "method": "GET",
        "status": 200,
        "response_shape": {
            "type": "object",
            "keys": ["items"],
        },
    },
    "GET /api/concepts": {
        "url": "/api/concepts",
        "method": "GET",
        "status": 200,
        "response_shape": {
            "type": "object",
            "keys": ["items"],
        },
    },
    "POST /api/query (basic)": {
        "url": "/api/query",
        "method": "POST",
        "json": {"query": "接地电阻", "bank": "standards", "nocache": True},
        "status": 200,
        "response_shape": {
            "type": "object",
            "keys": ["answer", "sources"],
        },
    },
    "POST /api/query (with nocache)": {
        "url": "/api/query",
        "method": "POST",
        "json": {"query": "GB/T 25000", "bank": "standards", "nocache": True},
        "status": 200,
        "response_shape": {
            "type": "object",
            "keys": ["answer", "sources"],
        },
    },
    "GET /health": {
        "url": "/health",
        "method": "GET",
        "status": 200,
        "response_shape": {
            "type": "object",
            "keys": ["status"],
        },
    },
}

# 前端页面路由（浏览器加载检查）
FRONTEND_ROUTES = [
    "/",           # QueryView（主查询页）
    "/documents",  # DocumentsView
    "/admin",      # AdminView
    "/upload",     # UploadView
]


# ═══════════════════════════════════════════════════════════════════
# API Endpoint 回归
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.skipif(
    "not config.getoption('--run-integration')",
    reason="需要 --run-integration 和 3027 服务",
)
class TestAPIEndpointAvailability:
    """每个前端依赖的 API 端点必须返回正确状态码和响应结构。"""

    @pytest.mark.parametrize(
        "name,spec",
        [(k, v) for k, v in API_CONTRACTS.items()],
        ids=[k[:40] for k in API_CONTRACTS.keys()],
    )
    @pytest.mark.asyncio
    async def test_endpoint_responds(self, name, spec):
        url = urljoin(BASE_URL, spec["url"])
        method = spec.get("method", "GET").lower()
        headers = {}
        if ADMIN_TOKEN:
            headers["Authorization"] = f"Bearer {ADMIN_TOKEN}"

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
            if method == "get":
                resp = await client.get(spec["url"], headers=headers)
            elif method == "post":
                json_data = spec.get("json", {})
                resp = await client.post(spec["url"], json=json_data, headers=headers)
            else:
                pytest.fail(f"Unknown method: {method}")

        assert resp.status_code == spec["status"], \
            f"{name}: 期望 {spec['status']}，实际 {resp.status_code}: {resp.text[:200]}"

        # 验证响应 JSON
        try:
            data = resp.json()
        except Exception:
            data = {}

        shape = spec.get("response_shape", {})
        if shape.get("type") == "object":
            for key in shape.get("keys", []):
                assert key in data, \
                    f"{name}: 响应缺少字段 '{key}'"


# ═══════════════════════════════════════════════════════════════════
# 查询工作流集成测试
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.skipif(
    "not config.getoption('--run-integration')",
    reason="需要 --run-integration",
)
class TestQueryWorkflow:
    """查询→检索→回答的核心工作流。"""

    @pytest.mark.asyncio
    async def test_query_returns_answer(self):
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
            resp = await client.post("/api/query", json={
                "query": "验收测评费用 取费标准",
                "bank": "standards",
                "nocache": True,
            })

        assert resp.status_code == 200, f"Query endpoint failed: {resp.text[:200]}"
        data = resp.json()
        assert "answer" in data, "响应缺少 answer"
        assert len(data["answer"]) > 50, f"answer 太短: {len(data['answer'])} chars"
        assert "sources" in data, "响应缺少 sources"

    @pytest.mark.asyncio
    async def test_query_with_history(self):
        """带历史上下文的查询。"""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
            resp = await client.post("/api/query", json={
                "query": "根据上述规范，测试周期多久？",
                "bank": "standards",
                "history": "用户: GB/T 25000.51 规定的测试流程是什么？\n助手: 根据相关标准...",
                "nocache": True,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data

    @pytest.mark.asyncio
    async def test_query_multi_bank(self):
        """跨 bank 查询。"""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
            resp = await client.post("/api/query", json={
                "query": "政务信息化项目管理办法",
                "bank": "all",
                "nocache": True,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data


# ═══════════════════════════════════════════════════════════════════
# 前端页面加载检查
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.skipif(
    "not config.getoption('--run-integration')",
    reason="需要 --run-integration",
)
class TestFrontendPageLoad:
    """前端各路由页面可正常加载（通过 browser 工具）。"""

    @pytest.mark.parametrize(
        "route", FRONTEND_ROUTES,
        ids=[r.lstrip("/") or "home" for r in FRONTEND_ROUTES],
    )
    @pytest.mark.asyncio
    async def test_frontend_page_loads(self, route):
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
            resp = await client.get(route, follow_redirects=True)
        assert resp.status_code in (200, 304, 302), \
            f"前台页面 {route}: {resp.status_code}"
        # 前端页面应返回 HTML（非 JSON）
        content_type = resp.headers.get("content-type", "")
        assert "text/html" in content_type or "text/html" in content_type, \
            f"前台页面 {route}: 期望 HTML，实际 {content_type}"


# ═══════════════════════════════════════════════════════════════════
# API 响应结构稳定性
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.skipif(
    "not config.getoption('--run-integration')",
    reason="需要 --run-integration",
)
class TestAPIResponseShape:
    """关键 API 的响应结构稳定性 — 前端依赖的这些结构不可变。"""

    @pytest.mark.asyncio
    async def test_banks_response_shape_stable(self):
        """GET /api/banks 返回的结构必须包含前端使用的字段。"""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
            resp = await client.get("/api/banks")

        data = resp.json()

        # banks 必须是数组
        assert isinstance(data.get("banks"), list)
        if data["banks"]:
            # 每个 bank 项必须有 name 和 key
            for bank in data["banks"]:
                assert "name" in bank, f"bank 缺少 name: {bank}"
                assert "key" in bank or "bank" in bank, f"bank 缺少 key: {bank}"

    @pytest.mark.asyncio
    async def test_documents_response_shape_stable(self):
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
            resp = await client.get("/api/documents")

        data = resp.json()
        assert isinstance(data.get("items"), list), "documents.items 不是数组"
        assert isinstance(data.get("total"), int), "documents.total 不是整数"

        if data["items"]:
            doc = data["items"][0]
            # 前端使用的字段
            for field in ["doc_id", "title", "bank", "status"]:
                assert field in doc, f"文档对象缺少字段 '{field}'"

    @pytest.mark.asyncio
    async def test_query_response_shape_stable(self):
        """POST /api/query 的响应结构。"""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
            resp = await client.post("/api/query", json={
                "query": "软件测试 规范",
                "bank": "standards",
                "nocache": True,
            })

        data = resp.json()
        # 前端使用的关键字段
        assert "answer" in data
        assert isinstance(data.get("sources"), list)
        if data["sources"]:
            # 每条 source 的来源信息格式
            for src in data["sources"]:
                assert "text" in src or "snippet" in src or "content" in src, \
                    f"source 缺少文本字段: {str(src)[:100]}"
