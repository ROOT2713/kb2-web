# kb2-web 生产上线检查清单【FIX-006】

> 依据 2026-09 代码审计（P0×2 / HIGH×2 / P1×5）与修复批次 1 整理。
> 逐项勾选后再对外网开放。

## 1. 必改项（不通过 = 拒绝上线）

| # | 检查项 | 说明 | 对应修复 |
|---|--------|------|----------|
| 1.1 | `JWT_SECRET` 已设置且 ≥32 字符 | `openssl rand -hex 32`；应用启动时强制校验，空/弱密钥拒绝启动 | FIX-003 |
| 1.2 | `ADMIN_PASSWORD` 为强密码 | 默认空串 + `ADMIN_USERNAME=admin` 是最大攻击面 | 审计 HIGH |
| 1.3 | 用户默认口令已重置 | 弱口令（如 8 位纯字母+数字）易被撞库 | 审计 MEDIUM |
| 1.4 | LLM / Embedding API Key 仅存在于 `.env` | 确认未硬编码进代码/前端/日志 | 基线要求 |
| 1.5 | 使用 pgvector 时连接串已改默认密码 | 默认 `hindsight:hindsight123@localhost` 不得外泄 | 审计 MEDIUM |

## 2. 网络与部署

| # | 检查项 | 说明 |
|---|--------|------|
| 2.1 | 后端仅监听 `127.0.0.1:3027`，由 Nginx 对外 | 参考 `deploy/nginx.conf.example` |
| 2.2 | Hindsight(:8080)、Wiki(:3006) 未直接暴露公网 | `ss -tlnp` 核对监听面 |
| 2.3 | 反代后设置 `TRUST_PROXY=true` | 否则限流/审计日志拿到的是反代 IP |
| 2.4 | CORS `CORS_ORIGINS` 收紧到实际域名 | 默认含 localhost，仅开发用 |
| 2.5 | `client_max_body_size ≥ 210m`、读写超时 ≥ 300s | 见 nginx 样例 |

## 3. 修复批次 1 落地确认

| # | 检查项 | 验证方法 |
|---|--------|----------|
| 3.1 | bank→hs_bank 口径统一（FIX-001） | `bank=industry` 下查标准号（如 "GB/T 22239"）C1 注入日志出现 |
| 3.2 | 缓存用户隔离（FIX-002） | 用户 A 查询后，用户 B 同查询应 cache miss；`query_cache.scope` 列已建 |
| 3.3 | 拒答不入缓存（FIX-002） | 触发 L3 拒答后再次同查询重新走检索 |
| 3.4 | cache-clear 仅 admin（FIX-002） | viewer 调用返回 403 |
| 3.5 | JWT 守卫（FIX-003） | 空密钥启动直接 RuntimeError |
| 3.6 | 上传白名单（FIX-004） | 上传 `.exe`/无扩展名文件返回 400 |
| 3.7 | 索引质量门（FIX-005） | 日志无 `[FIX-005] ... NOT searchable` 告警；`documents.searchable=0` 的文档不再出现在检索结果 |

## 4. 运行时监控建议

- `/health` 探活（建议 60s 间隔）
- 日志关键字告警：`indexing error`、`[FIX-005] ... coverage`、`embedding breaker OPENED`、`CACHE` Write error
- `query_cache` 行数与 `hit_count` 周期巡检（缓存命中率陡降 = embedding API 故障）

## 5. 已知残留风险（批次 2 候选）

- `admin_username` 默认 `admin`，建议改为非默认值
- `/api/documents` 等只读接口的鉴权粒度（依赖 router 级认证，未见字段级过滤）
- SQLite 单文件存储的并发上限（约 10 并发用户下可接受，扩容需迁 pgvector）
- 上传异步任务 `asyncio.create_task` 无持久化，进程重启丢失任务状态
