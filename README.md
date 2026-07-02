# kb2-web — 知识库 Web 服务 v2

基于 **FastAPI + Vue 3 + Hindsight** 的政务信息化知识库 Web 服务，支持多 bank 知识库管理、BM25+Dense 混合检索、LLM 问答生成。

> 从 V1 架构完全重写，当前替代 V1 作为生产环境。

---

## ✨ 核心特性

| 特性 | 说明 |
|------|------|
| **混合检索** | BM25(初筛) → Hindsight Dense(向量排序) → top-K → LLM 生成，支持多 bank 并行召回 |
| **知识库管理** | 上传(单文件/批量/文件夹)、文档 CRUD、重解析、缓存管理 |
| **取费表查询** | `fee_utils` 关键词评分 D2-B 注入，16 种子词+金额档位评分排序 |
| **同义词扩展** | 158 条同义词映射在检索层扩展 query，零 prompt 膨胀 |
| **L2 语义缓存** | 基于语义指纹的查询缓存，nocache 参数控制 |
| **多用户权限** | admin/viewer 双角色 + JWT + 路由级 require_role |
| **Domain 过滤** | 按领域关键词自动路由到对应 Hindsight bank |
| **OKF 信息架构** | Document 12 字段 + Concept/KGTriple/QualityGate + Concept Summary 上浮 |
| **66 题质量评估** | 并行测试脚本，66 道真实政务场景题，当前通过率 **74.2%** |

---

## 🏗️ 架构概览

```text
┌─────────────────────────────────────────────────────┐
│                    Vue 3 SPA                         │
│  (Axios + JWT + Pinia + 来源卡片 + 文档管理)         │
└─────────────────────┬───────────────────────────────┘
                      │ POST /api/query (Form) + JWT
                      ▼
┌─────────────────────────────────────────────────────┐
│                  FastAPI (:3027)                      │
│                                                      │
│  ┌─────────┐ ┌──────────┐ ┌───────────┐ ┌─────────┐ │
│  │ api/    │ │ services/│ │repositories││ models/  │ │
│  │ 路由层  │ │ 业务逻辑 │ │ 数据访问  │ │ SQLAlch.│ │
│  └────┬────┘ └────┬─────┘ └─────┬─────┘ └────┬────┘ │
│       │           │             │            │       │
│  ┌────┴───────────┴─────────────┴────────────┴────┐  │
│  │            utils/ + middleware/ + config/       │  │
│  └────────────────────────────────────────────────┘  │
└──────────┬───────────────────────────────────────────┘
           │
    ┌──────┴──────┐
    │  SQLite     │  Hindsight (:8888)
    │  (kb.db)    │  (Dense/BM25 检索)
    └─────────────┘
```

---

## ⚡ 快速开始

### 前置依赖

- Python 3.10+
- Node.js 18+
- SQLite 3
- Hindsight 服务 (`:8888`)
- MinerU API Key（文档解析）

### 后端启动

```bash
cd backend
pip install -r requirements.txt
# 或使用虚拟环境
/home/ubuntu/.hermes/hermes-agent/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 3027
```

### 前端开发

```bash
cd frontend
npm install
npm run dev          # 开发模式
npm run build        # 生产构建
```

### 生产服务（systemd）

```bash
sudo systemctl status kb2-web.service
sudo systemctl restart kb2-web.service
curl -sS http://127.0.0.1:3027/health
```

---

## 📁 项目结构

