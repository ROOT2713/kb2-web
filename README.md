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
| **66 题质量评估** | 并行测试脚本，66 道真实政务场景题（历史存档通过率 74.2%，见文末） |

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
- SQLite >= 3.25（依赖窗口函数 `ROW_NUMBER() OVER` 与 JSON1；Ubuntu 22.04+ 自带 3.37 满足）
- Hindsight 服务 (`:8888`)
- MinerU API Key（文档解析）

### 账号与权限

- **admin 账号 = `.env` 配置账号**（`ADMIN_USERNAME`/`ADMIN_PASSWORD`），即超级管理员，不经 User 表校验。
- 若 DB `users` 表存在与 `ADMIN_USERNAME` 同名的低权用户：同名者走角色校验（防撞名提权）；配置账号本身始终直通。
- viewer 等普通用户在 `users` 表 + 前端登录页双通道。

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
| 数据存储 | SQLite (kb.db 元数据) + pgvector (向量) | 元数据/缓存 SQLite，chunk 向量 pgvector；registry 打标隔离孤儿 |

---

## 🧪 测试与评估

```bash
# 后端测试
cd backend && /home/ubuntu/.hermes/hermes-agent/venv/bin/python -m pytest -q

# 前端测试（vitest + jsdom）
cd frontend && npx vitest run

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
- 全量后端测试：**443 passed**（1 个既有环境失败=checklist LLM 依赖，与基线一致）

### 关键教训（写入代码库的工程经验）

1. **端点级认证变更前，必须先查 router 聚合层全局依赖**（`APIRouter(dependencies=[...])`）再定性"破坏性"——M1 双重误报的根因。
2. **缓存列无 DEFAULT + INSERT 不全列清单** = 静默 NULL 陷阱（`NULL+1=NULL`），排查"计数不涨"先查 DDL。
3. **bank 路由是双写两侧的事**：写路径 hs_bank 推导静默回退 'kb' 是黑洞，读路径映射与写路径必须同口径共享常量。
4. **fail-open 是默认的安全反模式**：未配置密码/密钥时拒绝服务（fail-closed），而不是放行。
5. **质量门不能有后门**：`_verify_searchable` 曾可被 reparse 的 recall 命中直接翻 1 绕过。

---

## 🗄️ 数据治理整改记录（2026-09-04）

> 0904 数据治理全景核查：主 agent 定性 + CC 独立审计（deleg_b10a31fe）双轨收敛，
> 交付物：交接文件 `kb2-data-governance-0904-handoff.md` + 本记录 + 整改 commit `e5f6152`。

### 问题定性（已闭合验证）

- **真孤儿 13,711 条** = 13,706（2026-06 批次 BGE-M3 回填）+ 5（08 月波次）；pg 总 doc 13,897 = 13,891 backfill + 6 真实上传。
- 数字闭合：13,897 − 186（SQLite 交集）= 13,711；06 批次 content 与 memory_units.text **100% 精确重叠**（BGE-M3 回填铁证）。
- 判定：**中等数据治理缺陷，非灾难性数据丢失**。根因 = 回填未落 SQLite 元数据（系统缺陷 ~70%）+ 低价值自然淘汰（~30%）。
- 恢复锚点：storage/backups 5/30 备份存 40 个源 PDF（GY 5055、GB/T 43206、造价指导书 Part1-3 等独有业务资料）。

### 整改方案（修订版 A，用户拍板执行）

| 层 | 措施 | 落地 |
|----|------|------|
| 一档回填 | 359 个**有 title** 孤儿（6月批次 354 + 8月 5）→ SQLite `documents` 建行 | `backfill_0904_registry.py`（幂等/dry-run 默认）；source=backfill_0904, searchable=1, active, coverage=1.0 |
| 检索端过滤 | pgvector 语义召回仅放行 `metadata->>'registry'='1'` 的 doc | `vector_repo.query_by_embedding` CTE WHERE（【FIX-0904】） |
| 防复发 | 所有写入口（upload/refetch/reparse）新 chunk 默认注入 `registry:1` | `vector_repo._chunks_to_rows` meta.setdefault |
| 数据保留 | 13,352 无 title 孤儿**不删除**（吸取"清库无保留"教训），仅检索不可见 | registry 未打标 = 天然隔离 |

### 整改后状态（运行时验证）

- SQLite documents：203 → **562**（+359 backfill，全部 active+searchable）
- pg registry=1：**545 doc / 10,032 chunks**（186 原 sqlite∩pg + 359 回填）
- 冒烟（真实查询, nocache, doc_id 级断言）：孤儿泄漏 **0/3**；回填文档（东莞造价指南/GB/T 25000.51）检索命中 ✓
- 语义过滤损耗：被排除 chunk **无一有 title**（0 合法损失）
- 已知残留（P4，不阻塞）：359 回填中部分与存量 doc 同标题重复（如 25000.51 现 2 份），源自历史多次入库，待后续去重治理

### 关键教训

1. **回填/打标脚本的集合必须在写操作后动态重算**——初版 tag 集合在 INSERT 前固定，359 个新回填行全部漏标（若上线会被检索端过滤误杀），verify 段 `cur.execute().fetchone()` 链式调用在 psycopg2 下返回 None 崩溃。
2. **psycopg2 `cursor.execute()` 返回 None**，不可链式 `.fetchall()/.fetchone()`。
3. **SQLite 路径双硬链接**（/home/ubuntu/kb-web/data/kb.db ≡ /data/projects/kb-web/data/kb.db 同 inode）——改库前须以服务进程 environ 的 DB_PATH 为准，勿凭记忆判断。
4. **冒烟断言必须用 doc_id 引用级**而非响应全文子串——LLM 回答会复述查询词，全文搜必假阳性。
5. **API 契约实测**：POST /api/query 用 form（q + bank=all + nocache=1），非 JSON；bank="kb" 非法 400。

---

## 🔐 第二轮外部审计（R2）整改记录（2026-09-04）

> 独立外部审计 kb2-web-audit-r2（基线 `main@526df74`）17 项发现，经 CC（Claude Code）
> 对抗复审 + 行为级/语义级测试 + 重启后运行时冒烟三层验证，全数闭环。
> commits：`d859513 → e395ffa → fa8661b → 59738db → d77a802`（均已推送 origin/main）。

### 问题清单与修复

| # | Commit | 级别 | 发现的问题 | 修复内容 |
|---|--------|------|-----------|---------|
| R2-1 | `d859513` | P0 | `generation.chat()` 网络异常/5xx/非 JSON 响应裸抛 500 | httpx 异常捕获 + 指数退避重试(≤15s) + 非 JSON 容错（网关 HTML 页）；顺带修复缩进语义：正常路径误入 except 永不 return |
| R2-2 | `d859513` | P0 | 缓存隔离未含 rerank 维度（rr=0/1 串缓存） | `cache_scope=f'{user}\|rr={int(use_rerank)}:{mode}'` 复合键并入三处缓存读写；删死代码 `_use_rerank` |
| R2-3 | `e395ffa` | P1 | 上传任务无并发上限 | `_process_upload_task`→`_impl` + 文件尾同名 wrapper `Semaphore(4)` 限流（调用点零改动，200 硬上限约束无堆积） |
| R2-4 | `e395ffa` | P1 | 缓存 scope 列迁移失败静默继续（旧逻辑可能串用户缓存） | **fail-closed**：`_scope_ready=False` → 缓存 get/set 全禁用（宁缺毋串） |
| R2-5 | `d77a802` | P1 | LRU 驱逐仅按 bank COUNT/DELETE，单 scope 灌爆驱逐全 bank | 窗口函数 `ROW_NUMBER() OVER (PARTITION BY bank, scope)` 分组驱逐，scope 隔离公平；**CC 审查修正排序 DESC**（初版 ASC 误淘汰最热条目） |
| R2-6 | `e395ffa` | P1 | `_verify_searchable` 双份实现（upload/documents 漂移风险）+ pgvector verify 无重试 | 全仓统一 documents 版（质量门 + 3 次 2/4/8s 退避 + searchable=0 保守降级）；upload 主路径补 expected/retained 参数 |
| R2-7 | `e395ffa` | P1 | 上传/重解析后 query_cache 不失效 → 旧答案残留 | `invalidate_query_cache_by_bank(bank)`（DELETE bank IN (目标, all)），upload + reparse 路径均调用 |
| R2-8 | `d77a802` | P1 | `require_role` 未知 min_role **fail-open**（`_role_rank.get→0` 全放行） | 定义期 `raise ValueError`（fail-closed，启动即暴露拼写错误） |
| R2-9 | `d77a802` | P1 | admin 配置用户名无条件直通 → DB 同名低权用户被提权 | 先查 DB：同名存在走角色校验；无同名=配置账号直通（防回归保留） |
| R2-10 | — | P2 | systemd ExecStart 显式 `--host 0.0.0.0` | **不采纳**：前端/浏览器访问需 0.0.0.0 绑定，属部署需求非疏漏；暴露面由云安全组控制 |
| R2-11 | `d77a802` | P2 | 500 错误无 request_id，报障无法关联日志 | error_handler 500 body 增加 `request_id` 字段 + `X-Request-ID` header |
| R2-12 | `d77a802` | P2 | `require_admin`（HTTP Basic 遗留）死 import ×2 | 删除（全仓 0 调用点） |
| R2-13 | `d77a802` | P2 | admin.py 两个相同 `@router.post("/quality/check")` 堆叠 → 路由注册两次 | 删除冗余空装饰器 |
| R2-14 | `d77a802` | P2 | upload.py `confirm_quality` Form 参数从未被读取（死参数 ×2） | 删除（外部脚本/测试仍发送该字段会被静默忽略，无害） |
| R2-15 | `d77a802` | P2 | `invalidate_for_doc` 全表 SELECT 无 WHERE（doc_ids_json JSON 数组无法索引） | `WHERE doc_ids_json LIKE '%doc_id%'` 预过滤（doc_id 仅 hex+`-` 无通配符语义，无注入/无假阴性） |
| R2-16 | `d77a802` | P2 | 检索配置含幽灵库 `kb_咨询`（pg 实测仅 1 条测试残留 chunk） | BANKS 配置移除 + pg 孤儿 chunk 物理删除归零；咨询内容归 `kb_xhs` 口径一致 |
| R2-17 | `d77a802` | P2 | `standard_boost` `IN (:ids)` 传 tuple（SQLAlchemy text 不展开，**实测必 ProgrammingError**，异常被吞仅 warning → 排序静默跳过） | expanding bindparam；异常升级 error+exc_info 暴露 |

### CC 对抗审查（proc_b683aa1336b3）与修正

- **R2-5 P0 修正**：初版 `ORDER BY hit_count ASC` + `rn>max` 删的是最热条目（淘汰热保留冷，与原实现相反，缓存命中率会塌陷）。CC 引行号抓出 → 改 `DESC` + docstring 注明 + 语义级测试（真实 SQLite 复刻 schema，2 scope×5 条，断言存活=各 scope 最热 3 条）。
- 其余 9 项（R2-8/9/11/12/13/14/15/16/17）✅ 无回归。

### 验证方法学（本批）

- **行为级单测** mock 不污染生产库；t6 实证旧写法 ProgrammingError = bug 真实。
- **语义级测试**（R2-5）真实 SQLite 内存库断言存活集合，比 SQL 字符串断言强。
- **重启后运行时冒烟 5/5**：admin 配置账号登录 200（R2-9 直通回归保护）/ admin 端点 200（未误伤）/ 无 token→401 / query 200（9 sources）/ R2-15 真实 DB 0 删除不误伤。
- 单测 9/6 + evict 语义测试全 PASS。

### 关键教训

1. **LRU 驱逐排序方向要对着淘汰目标写**：`ORDER BY ... ASC/DESC` 决定 rn=1 是谁，`rn>max` 删的是尾部——写反 = 静默淘汰最热条目，且"只查数量不查存活集合"的测试捕获不了，必须断言存活集合。
2. **权限 fail-open 是安全反模式**：未知角色应定义期抛错而非默默放行；同名配置账号必须落角色校验，防 DB 低权用户撞名提权。
3. **SQLAlchemy text() 不展开序列绑定**：`IN (:ids)` 传 tuple 必炸且异常被吞时最阴险（功能静默降级），用 `bindparam(expanding=True)` 且异常要升级可见。
4. **JSON 数组列无法索引但可 LIKE 预过滤**：doc_id 字符集（hex+`-`）无通配符语义 → 安全超集粗筛 + JSON 精确判保留，全表扫变点查。

---

## 🔐 第三轮外部审计（R3）整改记录（2026-09-05）

审计对象 `main@d77a802`（2026-09-04，交付包 `0909/kb2-web-audit-r3.zip`）。裁决：R3-1~R3-13 + 审计盲区 B1/B2，其中 P1×2 / P2×3 / P3×9。执行节奏：A 批（P1/P2 + R3-1 降级采纳）当日凌晨闭环 `f0a2b8a`；P3 批次 2026-09-05 闭环 `a6c1003`+`e31e5cd`；R3-13 经实证**重定性**（见下）。

### 问题清单与修复（A 批 = P1/P2，commit `f0a2b8a`）

| # | Commit | 级别 | 发现的问题（根因机制） | 修复内容 |
|---|--------|------|----------------------|---------|
| R3-12 | `f0a2b8a` | P1 | R2-17 修复激活发布时间重排：standard_boost 排序作用于整个 doc_facts（`ORDER BY published_date DESC`），标准号查询被无关新文档压顶 → bank=all R@1 **−21.4pp**（独立复算口径 B 22/39→14/40 全吻合） | 排序收窄为仅注入组：boosted_ids 置顶 + 组内日期倒序，检索组保持相关性原序。CC-C1 补：already-in-search 命中文档也入组，防新旧版本倒挂 |
| B1 | `f0a2b8a` | P1（审计盲区） | banks.json 运行时残留幽灵库 `kb_咨询`/`kb_personal`：审计只核仓库代码（0 处）即判 R2-16 闭环，漏运行时配置注入层——personal 聚合检索会向 2 个不存在的 hindsight 库请求 | banks.json personal 显式 `hindsight=kb_xhs`（真库）。根因 `_normalize_bank_config` 加载即自动补默认 `kb_<key>`——**删键无效**，须显式设真库名；生效路径分裂：/api/banks 每次 reload 实时 vs 写路径模块 BANKS 需重启 |
| R3-2 | `f0a2b8a` | P2 | chat() 重试链无总预算：3×60s + 退避 1+2+4s + 检索 ≈ **283s** 超网关白烧配额（评测 CSV 实锤 c01/c02/c05 Read timed out） | `budget_s` 总预算 96s（≈网关 120s 的 80%）：deadline 钳制单次 timeout=min(llm_timeout, 剩余)，全部重试分支（网络/429/5xx/非 JSON/body 限流）退避前查预算，超时归一 ValueError |
| R3-3 | `f0a2b8a` | P2 | 上传限流覆盖面缺口：Semaphore(4) 只包 `_process_upload_task_impl`，spawn 出的解析/向量化派生任务不在信号量内 | `_BG_SEM(8)` + `spawn_bg()` 统一派生任务（verify/kg/quality）限流 + 异常日志；documents.py 重解析 `_verify_searchable` 也接入（CC-C2） |
| R3-1 | `f0a2b8a` | P1→P3 | LLM 故障降级文本与拒答常量**字节全等**（40 字符）→ "入缓存固化 24h"现网不可触发（机理误报），但字符串比对脆弱性真实 | 采纳方案 A：`_generate_answer` 返回 `degraded=True` 标志（常量替代硬编码比对）+ query.py 写缓存补 LOW_COVERAGE 拦截 + `not degraded` |
| B2 | — | P3 | R3-1 审计对 `_REJECT_MSG_LOW_COVERAGE` 的附带推断错误（L44=L45 文本相同故"漏网路径"不存在） | 审计方推断错误，无需修复；两常量文本相同为设计内 |

**A 批验收**：行为单测 16/16（含 CC-C1/C2 语义）；全量回归 443 passed 62 skipped；48 题黄金集 R@1 **21/39 vs 审计基线 14/39 = +17.9pp**（f01 GB/T 21671-2008 由 rank2 → top1 直接翻案 R3-12）。

### 问题清单与修复（P3 批次，commit `a6c1003` + `e31e5cd`）

| # | Commit | 级别 | 发现的问题 | 修复内容 |
|---|--------|------|-----------|---------|
| R3-4 | `a6c1003` | P3 | stream 死代码：`stream_chat()` 全仓 0 调用点，chat() `stream=True` 分支从不消费 | 删 `stream_chat()` + chat() 的 stream 参数/分支（含 API body `"stream"` 键） |
| R3-9 | `a6c1003` | P3 | 死 import ×30（documents/query/upload/models 等） | AST 精确扫描（import 外 0 引用）+ 跨文件 re-export 保护后逐处删除 |
| R3-5 | `e31e5cd` | P3 | 内部错误文案可串入 answer（deai_postprocess 只做禁用词替换/空行修复，无内容安全过滤） | `deai_postprocess` 前置 `_strip_internal_error_text`：Traceback 块整删 + 内部错误特征行删（LLM API 异常/httpx 错误/Read timed out/rate limit/HTTP 4xx5xx/API*Error）；清洗为空返回原文（上层 degraded 兜底，防空 answer 冒充成功）。新增 4 用例 |
| R3-7 | `e31e5cd` | P3 | 缓存无全局总量上限（仅 (bank,scope) 分区 evict，scope×bank 组合可无限增长） | `_CACHE_MAX_TOTAL=2000` + `evict_global()`：全表 ROW_NUMBER(hit_count DESC, last_hit_at DESC) 删最冷超限条目；set_cache 尾部追加。NULL last_hit_at（未命中）优先淘汰。新增 2 语义用例 |
| R3-10 | `e31e5cd` | P3 | 双套门禁端点冗余：`/quality/check`（单）+ check-all + stats 并存 | 下线单文档端点 `POST /quality/check`（前端/测试 0 调用）；`check_document` 保留供 check-all 内部使用 |
| R3-6 | README | P3 | admin 自锁副作用未文档注明 | README 新增"账号与权限"节：admin=`.env` 配置账号即超级管理员，DB 同名用户落角色校验 |
| R3-8 | README | P3 | SQLite 版本未声明 | README 前置依赖声明 SQLite >= 3.25（窗口函数 + JSON1） |
| R3-11 | README | P3 | R2-16 后 README 表述歧义（LEGACY_BANK_TO_HS 兼容映射） | B1 已清 banks.json 运行时侧（kb_咨询/kb_personal → kb_xhs）；兼容映射 `"咨询"→"kb_xhs"` 为设计内旧名路由（非幽灵配置），本表 + B1 行即澄清 |

### R3-13 重定性（数据治理联动，另立项）

审计主张"存量重复文档 57%（545 行/234 title），查重上线前上传所致，建议保留主版本/标记 superseded"。**实证推翻归因**：

- 重复 348 行构成：**343 行 `source=backfill_0904`**（0904 治理的回填元数据行，parent_chunks=0）+ 真实上传重复**仅 1 组 2 行** + 混合组（上传+回填同名）3 个。
- 检索召回 SQL（retrieval L474/486、query_engine L301/724）与孤儿过滤 title_map（L305）均依赖 `status='active'` → 对 343 回填行标 superseded 会使对应 pgvector 孤儿 chunk **再次失去来源名**（0904 治理成果倒退），不可执行。
- **已执行**（安全子集）：真实上传重复组「网络安全等级保护测评高风险判定实施指引」保留 aeb89ad1（08-21 完整解析 807 chunks/41.6K 字符），298ad3a9（07-20 PyPDF 回退 12 chunks/38.5K）标 superseded + pg 12 chunks 双写删除。
- **决议**：343 回填同名 = 内容层重复（6 月 memory_units 转储批多次转储同文件），与 0904 修订版 A 的检索端过滤/内容去重方案**合并另立项**；本次不动数据。

### 验收测试（P3 批次）

- 全量单测 **397 passed 62 skipped**（含新增 6 用例：R3-5 ×4 + R3-7 ×2）；golden 22 题集成回归 **39 passed**（--run-integration 真库）零回归。
- R3-5 行为验证：正常答案不受影响 / Traceback 块整删 / 错误行删 / 全错误文案保底非空。

### 关键教训

1. **运行时配置是审计盲区**：只核仓库代码 ≠ 闭环——banks.json/`_normalize` 自动补默认可独立于代码制造幽灵库；三方核对须含 `/proc/PID/environ` 实际加载值（B1）。
2. **排序修复先画数据流边界**：日期倒序不是问题，作用域（全 doc_facts vs 注入组）才是（R3-12）。
3. **审计方机理误报也要采纳其方向**："入缓存固化"现网不可触发，但字符串比对脆弱性真实——显式 degraded 标志防未来常量漂移（R3-1）。
4. **重试必须算总账**：单次 timeout 合规 ≠ 链路合规，283s 超网关白烧配额——总预算 = 网关阈值×80%（R3-2）。
5. **回归评测三坑**：nocache=1（缓存命中 sources 空 = 假 MISS）/ source 字段是 `doc` 非 `title` / 长跑增量落盘续跑——否则回归数字失真。
6. **数据治理项先验"重复的构成"再定方案**：545/234 数字对但 98.6% 重复是治理回填行——对治理产物执行审计建议会推翻治理本身；数据操作前必须分层验证 source/parent_chunks/pg 三侧（R3-13）。

---

## 🗄️ 数据治理整改记录（2026-09-04 ~ 2026-09-17）

### 问题定性（三层漂移）

| 层 | 漂移现象 | 根因 |
|----|---------|------|
| **可见性层**（D3） | 旧版 superseded 文档的向量仍可被语义检索命中（"旧版永生"） | 语义检索路径未施加 searchable 门禁，仅 SQLite 侧过滤 |
| **所有权层**（D2） | 孤儿向量（pg 有 / SQLite 无）大量堆积 | supersede 只删 SQLite 不删 pgvector；删除失败被静默吞掉 |
| **机制层**（P2） | 同类漂移只能靠事后人工 SQL 清理 | 无复发拦截、无常态对账、无孤儿 TTL |

### 整改方案（三段式）

按「**先止血 → 再补正主 → 最后清碎片**」顺序推进：

1. **P0 止血** — `registry` 自动打标（`vector_repo.py`）+ 检索 SQL 硬过滤（`metadata->>'registry' = '1'`），让不可见文档在检索层 100% 隔离
2. **P1 治本** — 碎片合并（`p1_batch_recover.py` / `p1_execute_plan.py` / `p1_merge_fragments.py`），修复 `parent_chunks` 覆盖
3. **P2 机制化** — 5 个缺口闭环：G1 删除漏 bank 维度 / G2 删除失败静默 / G3 无对账 / G4 无孤儿 TTL / G5 死代码 `delete_by_ids`

### 整改后状态（运行时验证）

| 指标 | 治理前 | 治理后 | 验证方式 |
|------|-------|-------|---------|
| pg `vector_chunks` 行数 | 38,143 | **22,609** | `SELECT COUNT(*)` |
| distinct `doc_id` | 13,574 | **221** | `COUNT(DISTINCT doc_id)` |
| pg 孤儿（SQLite 无对应） | 15,531 | **0** | `p2_reconcile.py` 四类检查 |
| `registry` 打标覆盖率 | — | **100%**（22,609/22,609） | `metadata->>'registry'='1'` |
| HNSW 索引 `idx_vc_embedding` | 397.7 MB | **131 MB** | `REINDEX INDEX CONCURRENTLY` 实测 **99.0s** |
| 库总大小 | 1796.8 MB | **1530 MB** | `pg_database_size` |
| SQLite `documents` | 598（active 221 / superseded 377） | 不变 | 治理只动向量侧 |
| 后端单测 | — | **425 passed / 62 skipped** | `pytest tests/unit`（22.88s 实测） |
| 泄漏检查 | — | 4 组查询多轮**零泄漏** | sources 全部 active 且 searchable=1 |

### 关键教训

1. **检索结果非确定性** —— 同查询多跑可出不同结果（分数等距 0.08 是排名映射，非相似度）。因此**不能靠"比对序列"验证**，必须用**顺序无关的不变量**，即「泄漏检查」：所有 sources 必须 `active` 且 `searchable=1`。
2. **pgvector 0.6.0 的 HNSW 不回收死节点** —— `VACUUM` 无效。删除后想真正回收空间，唯一手段是 `REINDEX INDEX CONCURRENTLY`（在线、无锁、实测 99.0s，397.7 → 131 MB）。
3. **删除必须双写且不可静默** —— 只删一侧 = 制造孤儿；失败静默 = 孤儿无声堆积（P2-G2 已修复为抛 500）。
4. **判"活路径还在"必须实调一次**，不能读代码推断。
5. **`/proc/PID/environ` 是 DB 路径权威** —— 读 `.env` 的 `DB_PATH` 做验证是假验证。
6. **`.gitignore` 说「不入仓」≠「不重要」** —— `frontend/dist` 不入版本库，但它是**运行时依赖**（kb2-web 后端静态托管，非 dev server）。判断「某改动能否回退」之前，先确认它是不是运行时依赖：曾把 build 后的 `dist/index.html` 用 `git checkout` 回退，而 `vite build` 的 `emptyOutDir` 已清空重建 assets ⇒ 回退的 index.html 引用旧 hash 文件 ⇒ **JS 404 前端白屏**，而 `is-active` / `/api/banks` 401 / journalctl 全部正常。前端改动验收链（批次 E 补齐）：`改 src` → `npm run lint`（0 error）→ `vitest` → `vue-tsc 净增 0` → `vite build` → **服务返回的 index.html 引用的每个 `/assets/*` 均 200**，且**懒加载 chunk 也要 200**（SFC 按组件 code-split，视图代码不在 entry 里），最后核对**服务返回的 index.html 与磁盘字节一致**。
7. **「函数有测试」≠「修复有效」—— 必须补接线级与基建守卫级测试** —— 批次 E 把 16 处 `e instanceof Error ? e.message` 收敛为 `getErrorMessage` 时，若只写 `utils/error.spec.ts`，**把全部 16 处回退也依然全绿**（因为函数本身没变）。故分三层：单元级（函数对）→ **接线级**（消费方真的用了：断言后端中文 detail 真到达 `store.error`；断言 ResultCard 真渲染出 `1.3 万字` 而非 `12.3KB`）→ **基建守卫级**（直接 `readFileSync` 断言 `vite.config.ts` 里 dev proxy 不是已冻结的 `:3002`、`package.json` 的 lint 脚本没退回 `--ext`、`eslint.config.js` 没把 `vue/no-v-html` 降级）—— 配置类缺陷**没有任何运行时行为可断言**，只能读文件断言。反向核验时也要把「接线回退」当突变项（本批 M14/M15/M16 正是最有价值的三条）。
8. **断言写太严也是一种错误** —— `format-wiring` 首版断言「渲染结果不得含 `<img>`」直接失败：回答正文链**刻意**允许 `<img>`（Markdown 的 `![alt](url)` 需正常显示图片），只有来源链才 `forbidMedia`。判据必须对准**真实契约**（危险属性 `onerror` 被剥 = 正确），否则会把正确行为判成回归。同理 `infra-guard` 首版断言「配置文件全文不得含 3002」也失败 —— 因为我在**注释里**写了旧端口去解释缺陷；正确判据是「**代码行**不得含旧端口，注释可提及」（剔除注释行后再断言）。
9. **不盲从 linter** —— ESLint 报 `AdminView.vue` 的 `v == null` 违 `eqeqeq`，但 `== null` 是**同时覆盖 null 与 undefined 的惯用法**，改成 `=== null` 会漏掉 `undefined`（真 bug）⇒ 正确做法是**改规则**（`{ null: 'ignore' }`）而非改代码。linter 是工具不是权威，每条告警都要判断「谁错了」。
10. **测试判据必须收敛到具体节点** —— 批次 D 首轮反向核验 12/13，M11（渲染退回旧字段）未捕获：C4 的原断言是「全页 text 包含 `ok`」，而 `health.status` 恰好也返回 `'ok'`，**无关字段把断言顺带满足了**（退回旧字段时渲染空串，`not.toContain('undefined')` 也拦不住）。改为**逐行断言**（定位含「向量库」的 `.health-row`，断言其值为唯一值）后即捕获。⇒ 全页 `contains` 是弱判据；组件级测试还要给足数据（分类列表为空时 `<option>` 不存在，jsdom 会把 `select.value` 置回 `''`，会被误读成修复未生效）。
11. **突变测试必须先自证** —— 「测试没变红」既可能是测试没牙齿，也可能是**核验脚本自己坏了**。本轮反向核验 6 项连锁假阴性，根因是还原逻辑 `str.replace("", X, 1)`（空串替换不是无操作，会把旧内容插到文件开头）写坏文件 + 判定漏了 vitest 的第三种形态 `Tests  no tests`。判据必须包含「基线全绿 + 突变后确有收集/断言失败」，否则假阴性会被读成「加固无效」。
12. **后处理会改坏 Markdown 结构，prompt 硬化单独不够** —— `deai_postprocess` 用 `\s+`（含换行）删标点后空白 ⇒ 表格表头被粘到上一行 ⇒ 整张表退化。**教训：给 LLM 加了「照抄硬模板」还不够，链路上任何一步正则都可能把它改坏；改 prompt 类资产时必须同时审后处理链。** 判据 = 结构解析器的 `repair_flags` 在端到端跑完后必须为零（本轮正是它先报 `no_separator` 才定位到该缺陷）。
13. **「落地」≠「生效」≠「被消费」** —— 新模块放进 `app/services/` 只是落地；接进主链路才是生效；有消费方才是被消费（本轮 `answer_blocks` **有意不下发**，因为前端缺 `answerParser.ts` 无消费方）。三者要分开汇报，别用「已完成」一词糊过去。


---

## 🔐 第四轮外部审计（R4）前置整改记录（2026-09-28 ~ 2026-09-29）

> 本章为 R4 送审前的整改与发现汇总。所有结论均附可复现证据；**未修项在第 4 节单列，建议审计方优先复核**。
> 本轮提交链：`6745f6a`(F0) → `912508b`(F1 A组43红) → `352be34`(A6归位) → `954453a`(对拍链路) → `3155300`(测试隔离) → `9dd2645`(基线) → `dd9a7bd`(①到期预警) → `9610829`+`49d77b1`(②F2) → `45e7238`(清理盲区)；kb2-wiki：`de939cd`。

### 1. 本轮定性（一句话）

**本轮多数问题属「静默」类缺陷——不报错、不崩溃、返回成功，但功能实际未生效。** 判据必须落在**目标数据的实际变化**上：`rc=0` ≠ 生效，`文件在 git 里` ≠ 流程可跑，`日志显示成功` ≠ 覆盖了目标数据。三个反例都在本轮实证：三条治理 cron 死了 87 天（rc≠0 被 `>> log` 吞掉）；对拍脚本「已在库」却静默空转；清理作业每天报 `deleted=0`「成功」却从未覆盖非终态任务。

### 2. 问题清单与修复（按严重度）

| 编号 | 严重度 | 问题（现象 → 根因） | 修复 | 提交 | 验证证据 |
|------|--------|--------------------|------|------|---------|
| **N1** | 高 | **三条 kb2 治理定时任务自 2026-07-04 03:00 起 100% 失败（87 次 / 0 成功）**。根因：wrapper 用裸 `python3`，cron 最小 PATH 解析到 `/usr/bin/python3`（3.12，**无 sqlalchemy**），而服务实跑的是 venv `3.11.15` + `sqlalchemy 2.0.50`。失败输出被 `>> log 2>&1` 吞掉，无人可见 | 三个 wrapper 改 **venv 绝对路径** + `START/OK/FAIL` 心跳行；gov-tree 两个日志重定向落盘 | `6745f6a` | 2026-09-29 **首次通电**：03:08:57 / 04:00:02 / 05:00:01 三次 rc=0（§3） |
| **N2** | 高 | **回归基线实证不可用**——对拍链路此前只验证「文件在 git 里」，从未实跑。实跑暴露**三个独立缺陷叠加**（§2.1），22 份快照的关键字段 95% 为 `null`，无法区分「检索变好」还是「变坏」 | 三缺陷逐个修复 + 重生成 + 冻结 | `9dd2645`（+ 路径对齐 `954453a`、隔离 `3155300`） | `compare 100.0% (125/125)`、**回归项 0/22**、exit 0；非空 doc_id **220/220**；连跑两次 **Jaccard=1.00** |
| **N3** | 高 | **bank 解析静默兜底（`or "kb"` 黑洞）**——写路径存在 **9 处各自派生** `hs_bank`，普遍带 `... or "kb"`；而 `"kb"` 在读侧是**全库并行哨兵**（`recall()` 中 `bank in ("all","kb")` 才走并行全库）。后果：内容写进「kb」库后，**任何定向 bank 查询都命中不到**，而上传返回成功 | 新增**唯一解析入口** `app/services/bank_resolver.py`（legacy 映射 / `kb_` 透传 / 业务键查配置，未知键 **422 fail-fast**）；**6 处写路径收口**（`upload` 主路径与 `/batch`、`fetch-standard`、`refetch`、`PATCH /bank` 改为 bank+hs_bank **同写**、`reparse` 把解析**提前到删除之前**）；`save()` 删除 `hs_bank="kb_general"` 善意默认值改必传 + 自洽校验 | `9610829` + `49d77b1` | A 组契约 **43 red → 43 passed**；运行时 `bank=no_such_bank` → **HTTP 422** 且 `upload_tasks` **零新增**（旧代码返 200 并静默落黑洞） |
| **N4** | 高 | **90 天自净空（单向棘轮）**——`status='stale'` 是**终结态且退出检索**（`_filter_invisible` 排除 `status!='active'`），系统**有「退出」无「复验/回归」**。按 active 132 口径：**30 天内 44 篇(33%)、60 天内 89 篇(67%)、90 天内 132 篇(100%)** 将退出检索 | 落**只读「到期预警」脚本**（复用服务端**同一套** `_check_staleness` 规则，杜绝两套规则漂移；watchdog 模式：无事项即静默）+ 每周一 cron；执行段复用既有 `POST /api/admin/stale/restore/{id}` | `dd9a7bd` | 2026-09-29 04:00 **实测开火**：`checked=134, stale=3`，三篇全部 `verification_expired (91d)`（§2.2）；`env -i` 最小环境实测通过（规避 F0 同款 PATH 陷阱） |
| **N5** | 中 | **上传清理盲区 + 18 个僵尸任务**——`cleanup_old_tasks()` 只删**终态**（done/failed），对 **pending/processing 零覆盖**。18 行自 2026-09-18 08:28 滞留 **11 天**（15 pending 停在 `queued 0.000` / 3 processing 停在 `parsing 0.050`，同一批次），而 05:00 作业每天 `deleted=0` 报「成功」⇒ 真实积压被伪装成正常排队，`/tasks` 轮询永远显示「进行中」 | 新增 `UploadTask.cleanup_stale_inflight(max_age_hours=24)`（标记 failed 并写 `error_message` 留痕）；清理作业改**两段式**（先标非终态 → 再删终态超期）并同时输出两个计数 | `45e7238` | 首跑 `inflight_marked_failed=18` / 二跑 `=0`（**幂等**）；非终态残留 **0**；`documents` 未受影响（当时 605/131；**当日重传 1 篇真缺失后为 606/132**）；全量单测 574 passed |
| **N6** | 中 | **kb2-wiki 反复僵死**——`serve.py` = 单线程 `http.server.HTTPServer` + handler **无 `timeout`**。向**已断开**客户端写大文件时 `socket.sendall` **永久阻塞** ⇒ 唯一服务线程卡死 ⇒ 单线程服务器不再 `accept`，而 systemd 仍显示 **active**。实测频率**每 2–4 天一次**（保活日志 09-16/19/21/25），每日 04:30 保活只救一次 ⇒ 每次最长 **~24h 不可用盲窗** | ① `ThreadingHTTPServer`（爆炸半径隔离）② `H.timeout=30`（停滞连接强制回收）③ `handle_error` 覆盖：客户端断开降为单行日志（旧版异常逃逸会打整段 traceback，**本次排障时曾被误读为崩溃**） | `de939cd` | **复现原故障形态**验证：3 条半截请求占住 handler 时正常请求仍 **200（0.03s）**、进程线程数 4；停滞连接在 **30.0s** 被服务端关闭（与 `timeout=30` 精确一致）；journal Traceback **= 0** |
| **N7** | 低 | 测试垃圾文档 `kb_web_report(1)` 长期在库，出现在 `bank=all` 检索结果中 | 走**官方 DELETE 端点**删除（未改代码） | 纯数据操作 | 三层核验：SQLite 404 / pg 向量残留 **0** / `bank='kb'` 黑洞 **0**。⚠️ 顺带坐实：该端点 `doc_hs_bank or "kb"` 在 `hs_bank` 为空时**删不到向量却返回成功**（§4-3） |

### 2.1 基线三缺陷（N2 展开，诊断顺序可复用）

1. **不可见过滤在 pytest 下变成空操作**（最隐蔽）—— `conftest.py` 把 `app.models.database.SessionLocal` 换成**测试内存库**，而 `retrieval.py:24` 在 **import 时**即完成绑定 ⇒ `_get_invisible_doc_ids()`（`retrieval.py:271-273`）读**空库** ⇒ 过滤器整体空转、快照混入 `superseded` 文档。**纯测试保真度缺陷，生产环境无此问题**（生产 `SessionLocal` 指向真实库）。
2. **切片 off-by-one** —— `test_regression_retrieval.py:250` 取 `t[6:]`，而 `"doc_id:"` 是 **7** 字符 ⇒ 每个 doc_id 都带前导冒号。
3. **doc_id 双载体** —— dense 路径把 doc_id 放 **tags**（`doc_id:<uuid>`），BM25 路径放**顶层字段**，`rrf_merge` 以 **bm25 形态覆盖**同键条目 ⇒ 最终结果大部分「只有字段、没有标签」⇒ 22 份快照只剩 **1** 个非空 id。

**诊断顺序（推荐复用）**：先验 **① 非空率** → 再验 **② 合规性**（不得混入 `status!=active` / `searchable!=1`）→ 最后验 **③ 确定性**（同代码连跑两次比**集合**而非逐位，`Jaccard=1.0` 才可用）。三个缺陷分别由这三查捕获。

### 2.2 90 天自净空（N4 定量与实测）

- **规则**：`stale_detection` 规则 2 =「最后验证超过 90 天即置 stale」，而 stale **退出检索**（`_filter_invisible` 排除 `status!='active'`；BM25 索引亦带 `searchable=1 AND status='active'`）。
- **定量**（2026-09-29，active **132**，按 `_check_staleness` 真实规则**逐篇计算退出日**）：**30 天内 44 篇(33%)、60 天内 89 篇(67%)、90 天内 132 篇(100%)**。⚠️ 90 天档 100% 是**结构性**的——`verified_at` 最早的文档，其到期日必然落在 90 天内，系统**不存在「安全区」**；真正的近端压力看 **30/60 天**两档。
- **构成**（stale 95 篇）：**92 篇 `verification_expired`**（验证过期）+ **3 篇 `never_verified`**（从未验证）。当前 active 中 **8 篇无 `verified_at`**（走规则 1，按 `created_at` 计）**124 篇有**（走规则 2）。**已过期却仍为 active 的 0 篇** —— 反向印证 04:00 作业真的在清。
- **实测开火**（2026-09-29 04:00 作业日志）：
  `Marked 3 documents as stale (max_days=90)` / `checked=134, stale=3`
  - `d2c14c7d` 广东省市场监督管理局…CMA 检验检测报告（industry_docs）`verification_expired (91d since last verify)`
  - `9facf681` 为什么 Agent 要引入状态机…（咨询）
  - `eda0ced9` 让 KV Cache「按头分家」…（咨询）
  —— 与整改前的预判**完全一致**，证明 F0 修复后作业已真实运行。
- **定性**：**这是闭环缺失，不是知识老化**。系统只有「退出」没有「复验/回归」，故本质是**单向棘轮**；预警脚本只补上「感知」段，**复验流程仍缺**（§4-8）。

### 2.3 僵尸任务归位：判定「是否已入库」的正确方法（**四轮收敛 18 → 2 → 4 → 1**）

N5 清理出的 18 个僵尸任务，**先要回答「这些内容到底入库了没有」**，否则会把已入库的重复重传、或把真缺失的漏掉。四轮判定的收敛过程本身就是一条方法学：

| 轮次 | 方法 | 结论 | 为什么错 |
|------|------|------|---------|
| ① | 文件名 vs `documents.title` **精确匹配** | 18 篇全「缺失」 | 入库后标题被**规范化重写**（去标准号、加「（文本版）」「（2023年·）」，或直接用正文标题），精确匹配必然全灭 |
| ② | 标题**双向包含** + 标准号/书名号锚点 | 2 篇缺失 | 召回提高了，但**仍漏**——原文件名带「广州市政务服务数据管理局关于…」长前缀、或正文标题**不含标准号**（`GB/T 39786-2021` 在库里只叫《信息安全技术信息系统密码应用基本要求》） |
| ③ | 关键词反查（`title LIKE '%补充%'` / `'%39786%'` 等） | 4 篇缺失 | 反向查询又救回 2 篇，但**无法穷举**关键词，且 `hainan_acceptance_report` 这类英文名查不到 |
| ④ | **`documents.filename` 反查**（入库时记录的原件名） | **1 篇缺失** | ✅ **决定性**：`filename` 是入库时**原样保留**的原件名，与上传任务同一命名空间，**一对一直查** |

**最终结果**：18 篇中 **17 篇已在库（全部 `active`）**，**真正缺失 1 篇** → 已重传。

- 重传对象：《广东省省级政务信息化验收测评服务项目管理指引（试行）》解读（原件 5.6 MB 在 `kb-web/uploads`，从未成功入库）
- 入库：`doc_id 122a2db5`，`bank=industry_docs` / `hs_bank=kb_industry`（与同桶兄弟文档一致），`chunks=24`、`quality=98`、`content_hash` **唯一**（无重复）
- 三层验证：① `searchable=1` / `status=active` / `chunk_count=24` ② `parent_chunks` 24 行 ③ 端到端检索两问**均命中**（第 10 位 / 第 4 位）；pg 侧 24 行、`registry=1`、`bank=kb_industry`

📌 **教训（已写入 §5-4）**：本表第 ① 行若直接汇报，就是**虚报「18 篇未入库」**，并会导致 17 篇的**无谓重传**（重复入库 → 触发 supersede 链 → 检索面污染）。判「某内容是否在库」**首选 `documents.filename`**，不要用标题匹配。

### 3. 三层验证证据（磁盘 → 进程加载 → 运行时生效）

| 层 | 内容 | 证据 |
|----|------|------|
| **① 磁盘** | 语法 / 导入 / 规则自洽 | `pytest tests/unit` **574 passed / 62 skipped / 0 failed**（20.7s）；`bank_resolver` 9 例边界 + 7 例 fail-fast；整应用导入**无循环依赖**；`serve.py` 属性自检 `ThreadingHTTPServer` / `timeout=30`；存量行 `(bank, hs_bank)` 自洽性扫描：**active 132 全部自洽 / 不自洽 0** |
| **② 进程加载** | 新 PID + 启动日志 | kb2-web `MainPID 3920594 → 4141181`，`Application startup complete`，Traceback/ImportError/SyntaxError **= 0**；kb2-wiki `PID → 58995` |
| **③ 运行时生效** | 真实请求（**不是**只测 200） | 查询：`bank=general` → 3 条、`bank=all` → 12 条（响应键 `sources`）；`bank=no_such_bank` → **422** + `upload_tasks` 零新增；kb2-wiki：3 条卡死连接占用下正常请求仍 **200**、停滞连接 **30.0s** 回收 |

### 4. 未修项 / 待定项（**建议审计方优先复核**）

| # | 位置 | 问题 | 影响 | 状态 |
|---|------|------|------|------|
| 1 | `app/api/upload.py:337` `get_by_hash()` | 去重**不过滤 `status`** | 已删除 / 已 stale 的同哈希文档会**挡住重新上传**（用户看到"重复"但库里没有可检索副本） | 未修 |
| 2 | `app/models/database.py` | 未开 **WAL**（实测生产 `journal_mode=delete`、无 `-wal`、7 天内 5 次锁错误） | 并发上传撞 SQLite 锁 → **HTTP 500**。开 WAL 需**瞬时独占锁** = 需要一个维护窗口，属独立授权点 | 未修（待窗口） |
| 3 | `app/api/documents.py:1060` | 官方删除端点用 `doc_hs_bank or "kb"` | `hs_bank` 为空时**删不到向量却返回成功** → 静默孤儿 | 未修 |
| 4 | `app/api/upload.py:463-467` | `detect_existing_doc()` **不排除自身** | `supersedes` **自引用**（文档把"上一版"指向自己） | 未修（系统性） |
| 5 | `banks_config_path` | 指向 **v1 已退役目录** | 该目录一旦被清理，配置**静默退化**，`general` 从合法键变黑洞 | 未修 |
| 6 | 向量库 | pgvector 0.6.0 **HNSW 不回收已删节点** | 索引膨胀（`VACUUM` 无效；唯一回收 = `REINDEX CONCURRENTLY`，在线约 99s） | 未修 |
| 7 | Hermes 侧 | 会话消息落库告警 **22 次/日**；langfuse 遥测超时 **67 次/日** | 与 kb2-web 无直接关联，但会污染整体可观测性 | 待定位 |
| 8 | 流程 | **stale 无复验回归路径**（N4 的根因） | 预警只解决「看得见」，未解决「能回来」；90 天自净空仍会持续发生 | 半解（感知段已补） |
| 9 | 运维 | kb2-wiki 保活**每天仅一次** | 根修后卡死概率大降，但检测窗口仍有 **~24h**；可考虑加密保活或加 socket 级守护 | 待定 |

**口径说明（避免误读）**：`README` 历史存档中的「544 篇 active」为 **2026-09-05** 口径；当前权威口径（2026-09-29）为 `documents` **606 总 / 132 active / 95 stale / 379 superseded**，「可检索」= **active 且 `searchable=1`**。跨存储：pg 覆盖 227 个 doc_id = 606 − 379（superseded），**孤儿 0**；`status='superseded'` 的 379 篇在 pg **无向量属预期隔离态**，**不得据此判「向量缺失」**。另：`metadata.bank`（业务键）与列 `bank`（物理库名）是**设计分层**，二者不一致 93% **不是缺陷**（勿据此判"数据不一致"）；`kb_general` 出现在 `industry` 范围内属**设计意图**（`hindsight_banks` 是列表，industry 跨 6 库 / all 跨 8 库）。

### 5. 关键教训（本轮沉淀）

1. **「部署 / 提交 / rc=0」都不等于「生效」** —— 三条 cron 死了 87 天（`rc≠0` 被 `>> log 2>&1` 吞掉且无人查看）；清理作业每天报 `deleted=0`「成功」却从未覆盖非终态。**判据必须是目标数据的实际变化**，不是进程退出码。
2. **「文件在 git 里」≠「流程可跑」** —— 对拍脚本入库被当作「链路可用」，实跑才发现它**静默空转**、且基线关键字段 95% 为 `null`。任何门禁 / 对拍 / 回归资产，必须**实跑一次**并检查**输出语义**（非空率）。
3. **fail-fast 不能写在异步路径上** —— 把「非法入参 → 4xx」的校验放进 `asyncio.create_task()` 的 worker，**单元测试会全绿**，但客户端拿到的是 **200**（端点先建任务再立即返回），失败只能靠轮询发现且已留下任务记录。**修法 = 双保险**：同步侧在**参数归一化之后、任何副作用之前**预校验（干净 4xx + 零副作用）+ worker 内保留同一道校验兜住绕过 HTTP 的调用方；并按「同一语义的端点集合」扫描（本次 `/api/upload` 与 `/api/upload/batch` 必须同改）。
4. **「字段匹配失败」≠「不存在」** —— 18 个僵尸任务的文件名与库内 `title` 精确匹配**全部失败**，四轮收敛后（18 → 2 → 4 → **1**）实际只有 **1 篇**真缺失，其余 **17 篇早已 `active` 在库**。若按第 ① 轮直接汇报「18 篇未入库」即属**虚报**，并会导致 17 篇的无谓重传（重复入库 → 触发 supersede 链 → 污染检索面）。**正确方法：查 `documents.filename`（入库时原样保留的原件名）**，它与上传任务同一命名空间，可一对一直查；标题会被规范化重写，**不可作为判据**。详见 §2.3。
5. **单线程服务 + 无超时 = 单点僵死** —— 一个客户端的半开连接足以拖垮整个服务，而 systemd 仍报 `active`。可观测性必须覆盖**「端口在听但不应答」**这一形态（本次靠 curl 超时 + `Recv-Q` 积压才发现）。
6. **预期噪音会污染诊断** —— 客户端断开异常打整段 traceback 到 journal，本次排障时**被误读为崩溃**。降噪时要区分「预期事件」与「真故障」：前者降为单行，后者仍打完整堆栈。

---

## 📊 当前状态（2026-09-29 更新）

| 指标 | 数值 |
|------|------|
| 后端测试 | **574 passed / 62 skipped / 0 failed**（`pytest tests/unit`，20.7s 实测）—— 较 09-17 的 531 增 **43**，全部来自 A 组 bank 派生契约 `test_a_group_hs_bank_derivation.py`（修复前 **43 红**，即 N3 的验收靶） |
| **回归基线** | **有效且已冻结**（`9dd2645`）—— 修复三个独立缺陷后 `compare 100.0% (125/125)`、**回归项 0/22**、exit 0；非空 doc_id **220/220**、连跑两次 **Jaccard=1.00** |
| 代码状态 | HEAD **`45e7238`**，已推送 `origin/main`；**kb2-web 已重启生效**（`MainPID 4141181`，`Application startup complete`）；kb2-wiki 修复 `de939cd`（**本地仓库，无远端**） |
| 数据规模 | SQLite `documents` **606 总 / 132 active / 95 stale / 379 superseded**；pg `vector_chunks` **22,605**（`registry` 100%、**孤儿 0**；覆盖 **227** 个 doc_id，恰 = 606 − 379 ⇒ superseded 无向量属**预期隔离态**，非缺失）；对外**可检索口径 = active 且 `searchable=1`** |
| 上传任务 | `upload_tasks` **done=47 / failed=21 / 非终态残留 0**（本轮清理 18 个滞留 11 天的僵尸任务，见 N5） |
| 治理定时任务 | 三条 kb2 治理 cron（**3am 置信度重算 / 4am stale 检测 / 5am 上传清理**）**首次通电成功**，无失败（N1）；gov-tree 备份恢复正常（03:00，652K，保留 7 天）；新增 ① 每周一 09:00 到期预警 cron |
| 服务 | kb2-web `:3027` · kb2-wiki `:3006` · hermes-wiki `:3004` · tianzhi `:3037` 全部 **200** |
| 数据治理（0904） | 主库 `/home/ubuntu/kb-web/data/kb.db`；`PRAGMA integrity_check` = **ok**、`foreign_key_check` = **0 违规**；`profile_confidence` 覆盖 **可检索集 127/127 = 100%**（**active 131/131**；全表 245 有值 / 360 为 NULL，NULL **全部集中在 superseded 历史行**（379 中 359），属预期——0904 回填即按「非 superseded」口径） |

### 历史状态（2026-09-17 存档）

| 指标 | 数值 |
|------|------|
| 后端测试 | **531 passed / 62 skipped**（`pytest tests/unit`，22.1s 实测）—— 批次 B 新增 60（交付包 44 + 接线锁 3 + 接线/回归 13）；改动前基线 471 |
| **前端测试** | **101 passed**（`vitest run`，8 文件）—— `utils/sanitize.spec.ts`（26，渲染链安全）+ `__tests__/contract.test.ts`（23，批次 D 契约回归，含**组件级** `mount QueryView`/`AdminView`）+ 批次 E 新增 52（`utils/{format,error,markdown}.spec.ts` 单元 + `{error,format}-wiring` **接线级** + `infra-guard` **基建守卫级**）；含**反向核验（突变测试）**：安全 9/9、契约 13/13、批次 E **21/21** 全捕获 |
| **前端基建（批次 E）** | **`483fac4` + `7d0b55b`** —— 修掉两条**配置静默空转**：① `npm run lint` 修复前实测 `sh: 1: eslint: not found`（脚本声明了却**无依赖无配置**，且用了 flat config 已移除的 `--ext`）⇒ 落 **ESLint 10** flat config + 装齐依赖，**首跑即报出 5 error / 9 warning**（此前完全不可见），现 **0 error / 1 warning**；② `vite` dev proxy 硬编码 `:3002` = **已冻结的 v1**（kb2-web 在 :3027）⇒ dev 下所有 `/api` 打到旧后端而**构建/运行全不报错**，现默认 `:3027` + `VITE_API_TARGET` 可覆盖（⚠️ 交付包给的版本默认值仍是 :3002，**未照抄**）。另落 `utils/{format,error,markdown}.ts` 三模块**消除三处跨文件重复**：`formatSize` 两份且已漂移（★其中一份把**字符数**当字节显示 `12.3KB`，数字与单位双重错 ⇒ 拆 `formatFileSize`/`formatCharCount`）、错误消息提取 2 份、取消判定 2 份（★须列全 `CanceledError`/`AbortError`/`ERR_CANCELED` 三标记）；`markdown.ts` 把 `sanitizeHtml(marked.parse())` 的**消毒顺序固定进模块**。★ 顺带修 **C3：全仓 16 处** `e instanceof Error ? e.message : '…'` ⇒ **后端中文 detail 全线丢失**（用户只见 `Request failed with status code 400`），全部收敛到 `getErrorMessage` —— 本批**唯一用户可感收益**。★ 两处**不盲从 linter**：`AdminView` 的 `v == null` 是惯用法（改 `=== null` 会漏 undefined）⇒ **改规则**（`eqeqeq {null:'ignore'}`）；`vue/no-v-html` × 3 取**显式豁免**（保留 error 级）而非降级 |
| **前端渲染链安全** | **XSS 收口 + 加固**（`68acba6` + `4cff1b2`）—— 3 条 `v-html` 链（回答正文/来源文本/规范原文）统一收敛至 `utils/sanitize.ts` 的 `sanitizeHtml()`；修复前 5/8 载荷可注入真实元素 + `onerror`，修复后 0/8。加固后 `FORBID_TAGS` **12 → 21 项**（表单家族口径统一 + `svg`/`math` mXSS 面），来源链新增 `forbidMedia` 开关（禁 `img`/`video`/`audio`/`source`/`track`）；独立探针 **6/8 → 0/8 可利用**、**真退化 0** |
| 多假设对比 | **已接线生效**（`d40d269`）—— 前端 `multi_hypothesis` 开关此前被 FastAPI 静默忽略；含缓存隔离（`mh=`/`cat=`）+ 全失败回落单路 |
| **表格硬化与结构可观测** | **批次 B 已落地 + 已接线 + 已生效**（`8c23998` + `52aac15`）—— `answer_structurer.py`（331 行，回答容错解析为区块 + 表格 `repair_flags`）与 `prompt_hardening.py`（120 行，费用表格硬模板 + 输出前列数自检，追加 **779 字符**）落地；接线两处：`_fee_rules` 末尾追加 + `_generate_answer` 返回前 `_structure_telemetry`（坏表记一行 `[STRUCTURE]` 日志，纯指标、不改响应契约）。验证：交付 44 测试 + 3 接线锁全绿，全量 **528 passed**（零回归），反向核验 **9/9**，端到端探针费用 prompt 6312 字符含硬模板 / 非费用不含，单变量 A/B **Δ=779**。CC 审查 **PASS_WITH_WARNING**（0 阻塞），其 2 条建议已落地（`52aac15`）。**已重启生效**（13:50:54，MainPID 3920594）：真实费用查询返回硬化模板 5 列表头 + 5 格对齐分隔行 + 0 处标点粘连，日志 `[FEE_RULES]` 有 / `[STRUCTURE]` 无 |
| **deai 后处理换行缺陷（本轮发现并修复）** | `496386b` + `52aac15` —— `deai_postprocess` 第 3 条规则用 `\s+`（含换行）删标点后空白 ⇒ 「…万元。⏎⏎\| 表头 \|」被粘成一行 ⇒ **表头不再是独立管道行 ⇒ Markdown 表格整张退化**（用户可见：费用回答的表格/表头消失）。改为 `[^\S\r\n]+`（先用 `[ \t]+`，CC 指出会漏掉 U+3000 全角空格 ⇒ 再收窄，见 `52aac15`）；修复前后处理输出与输入 diff 由非空变**空**，7 类 Markdown 结构回归探针 diff 全为空 |
| **前端契约修复（批次 D）** | **5 条静默失效已修**（`58e0071` + `b2b0652`）—— 共性是**不报错、不崩溃，功能就是不对**：**C1** 前端 `grep session_id` **零命中** ⇒ 后端多轮域锁定（复用上轮文档白名单）完全失效 ⇒ 追问「那东莞呢」重新全库检索、**召回漂移**（现 `sessionStorage` 持久化 + 注入 + 回写 + `resetSession`）；**C4** 读 `hindsight` 而后端返 `vector_store` ⇒ 管理页该项**永远空白**；**C5** `abortQuery()` 只清本地状态 ⇒ 后端仍跑满检索 + LLM、**计费照常发生**（现 `AbortSignal` 透传到 axios，新请求先取消旧请求）；**C6** 打 admin 门控的 `/admin/categories` ⇒ viewer 必 **403** 被吞 ⇒ 分类下拉框**静默变空**（现走 `/banks/categories` + 两形态分别解包）；**C7** 哨兵值 `''` 语义过载 ⇒ 分类改回空判 400 **改不回去**（现 `EXCLUDE_DAILY_CATEGORIES` + `toCategoriesParam()`）。**只移植修复逻辑不整包覆盖**（交付包基线 `b0a9dff` 在本仓库不存在），并消掉交付包自身类型硬伤（冗余内联类型缺 `session_id` ⇒ TS2339）—— 参数类型收敛为具名 `PostQueryParams` 唯一来源。**生产实测**：非管理员账号 `/admin/categories` → **403** 而 `/banks/categories` → **200**；多轮 session 第 2 轮回传后**被沿用**、不带则换新会话。CC **PASS_WITH_WARNING**（0 阻塞），其 3 条强烈建议**逐条先实测**：S1 成立且属本批自引入（主路径实测无 `isolated` 而类型必填⇒已改可选 + 回归锁）、**S2 被实测推翻**（`hindsight` 确由后端返回，仅收窄类型）、S3 成立、S4 成立 |
| R3 第三轮外部审计 | **P1/P2 全闭环**（`f0a2b8a`）+ **P3 全闭环**（`a6c1003`+`e31e5cd`）；R3-13 重定性已并入 0904 治理闭环 |
| R2 第二轮外部审计 | **17 项全闭环**（`d77a802`） |
| 代码状态 | HEAD `7d0b55b`，已推送 origin/main；**kb2-web 已重启生效**（MainPID 3920594 @ 13:50:54，`Application startup complete`，后端批次 B 三层验证通过）；**批次 D/E 均为纯前端改动 ⇒ `vite build` 即生效、无需重启**（`/` 200 + 引用的每个 `/assets/*` **及懒加载 chunk** 均 200 + 服务返回 index.html 与磁盘**字节一致**）；`frontend/dist` 已移出 git 跟踪（`36dfa9b`，**仍是运行时依赖**） |
| 数据规模 | SQLite `documents` 598（active 221 / superseded 377）；pg `vector_chunks` 22,609（registry 100%）；`wiki_entries` 62 |
| 库空间 | 1530 MB（HNSW 索引 131 MB）；Hindsight 服务 `inactive` + `disabled` |
| 缓存 | hit_count 累加 + scope 隔离（含 rerank 维度）+ (bank,scope) 分区 LRU + 全局总量上限 2000（R3-7） |
| 权限 | JWT 三重守卫 + require_role fail-closed + admin 同名 DB 用户落角色校验（.env 配置账号即超管） |
| 健壮性 | chat() 总预算 96s（R3-2）+ 上传/派生任务统一限流（R3-3）+ answer 出口错误文案过滤（R3-5）+ 500 带 request_id |
| 检索质量 | 48 题黄金集 R@1 **21/39 vs 审计基线 14/39 = +17.9pp**（R3-12 排序收窄后） |

### 历史状态（2026-09-05 存档）

| 指标 | 数值 |
|------|------|
| 后端测试 | **443 passed**（单测 397 + golden 集成 39；62 skipped 环境项）；R3 P3 批次新增 6 用例 |
| R3 第三轮外部审计 | **P1/P2 全闭环**（R3-12/B1/R3-2/R3-3 + R3-1 降级采纳；`f0a2b8a`）+ **P3 全闭环**（R3-4~R3-11；`a6c1003`+`e31e5cd`）；R3-13 重定性合并 0904 另立项 |
| R2 第二轮外部审计 | **17 项全闭环**（`d77a802`） |
| 代码状态 | HEAD `f0a2b8a` + `a6c1003` + `e31e5cd`，已推送 origin/main；服务重启生效（MainPID 3349354） |
| 缓存 | hit_count 累加 + scope 隔离（含 rerank 维度）+ (bank,scope) 分区 LRU + **全局总量上限 2000（R3-7）** |
| 权限 | JWT 三重守卫 + require_role fail-closed + admin 同名 DB 用户落角色校验（.env 配置账号即超管，README 注明） |
| 健壮性 | chat() 总预算 96s（R3-2）+ 上传/派生任务统一限流（R3-3）+ answer 出口错误文案过滤（R3-5）+ 500 带 request_id |
| 检索质量 | 48 题黄金集 R@1 **21/39 vs 审计基线 14/39 = +17.9pp**（R3-12 排序收窄后） |
| 文档数 | **544 篇 active**（545 − 1 重复旧版标 superseded；含 0904 回填 359） |

### 历史状态（2026-09-04 存档）

| 指标 | 数值 |
|------|------|
| 后端测试 | **443 passed**（含审计整改验收测试 13+14 道；62 skipped 环境项） |
| R2 第二轮外部审计 | **17 项全闭环**（16 修复 + 1 不采纳 R2-10；CC 对抗复审修正 R2-5 P0） |
| 代码状态 | HEAD `d77a802`，全部推送 origin/main；服务已重启生效（MainPID 3205534） |
| 缓存 | hit_count 从 0 累加 + scope 隔离（含 rerank 维度）+ (bank,scope) 分组 LRU 驱逐 |
| 权限 | JWT 三重守卫 + require_role fail-closed（未知角色拒启）+ admin 同名 DB 用户落角色校验 |
| 健壮性 | chat() 指数退避重试 + LLM rerank 统一走 chat + 上传 Semaphore(4) + 500 带 request_id |
| 文档数 | **562 篇 active**（含 0904 回填 359；跨多 banks） |

### 历史状态（2026-09-03 存档）

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
