"""Request ID 中间件 — 为每个请求生成 trace_id，贯穿全链路日志。

使用方式（已在 main.py 中通过 app.add_middleware(RequestIDMiddleware) 注册）：

1. 在任意深度调用 get_request_id() 获取当前请求 ID
2. 响应头自动包含 X-Request-ID
3. 日志自动带上 [req=xxx] 前缀（无需修改任何 logger.info/warning/error 调用）
"""

import uuid
import logging
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """获取当前请求的 trace_id（任何深度调用都能拿到）"""
    return _request_id_ctx.get()


def generate_request_id() -> str:
    """生成全局唯一的短请求 ID"""
    return uuid.uuid4().hex[:8]


class _RequestIDFilter(logging.Filter):
    """Logging Filter：自动在每条日志前面加上 [req=xxx] 前缀。"""

    def filter(self, record: logging.LogRecord) -> bool:
        rid = _request_id_ctx.get()
        if rid and not getattr(record, "_rid_injected", False):
            record.msg = f"[req={rid}] {record.msg}"
            record._rid_injected = True
        return True


# ── 注册到所有 handler（root.addFilter 不影响子 logger 的 handler 链）──
_RID_FILTER = _RequestIDFilter()
for h in logging.root.handlers:
    h.addFilter(_RID_FILTER)


def _ensure_rid_filter():
    """确保新创建的 handler 也挂上 filter（在 lifespan startup 中调用）"""
    for h in logging.root.handlers:
        if _RID_FILTER not in h.filters:
            h.addFilter(_RID_FILTER)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """FastAPI 中间件：为每个请求注入 request_id，响应头返回 X-Request-ID。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = generate_request_id()
        token = _request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            _request_id_ctx.reset(token)