```
kb2-web/
├── backend/
│   ├── app/
│   │   ├── api/           # FastAPI 路由层
│   │   │   ├── auth.py         # 登录/注册/JWT
│   │   │   ├── query.py        # 核心查询端点
│   │   │   ├── upload.py       # 文档上传(batch+单文件)
│   │   │   ├── documents.py    # 文档 CRUD
│   │   │   ├── banks.py        # Bank 管理
│   │   │   ├── synonyms.py     # 同义词管理
│   │   │   └── admin.py        # 管理面板
│   │   ├── services/
│   │   │   ├── retrieval.py    # 检索管线(BM25+Dense+RRF)
│   │   │   ├── generation.py   # LLM 问答生成
│   │   │   ├── chunking.py     # 切片策略
│   │   │   ├── parsing.py      # 文档解析(MinerU/pypdf)
│   │   │   ├── fee_utils.py    # 取费表评分注入
│   │   │   └── cache.py        # L2 语义缓存
│   │   ├── models/         # SQLAlchemy 模型
│   │   ├── repositories/   # 数据访问层
│   │   ├── middleware/     # JWT/错误处理
│   │   └── main.py         # FastAPI 入口
│   ├── migrations/     # Alembic
│   ├── scripts/        # 数据同步/回填/评估脚本
│   └── tests/          # 单元+集成测试
├── frontend/           # Vue 3 + Vite + Pinia
│   ├── src/
│   │   ├── views/      # 页面组件
│   │   ├── components/ # 通用组件(来源卡片/文档列表等)
│   │   └── stores/     # Pinia 状态管理
│   └── dist/           # 构建产物
└── README.md
```

---

## 🔌 主要 API

| 能力 | Endpoint | 说明 |
|------|----------|------|
| 登录 | `POST /api/auth/login` | JSON：username/password，返回 JWT |
| 查询 | `POST /api/query` | Form：q, bank, nocache, rerank, history |
| 联网搜索 | `POST /api/query/web-search` | Form：q, bank, context |
| 单文件上传 | `POST /api/upload` | 文件 + bank + title |
| 批量上传 | `POST /api/upload/batch` | 多文件 + 预检 + 分批 |
| 文档管理 | `/api/documents/*` | 列表、详情、删除、重解析 |
| Bank 管理 | `/api/banks/*` | Bank 列表、配置、wiki tree |
| 同义词管理 | `/api/synonyms/*` | CRUD |
| 管理面板 | `/api/admin/*` | stats、health、cache invalidate |

---

## ⚙️ 关键技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 检索引擎 | Hindsight (BM25+Dense) | 自托管，低延迟，SQLite 原生集成 |
| 文档解析 | MinerU (优先) → pypdf (降级) | MinerU 高精度保留表格/公式 |
| LLM | DeepSeek V4 (OpenRouter) | 成本低、中文表现强 |
| 缓存 | L2 语义缓存 | 相似 query 命中，nocache 强制绕过 |
| 鉴权 | JWT + require_role | 轻量、stateless、支持 admin/viewer |
| 数据存储 | SQLite (共享 V1) | 无需额外 DB 服务，双写策略待定 |

---

## 🧪 测试与评估

```bash
# 后端测试
cd backend && /home/ubuntu/.hermes/hermes-agent/venv/bin/python -m pytest -q

# 前端构建
cd frontend && npm run build

# 服务健康检查
curl -sS http://127.0.0.1:3027/health

# 66 题质量评估（nocache）
cd backend && /home/ubuntu/.hermes/hermes-agent/venv/bin/python scripts/kb2_66test_v3.py
```

---

## 📊 当前状态（2026-07-01）

| 指标 | 数值 |
|------|------|
| 66 题通过率 | **49/66 (74.2%)**（+13.6pp 自 6/30） |
| 真过拒数 | **2**（CC 审查确认，均检索层修复） |
| 取费表 D2-B 命中率 | **100%**（idx=37-55 费率表全量注入） |
| 后端测试 | 374 passed |
| 文档数 | ~140 篇（跨 6 banks） |

### 三方案整合路线图

已输出 PDF 评估报告 → 执行顺序：

```
Phase 1 (2周): OKF 底座收尾 + 前端 P0 贴面剂
Phase 2 (3周): GraphRAG 图谱检索 + 实体抽取
Phase 3 (2周): 前端深度重构（Loop工程 + 查询工作台）
```

---

## 🗺️ 相关链接

- [kb2-web Wiki](http://rogerz-ROOT2713-7y3p7v5g8xtq-3006.us.kg/) — 项目架构图/改造档案/更新日志
- [Hindsight](https://github.com/vectorize-io/hindsight) — 检索后端
- [MinerU](https://github.com/opendatalab/MinerU) — PDF 文档解析
- [anti-ai-plastic-ui](https://github.com/NousResearch/hermes-agent) — 前端设计规范参考

## 许可证

MIT
