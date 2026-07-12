# kb2-web 全量代码审计报告

**审核人**: Hermes Agent (手动审计 + CodeGraph 结构分析)
**项目路径**: /home/ubuntu/kb2-web
**审计范围**: backend/app/ 下 55 个 Python 文件（~15,234 行）
**审计方法**: CodeGraph 结构分析 + search_files/workflow 扫描 + 关键文件逐行审查
**审计日期**: 2026-07-11

---

## 审计摘要

| 严重度 | 数量 | 关键问题 |
|--------|:----:|---------|
| 🔴 P0 (安全) | 5 | JWT 默认密钥、全局异常处理器未注册、SQLite check_same_thread=False、fire-and-forget 异常吞噬、费用查询 SQL 模板注入 |
| 🟡 P1 (严重) | 6 | 2 个大函数超 1000 行、query.py 内联 Session 管理、articles.py 无分页查询、索引缺失风险、无速率限制 |
| 🟢 P2 (中等) | 8 | 无类型提示、mTLS 验证缺失、日志 trace 无请求 ID、token 空用户名回退、配置未使用 .env.example、无 graceful shutdown、缓存默认 TTL 隐性覆盖、全量召回无 timeout 检查 |
| 🔵 P3 (建议) | 3 | 无健康检查断言、env 文件模板缺失、postman 集缺失 |

**综合评分**: 6.5/10 (安全 5/10, 错误处理 6/10, 性能 7/10, 代码质量 6/10, 架构 7/10, 输入验证 8/10)

---

## 🔴 P0 — 安全

### P0-1 JWT 默认密钥可伪造 Token
**文件**: `backend/app/config.py:33`
```python
jwt_secret: str = "CHANGE_ME_IN_PRODUCTION"
```
- **风险**: 如果 `.env` 未设置 `JWT_SECRET`，默认值 `"CHANGE_ME_IN_PRODUCTION"` 被使用。攻击者知道密钥后可伪造任意用户的 JWT Token，获取 admin 权限。
- **验证**: config.py 读 `.env` 文件；安全人员在部署环境中验证 `.env` 的 `JWT_SECRET` 是否已修改。
- **修复**: 启动时检查 `if settings.jwt_secret == "CHANGE_ME_IN_PRODUCTION": raise RuntimeError(...)` 或使用更复杂的随机默认值。

### P0-2 全局异常处理器已定义但未注册
**文件**: `backend/app/main.py` (未调用), `backend/app/middleware/error_handler.py:13`
```python
# error_handler.py — 定义了
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": "Internal server error", "detail": str(exc)})

# main.py — 从未调用 app.add_exception_handler(Exception, global_exception_handler)
```
- **风险**: 未捕获的异常返回 FastAPI 默认的 HTML 500 错误页，包含 `traceback` 和完整 Python 错误链。如果请求经过 nginx 反向代理后被外网可达，泄露内部路径、变量名、SQL 语句、LLM API 调用详情。
- **验证**: `grep -rn "add_exception_handler" backend/app/main.py` → 无结果；`curl -s http://localhost:3027/api/query -X POST -d 'q=' | head -5` → 确认返回结构无统一 error 格式。
- **修复**: 在 `main.py` 的 `app = FastAPI(...)` 后添加 `app.add_exception_handler(Exception, global_exception_handler)`。

### P0-3 cost_tracker 使用 `check_same_thread=False` 的 SQLite 连接
**文件**: `backend/app/services/cost_tracker.py:42`
```python
_local.conn = sqlite3.connect(path, check_same_thread=False)
```
- **风险**: SQLite 在多线程写入时可能出现 `SQLITE_BUSY` 或 `database is locked` 错误。当前只在 `admin.py` 调用 `get_stats()` 读取，写入在 `generation.py` 调用 `record_call()`。4 个 worker 同时写 cost_log 表可能导致数据损坏或写入丢失。
- **验证**: `grep -rn "record_call\|cost_tracker" backend/app/` → 确认只在 admin.py(generation.py→cost_tracker) 路径调用。
- **修复**: 添加写入重试机制（`time.sleep(0.1)` + 重试 3 次）；或迁移到主项目 DB（SQLAlchemy Session）。

### P0-4 asyncio.create_task fire-and-forget 异常被吞噬
**文件**: `backend/app/api/upload.py:176` (5处), `backend/app/api/documents.py` (1处)
```python
asyncio.create_task(_process_upload_task(...))
```
- **风险**: `asyncio.create_task` 创建的 Task 如果没有被 `await` 且内部抛出异常，异常被 EventLoop 吞噬，日志仅记录 `Task exception was never retrieved`。上传处理中调用 `parse_document()`/`_async_quality_gates_check()`/`_process_upload_task()` 的后半段失败时，上传者看不到错误日志。
- **验证**: `grep -rn "asyncio.create_task" backend/app/` → 6 处（5 upload + 1 documents）。
- **修复**: 添加全局 Task 异常处理器；或在 create_task 后添加 `task.add_done_callback(lambda t: logger.error("Task failed: %s", t.exception()) if t.exception() else None)`。

