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

## 🔐 安全审计整改记录（2026-09-03）

> 外部安全审计（kb2-web-audit-delivery）+ CC（Claude Code）独立复审双轮驱动，
> 共 6 commits：外部审计整改 0001-0006 → 写路径归一化 → 缓存计数修复 → 验收测试 → CC-R2 整改 → M1 误报回滚。

### 问题清单与修复（按发现顺序）

| # | Commit | 级别 | 发现的问题 | 修复内容 |
|---|--------|------|-----------|---------|
| 1 | `cb711d5` | **P0** | 检索过滤用 `documents.bank`，写入用 `hs_bank`，两侧口径不统一 → 定向 bank 检索漏数据/串数据 | FIX-001：bank→hs_bank 过滤口径统一，`doc_bank_filter` 映射（query.py/standard_boost.py/retrieval.py） |
| 2 | `cb711d5` | **P0** | 缓存无用户隔离（A 用户命中 B 用户私有文档缓存）；拒答内容也入缓存；cache-clear 无 admin 提权 | FIX-002：缓存 `scope` 用户隔离 + 拒答不入缓存 + cache-clear 仅 admin |
| 3 | `cb711d5` | **HIGH** | JWT 密钥可为空/默认 CHANGE_ME/<32 字符，密钥强度无守卫 | FIX-003：JWT 密钥三重守卫（空/CHANGE_ME/<32 字符直接拒启） |
| 4 | `cb711d5` | **HIGH** | 上传无扩展名白名单，任意文件可入库；/batch basename 未清理 | FIX-004：上传扩展名白名单 + /batch basename 清理 + 单文件上限 |
| 5 | `cb711d5` | **P1** | searchable=1 无质量门（embedding 失败也标记可检索）；embedding 同步阻塞无重试 | FIX-005：searchable 质量门（覆盖率≥80%）+ embedding 异步化/重试/熔断 |
| 6 | `cb711d5` | **P2** | 无部署加固文档（nginx 反代/生产清单缺失） | FIX-006：`deploy/nginx.conf.example` + `deploy/PRODUCTION-CHECKLIST.md` |
| 7 | `cb711d5` | 附加 | 审计补丁自身缺陷：`_ensure_scope_column` 的 `text(...).fetchall()` 括号错位 → **迁移静默失败**，存量库 scope 列永不补建 | 修正括号；验收测试覆盖幂等/默认值 |
| 8 | `cb711d5` | 附加 | `_verify_searchable` 硬编码 `coverage_pct=80.0` + recall 命中即翻 1 = **reparse 后门**（绕过质量门） | searchable 由质量门统一决定，删硬编码后门 |
| 9 | `cb711d5` | 附加 | upsert embedding 失败 chunk 跳过入库但计数虚高（`retained` 虚高绕过质量门）；补插切片 `memory_items[retained:]` 与分批错位 → **重复 chunk** | embedding 失败跳过并计数，返回真实有效数；补插 `append=True+offset=retained` |
| 10 | `7836e13` | P1 | 写路径 legacy bank key（standards/industry_docs/咨询）不在 BANKS → `get_bank_config` 回退 all → **hs_bank='kb' 黑洞**（检索不可达） | 写路径按存量库实证主值直映射 `kb_standard/kb_industry/kb_xhs/kb_general`，`kb_` 前缀透传 |
| 11 | `7836e13` | P1 | `require_admin` 未配置 admin_password 时 **fail-open**（直接放行） | 改 fail-closed：503 拒绝，管理端点必须显式配置密码 |
| 12 | `4762aa4` | P2 | `query_cache.hit_count` INTEGER 无 DEFAULT + INSERT 未给值 → NULL；命中 `NULL+1=NULL` **计数永不累加**；LRU 排序失真 | INSERT 显式 `hit_count=0` + 存量 NULL 归零（运行时验证发现） |
| 13 | `a336b9d` | **C1** | upsert embedding 失败逐条散点计数 → 补插切片错位（重复 chunk） | 整批原子抛异常，upload 按失败批次精确重试 |
| 14 | `a336b9d` | **M1** | CC 认为 `/query` 匿名可达（旧 query.py 无显式认证） | **误报**——router.py 聚合层 `APIRouter(dependencies=[Depends(get_current_user)])` 早已全站强制 JWT（见 #16 回滚） |
| 15 | `a336b9d` | **C2** | pgvector 连接串含明文默认口令（0003 只清了 JWT，漏了 pgvector） | `config.py` 默认清空 + 启动守卫，连接串移至 `.env` |
| 16 | `a336b9d` | L1/L2 | 写路径兜底 `kb_<key>` 与读路径映射漂移；质量门未过仍跑 3 次 recall（~100s 浪费） | L1：`LEGACY_BANK_TO_HS` 共享常量同口径；L2：质量门未过直接 `searchable=0` 返回 |
| 17 | `981ab81` | 回滚 | M1 整改（/query 匿名化）**双重误报**：CC 未查 router 聚合层 + 我方只 diff query.py 单文件未看 router.py → 误删端点级认证 | 回滚恢复 `Depends(get_current_user)`（纵深防御显式化），删无用 `get_optional_user`；保留 C1/C2/L1/L2 真实修复 |

### 新增验收测试（2813dc2 + a336b9d）

- `backend/tests/unit/test_audit_fix_acceptance.py`（13 道）+ CC-R2 增补（14 道）覆盖：
  `_ensure_scope_column` PRAGMA 修复 / `hit_count` 从 0 累加（NULL+1=NULL 回归防护）/ scope 用户隔离+默认域共存 /
  `doc_bank_filter` 未知 bank 告警 / upsert embedding 失败**整批原子抛异常**+全成功入库回归 / `_verify_searchable` 质量门（覆盖率≥80%，无硬编码后门）
- 全量后端测试：**442 passed**（1 个既有环境失败=checklist LLM 依赖，与基线一致）

### 关键教训（写入代码库的工程经验）

1. **端点级认证变更前，必须先查 router 聚合层全局依赖**（`APIRouter(dependencies=[...])`）再定性"破坏性"——M1 双重误报的根因。
2. **缓存列无 DEFAULT + INSERT 不全列清单** = 静默 NULL 陷阱（`NULL+1=NULL`），排查"计数不涨"先查 DDL。
3. **bank 路由是双写两侧的事**：写路径 hs_bank 推导静默回退 'kb' 是黑洞，读路径映射与写路径必须同口径共享常量。
4. **fail-open 是默认的安全反模式**：未配置密码/密钥时拒绝服务（fail-closed），而不是放行。
5. **质量门不能有后门**：`_verify_searchable` 曾可被 reparse 的 recall 命中直接翻 1 绕过。

---

## 📊 当前状态（2026-09-03 更新）

| 指标 | 数值 |
|------|------|
| 后端测试 | **442 passed**（含审计整改验收测试 13+14 道） |
| 安全审计整改 | 17 项问题全闭环（外部审计 0001-0006 + 附加 5 项 + CC-R2 5 项 + M1 回滚） |
| 缓存命中计数 | 已修复（hit_count NULL→0 累加） |
| 认证/密钥 | JWT 三重守卫 + require_admin fail-closed + pgvector 口令出代码 |
| 文档数 | **182 篇 active**（跨多 banks，见上表） |

### 历史状态（2026-07-01 存档）

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
