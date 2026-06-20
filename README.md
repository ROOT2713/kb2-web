# kb-web 2.0 — 知识库 Web 服务

kb2-web 是 kb-web V1 的 Fork 2.0 重写版，基于 FastAPI + Vue 3 + Hindsight + LLM，目标是在灰度验证完成后替代 V1。

## 当前状态

| 组件 | 路径 | 端口/服务 | 状态 |
|---|---|---|---|
| V1 kb-web | `/home/ubuntu/kb-web` | `:3002` / `kb-web.service` | 生产基线，只修 Bug |
| V2 kb2-web | `/home/ubuntu/kb2-web` | `:3027` / `kb2-web.service` | 灰度建设与验证 |
| Hindsight | 服务依赖 | `:8888` / `hindsight.service` | V1/V2 共用检索后端 |

V2 已完成模块化后端、Vue 前端、JWT 登录、上传/查询/文档管理、Bank 管理、同义词管理、Admin/Wiki 页面和 V1 compatibility alias。当前仍需完成真实端到端 smoke、查询质量回归、V1/V2 数据边界治理后再全量替代 V1。

## 快速开始（本机开发）

```bash
cd /home/ubuntu/kb2-web/backend
/home/ubuntu/.hermes/hermes-agent/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 3027
```

前端开发：

```bash
cd /home/ubuntu/kb2-web/frontend
npm install
npm run dev
```

生产服务由 systemd 管理：

```bash
sudo systemctl status kb2-web.service
sudo systemctl restart kb2-web.service
curl -sS http://127.0.0.1:3027/health
```

## 项目结构

```text
kb2-web/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI 路由层：auth/upload/query/documents/banks/synonyms/admin
│   │   ├── services/     # 业务逻辑：parsing/chunking/retrieval/generation/cache/quality
│   │   ├── models/       # SQLAlchemy 模型
│   │   ├── repositories/ # 数据访问层
│   │   ├── middleware/   # JWT/Basic Auth/错误处理
│   │   ├── utils/        # 文本清洗、分词、embedding 等工具
│   │   ├── config.py     # Pydantic Settings
│   │   └── main.py       # FastAPI 入口、SPA 挂载、V1 compatibility aliases
│   ├── migrations/       # Alembic
│   ├── scripts/          # 数据同步/回填/对比脚本
│   └── tests/            # unit + integration tests
├── frontend/             # Vue 3 + Vite + Pinia 前端
├── docs/                 # 项目文档和评估脚本
└── README.md
```

## 架构

```text
Vue 3 SPA
   │ Axios + JWT
   ▼
FastAPI app (:3027)
   ├── api/          路由层，处理 HTTP、表单、鉴权、响应结构
   ├── services/     解析、分块、Dense/BM25/RRF/Rerank、生成、缓存
   ├── repositories/ SQLite/Hindsight 访问封装
   ├── models/       documents、parent_chunks、query_cache、synonym_map
   └── frontend/dist SPA 静态文件与 history fallback
```

## 主要 API

| 能力 | Endpoint | 说明 |
|---|---|---|
| 登录 | `POST /api/auth/login` | JSON：`username/password`，返回 JWT |
| 查询 | `POST /api/query` | Form：`q`, `bank`, `nocache`, `rerank`, `history` |
| 联网搜索 | `POST /api/query/web-search` | Form：`q`, `bank`, `context` |
| 上传 | `POST /api/upload` | 单文件上传 |
| 批量上传 | `POST /api/upload/batch` | 多文件上传，返回逐文件结果 |
| 文档管理 | `/api/documents/*` | 列表、详情、内容、删除、重解析、审计 |
| Bank 管理 | `/api/banks/*` | Bank 列表、配置、wiki tree |
| 同义词 | `/api/synonyms/*` | CRUD |
| Admin | `/api/admin/*` | stats、health、cache invalidate、bank config |

V1 compatibility aliases 保留在 `backend/app/main.py`，用于兼容旧路径，例如 `/api/stats`、`/api/wiki`、`/api/categories`、`/api/web-search` 等。旧路径仍受 JWT 保护。

## 测试与构建

后端：

```bash
cd /home/ubuntu/kb2-web/backend
/home/ubuntu/.hermes/hermes-agent/venv/bin/python -m pytest -q
```

前端：

```bash
cd /home/ubuntu/kb2-web/frontend
npm run build
```

服务 smoke：

```bash
curl -sS http://127.0.0.1:3027/health
```

涉及查询质量或新 RAG 逻辑时，必须使用真实 `/api/query` 并加 `nocache=true`，避免 L2 语义缓存误导验证。

## V1 与 V2 的关系

- V1 继续运行在 `:3002`，作为生产基线和回滚路径。
- V2 运行在 `:3027`，承接新功能和灰度验证。
- V1 原则上只修 Bug，不再新增功能。
- V2 在完全替代 V1 前，必须通过：后端测试、前端构建、真实上传/查询/删除 smoke、V1/V2 查询质量对比、compatibility alias 验证。
- 当前数据面仍需明确治理：部分配置会复用 V1 数据路径和 Hindsight bank。切流前必须确认共享库/独立库策略和回滚方案。

## 当前优先事项

1. 保持工作区可审查：大改动按功能拆 commit，避免混合提交。
2. 补齐真实端到端 smoke：上传 → 查询召回 → 删除 → 查询不再召回。
3. 重跑查询质量评估：短测 30 题，稳定后跑 120 题，所有请求使用 `nocache=true`。
4. 审核 V1 compatibility aliases：未登录 401、登录后方法/参数/Location 兼容。
5. 明确 V1/V2 数据边界：共享数据库、共享 Hindsight、双写或迁移策略。

## 常用命令

```bash
# 服务状态
sudo systemctl status kb2-web.service
sudo journalctl -u kb2-web.service --since '10 min ago' --no-pager

# 后端测试
cd /home/ubuntu/kb2-web/backend
/home/ubuntu/.hermes/hermes-agent/venv/bin/python -m pytest -q

# 前端构建
cd /home/ubuntu/kb2-web/frontend
npm run build

# 路由表
cd /home/ubuntu/kb2-web/backend
/home/ubuntu/.hermes/hermes-agent/venv/bin/python - <<'PY'
from app.main import app
for r in app.routes:
    methods = ','.join(sorted(getattr(r, 'methods', []) or []))
    path = getattr(r, 'path', '')
    if path.startswith('/api') or path == '/health':
        print(f'{methods:18} {path}')
PY
```