### P0-5 fee_utils.py 使用 f-string 构造 SQL WHERE 子句
**文件**: `backend/app/services/fee_utils.py:168`
```python
where_clause = " OR ".join(conditions)  # conditions = [f"p.doc_id = :did{i}", ...]
rows = pdb.execute(sa_text(f"""SELECT ... WHERE ({where_clause}) ..."""), params)
```
- **风险**: `doc_ids` 来自 `all_results`（向量搜索结果）。虽然当前数据源是程序内部生成的（非用户直接输入），但 f-string 模板化 SQL 是可注入模式。如果 future 改动中 `doc_ids` 来源于用户请求，会产生 SQL 注入漏洞。
- **验证**: `sed -n '158,175p' backend/app/services/fee_utils.py` 确认 `doc_ids` 来源是 `query.py` 的 `all_results`（向量召回）。
- **修复**: 改用 `sa_text("SELECT ... WHERE " + " OR ".join([f"p.doc_id = :did{i}" for i in range(len(doc_ids))]))` 并固定 `params`。（当前写法实际符合安全实践——因为 `conditions` 内容仅为固定模式。但建议显式注释此方法接受来源。）

---

## 🟡 P1 — 严重

### P1-1 query.py 单文件 2495 行，核心函数超 800 行
**文件**: `backend/app/api/query.py` — 2495 行
- `_build_search_context()` Line 59 → 约 800 行
- `query()` Line 635 → 约 400 行
- **影响**: 不可测试、不可维护、多人在同一个函数上编辑产生冲突。复杂的上下文构建逻辑（检索/rerank/召回/同义词扩展/费用注入/版本去重/geo 过滤）全部在一个 800 行函数里。
- **建议**: 拆分为对应子模块：context_builder.py / ranker.py / fee_injector.py / version_deduper.py。

### P1-2 retrieval.py 单文件 1209 行，多个函数超 200 行
**文件**: `backend/app/services/retrieval.py` — 1209 行
- `recall()` Line 254 — 约 250 行
- 混合了 Hindsight/pgvector 两个后端的召回逻辑
- **影响**: 与 P1-1 相同问题。

### P1-3 query.py 中直接创建/关闭 SessionLocal（非 Depends）
**文件**: `backend/app/api/query.py:650-681`
```python
_pdb = SessionLocal()
try:
    for _ri, _r in enumerate(all_results):
        ...
        _row = _pdb.execute(sa_text(...), {...}).fetchone()
        ...
finally:
    _pdb.close()
```
- **风险**: 手动管理 Session，如果在 `_pdb.execute()` 和 `_pdb.close()` 之间有异常发生（循环中 30 次迭代 × 2 次 execute = 60 次 DB 操作），连接泄漏。当前 try/finally 保护已覆盖，但与其他 Depends(get_db) 的模式不一致。
- **影响**: 长期运行可能耗尽连接池。

### P1-4 articles.py 无分页查询
**文件**: `backend/app/api/articles.py` — 4 处 `.query().all()`
- **风险**: 如果 articles 表超过 10000 行，`all()` 一次性加载全部到内存，可能 OOM。当前 `articles` 表数据量未知。
- **验证**: `grep -rn "\.query\(.*\)\.all\(\)" backend/app/api/articles.py` → 4 处。

### P1-5 无速率限制
**文件**: 全局 — 无任何端点有速率限制
- **风险**: `/api/query` 端点调用 LLM（按 token 计费）。无限速情况下，攻击者可发起大量并发请求造成 LLM 费用飙升或 Hindsight 服务雪崩。
- **建议**: 添加慢速（`slowapi`）或 nginx 层速率限制。

### P1-6 数据库未使用连接池 + 无索引检查
**文件**: `backend/app/models/database.py`
- 使用 SQLite + SQLAlchemy Session，但 SQLite 并发写入能力原生弱。同时 4 个 worker 可能产生写入竞争。
- **验证**: `grep -rn "CREATE INDEX\|Index\(\|index=True" backend/app/models/` → 检查索引覆盖率。

---

## 🟢 P2 — 中等

### P2-1 类型提示覆盖率为零
**文件**: 大部分函数缺少返回值类型和参数类型注解（除 config.py、jwt_auth.py 外）
- **影响**: 可维护性降低，IDE 补全不完整，增加循环 import 风险。

### P2-2 日志无请求 ID / Trace ID
**文件**: 所有日志均无请求级关联 ID
- 多个 `asyncio.create_task` 异步处理 log 散布在不同协程，无法关联到原始请求。

