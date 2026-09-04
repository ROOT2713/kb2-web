"""Global error handler middleware."""

import logging
import sys
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse

from app.middleware.request_id import get_request_id

logger = logging.getLogger(__name__)


async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all exception handler — log and return 500."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    # 【FIX-R2-11】500 body 透出 request_id：日志侧 [req=] 前缀已生效，
    # 响应体此前无 rid → 用户报障无法与日志关联。rid 非敏感（8位hex短id）。
    rid = get_request_id()
    content = {"error": "Internal server error"}
    if rid:
        content["request_id"] = rid
    return JSONResponse(
        status_code=500,
        content=content,
        headers={"X-Request-ID": rid} if rid else None,
    )
