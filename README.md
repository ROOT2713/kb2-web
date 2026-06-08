# kb-web 2.0 — 知识库 Web 服务

基于 Hindsight + LLM 的智能文档检索与问答系统。

## 快速开始

```bash
cd backend
cp ../../.env.example .env
# 编辑 .env 填入配置

pip install -e ..
uvicorn app.main:app --host 0.0.0.0 --port 3002
```

## 项目结构

```
kb2-web/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI 路由层（upload/query/documents/banks/synonyms/admin）
│   │   ├── services/     # 业务逻辑层（parsing/chunking/retrieval/generation/cache）
│   │   ├── models/       # SQLAlchemy 数据模型
│   │   ├── repositories/ # 数据访问层
│   │   ├── middleware/    # 鉴权/错误处理
│   │   ├── utils/        # 工具函数（text_cleaning/tokenizer/embeddings）
│   │   ├── config.py     # Pydantic Settings 配置
│   │   └── main.py       # FastAPI 入口
│   ├── migrations/       # Alembic 数据库迁移
│   └── tests/            # 测试
├── frontend/             # Vue 3 + Vite 前端（Phase 3）
├── scripts/              # 部署/迁移/辅助脚本
├── docs/                 # 文档
├── .env.example          # 环境变量模板
├── pyproject.toml        # 依赖管理
└── README.md
```

## 架构

```
前端 (Vue 3) → Nginx → FastAPI (后端)
                          ├── API 路由层
                          ├── 服务层（解析/分块/检索/生成/缓存）
                          ├── Repository 层（SQLite + Hindsight）
                          └── 工具层（清洗/分词/嵌入）
```

## 开发路线

- [x] Phase 1: 项目骨架（当前）
- [ ] Phase 2: 核心服务移植（从 v1）
- [ ] Phase 3: API 模块化 + Vue 3 前端
- [ ] Phase 4: 测试 + 数据迁移工具
- [ ] Phase 5: 灰度上线

## 与 v1 的关系

kb2-web 是 kb-web 的完全重写版本。v1（`~/kb-web/`）保持运行，v2 开发期间 v1 仅做 Bug 修复。