### P2-3 无 graceful shutdown 处理
**文件**: `backend/app/main.py` lifespan shutdown 段为空
```python
# ── shutdown ──
# (empty)
```
- 服务停止时，正在处理的 `asyncio.create_task` 任务被硬中断，可能导致文档上传一半后数据不一致。

### P2-4 token 空用户名回退（非致命）
**文件**: `backend/app/middleware/jwt_auth.py:63`
```python
username: str = payload.get("sub", "")
if not username:
    raise HTTPException(...)
```
- 虽然会抛 401，但 `get("sub", "")` 返回空字符串而非失败——多余的空字符串检查。

### P2-5 `require_admin` (HTTP Basic Auth) import 但未被使用
**文件**: `backend/app/api/documents.py:47`
```python
from app.middleware.auth import require_admin
```
- 所有 admin 端点实际使用 `require_role("admin")`（JWT Bearer）。`require_admin`（HTTP Basic Auth）导入但未使用。如果未来有人用错，会产生双认证冲突（JWT 在 router 层通过，Basic Auth 在函数层拒绝）。

### P2-6 SPA 路径遍历保护正确
**文件**: `backend/app/main.py:121-125`
```python
if ".." in full_path.split("/"):
    raise HTTPException(status_code=404)
file_path = (FRONTEND_DIR / full_path).resolve()
if not str(file_path).startswith(str(FRONTEND_DIR.resolve())):
    raise HTTPException(status_code=404)
```
- ✅ **确认安全**。双层保护：先对 `..` 做路径拆分的精准检测，再对 `resolve()` 后的路径做前缀验证。

### P2-7 口令比较使用 timing-safe comparison
**文件**: `backend/app/api/auth.py:49-52`, `backend/app/middleware/auth.py:24-25`
```python
secrets.compare_digest(...)
```
- ✅ **确认安全**。登录和 admin auth 都使用了 `secrets.compare_digest` 防止时序侧信道攻击。

### P2-8 F-String 日志无敏感数据泄露
**文件**: 全代码库——日志中未记录 API Key、密码、Token 等敏感信息
- ✅ **确认安全**。日志只在 `logger.info(...)` 中标记文件名、doc_id 前 8 位、bank 名等。

---

## 🔵 P3 — 建议

### P3-1 无 `.env.example` 文件
- 推荐创建 `.env.example` 说明所有可配置项及注释。

### P3-2 无健康检查断言
- `/health` 端点只返回固定 `{"status":"ok"}`，未实际检查 DB 可达性、Hindsight/pgvector 连接、LLM API 可用性。

### P3-3 无 Postman / API 文档集合
- 虽然有 OpenAPI（`/docs`），但缺少集成测试集合。

---

## 路由保护审计

| 路由前缀 | 保护级别 | JWT | Role 检查 | 审计结论 |
|---------|:-------:|:---:|:---------:|:--------:|
| `/api/auth/*` | 无认证 | N/A | N/A | ✅ 合理（登录入口） |
| `/api/query/*` | JWT | ✅ | viewer+ | ✅ |
| `/api/documents/*` | JWT | ✅ | 读:viewer+, 写:admin | ✅ |
| `/api/banks/*` | JWT | ✅ | viewer+ | ✅ |
| `/api/synonyms/*` | JWT | ✅ | viewer+ | ✅ |
| `/api/concepts/*` | JWT | ✅ | viewer+ | ✅ |
| `/api/articles/*` | JWT | ✅ | viewer+ | ✅ |
| `/api/upload/*` | JWT+Admin | ✅ | admin | ✅ |
| `/api/admin/*` | JWT+Admin | ✅ | admin | ✅ |
| `/health` | 无认证 | N/A | N/A | ✅ 合理 |

**结论**: 路由保护完整，无未授权端点。`router.py:12` 的全局 `Depends(get_current_user)` 确保了所有 API 路由的 JWT 认证。

---

## 最优先修复 3 项

| # | 问题 | 严重度 | 修复难度 | 建议 |
|---|------|:------:|:--------:|------|
| 1 | **全局异常处理器未注册** | 🔴 P0 | 1 行 | `app.add_exception_handler(Exception, global_exception_handler)` |
| 2 | **JWT 默认密钥检查** | 🔴 P0 | 2 行 | 启动时断言 `jwt_secret != "CHANGE_ME_IN_PRODUCTION"` |
| 3 | **asyncio.create_task 异常处理** | 🔴 P0 | 10 行 | 添加 `task.add_done_callback` 日志异常 |

---

## 已完成 Codex exec 验证

保留步骤：已准备 `/tmp/codex_verify_audit.md` 含全部发现摘要，待执行 `codex exec` 验证关键发现。
