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

## 📊 当前状态（2026-09-05 更新）

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
