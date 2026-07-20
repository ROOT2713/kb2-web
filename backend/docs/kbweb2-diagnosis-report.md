# KBWEB2 四大问题完整诊断报告

> 日期：2026-07-20 | 项目：kb2-web | 数据源：实际 DB 查询 + API 验证

---

## 核心架构背景（必读）

kb2-web 存在**两套存储系统分离但无桥接**的架构陷阱：

| 存储系统 | 位置 | 文档数 | doc_id 体系 | bank 命名 |
|----------|------|--------|------------|-----------|
| **v1 SQLite** | `/home/ubuntu/kb-web/data/kb.db` | **179** 篇 | UUID-A 体系 | `standards`, `industry_docs`, `咨询`, `business` |
| **pgvector (Hindsight)** | PostgreSQL `hindsight` 库 | **3266** 篇 | UUID-B 体系 | `kb_standard`, `kb_general` 等 11 种 |

**关键事实**：两边 doc_id 体系完全不同，**没有任何映射表**。v1 SQLite 的记录数是 179，pgvector 是 3266——不是同一个数据集，而是两套独立录入的数据。

---

## 问题 1：搜索"接线端子"出现"未知文档"

### 现状

搜索"接线端子"返回 12 个来源，其中 3 个 `doc` 字段显示为 **"未知文档"**，标题为空。三个 UUID：

| UUID | DB 证实实际内容 | tags 中隐藏的信息 |
|------|----------------|-------------------|
| `b7804e41-eae3-4a01-ad96-04d1aff52e9c` | GB 16806-2006 消防联动控制系统 | `doc_id:126df8b2...` / `title:中华人民共和国国家标准` |
| `286b3185-f745-43a1-8bee-ef0628d6fb35` | GY 5055-2008 扩声会议系统 | `doc_id:0bcd4089...` / `title:【会】GY 5055-2008...` |
| `024418ec-a424-472d-971e-ebe8b5dcf05e` | 不存在于 documents 表 | — |

其他 9 个来源有正确标题（如 `【机】GB 50303-2015 建筑电气工程施工质量验收规范`），因为这些来源的 `doc_id=None`，走了常规路径。

### 根因

```
前端搜索
  → POST /api/query
    → pgvector 召回 12 条来源（UUID-B 体系）
    → 组装 sources 时，拿 UUID 去查 v1 SQLite（179 篇 UUID-A 体系）
    → SQLite 找不到此 UUID → get_meta() 返回空 title
    → title 为空 → 前端显示 "未知文档"
```

**本质**：这 3 条是 Hindsight 的 **chunk 级记录**（tags 存了父文档 `doc_id` 和 `title`），但 kb2-web 查的是 v1 SQLite → UUID 体系不匹配。

### 影响范围

- 所有通过 **pgvector 新上传链路** 入库的文档都可能出现标题缺失（非全部，取决于来源信息组装路径）
- 不影响检索精度，只影响前端展示

### 修复方案

| 优先级 | 方案 | 操作 | 估时 |
|--------|------|------|------|
| **P0** | 来源逆向查询 title | 在 `query.py` 来源组装处，对 `doc` 为空但有 `doc_id` 的来源，加逆向查询：拿 doc_id 从 Hindsight 对应 tags 提取 title | **0.5d** |
| P1 | 统一元数据源 | 不再查 v1 SQLite，全部从 pgvector 取 | 1d |
| P2 | 数据迁移 | 建 doc_id 映射表，统一两套体系 | 2d |

---

## 问题 2：质量审计显示全部低质量（179 篇全 0 分）

### 现状

`GET /api/documents/audit` 返回：

```json
{
  "total_docs": 179,
  "avg_score": 0.0,
  "low_quality_count": 179,
  "documents": [
    { "title": "目 次", "score": 0, "issues": ["文本过短（<50字符）"] },
    { "title": "教育部办公厅关于印发...通知", "score": 0, "issues": ["文本过短（<50字符）"] },
    ...
  ]
}
```

**全部 179 篇文档 score=0，审计功能完全不可用。** 前端显示"全部是低质量内容"。

### 根因

审计端点执行链路：

```
GET /audit
  → repo.list_all() → 查 v1 SQLite（179 篇 UUID-A 体系文档）
  → 遍历每篇文档：
    → store.get_document_detail(doc_id=UUID-A, hs_bank="kb_standard")
      → 去 pgvector 搜索 UUID-A
      → **找不到！** pgvector 文档 ID 都是 UUID-B
      → 返回空列表 []
    → full_text = ""（空字符串）
    → assess_quality("")
      → 第 16 行：if not text or len(text.strip()) < 50:
      → 直接返回 {"score": 0, "issues": ["文本过短（<50字符）"]}
  → 179 篇全部 score=0
```

**两个致命问题**：

| 问题 | 详情 |
|------|------|
| ❌ **查错了数据源** | 审计遍历 v1 SQLite 的 179 篇旧文档，而不是 pgvector 的 3266 篇新文档 |
| ❌ **被审计的恰好是最老的一批** | pgvector 的 3266 篇文档（标准/小红书/行业文档）**完全未被审计覆盖** |

### 修复方案

| 方案 | 说明 | 估时 |
|------|------|------|
| **✅ 推荐：遍历 pgvector** | 审计端点改为直接遍历 pgvector 的 `vector_chunks` 表，按 `document_id` 分组，从 chunk 内容拼接全文后评估 | **1d** |
| ⚠️ 建映射表 | 建 doc_id 映射表，审计前先转换 UUID-A → UUID-B | 1.5d |
| ❌ 快速修复 | 仅改传参方式加日志（不解决根本问题） | 0.5d |

---

## 问题 3：分类重新整理

### 当前分类体系（三层互不关联）

```
OKF Domain (6 个)                     ← concept_gen.py
  standards / governance / methodology / operations / learning / ephemeral

Category (9 个)                       ← category_rules.py
  gov / security / it / cost / evaluation / regulation / standard / daily / news

Bank (11 个)                          ← retrieval.py / Hindsight
  all / project_docs / standards / industry_docs / tech_guides
  general / checklist / 咨询 / business / methodology / (kb_xhs)

前端展示 (13 个 with emoji)          ← banks.py + documents.py 硬编码
  💡想法 / 💼工作 / 📚学习 / 🏠生活 / 🚀项目 / 💭灵感
  📝会议 / 🔧技术 / 📊数据 / 📰资讯 / 🔒安全 / 🤖AI / 其他
```

### 存在的设计问题

| # | 问题 | 具体表现 |
|---|------|---------|
| 1 | **Category 粒度太粗** | 9 类覆盖不了用户实际业务分类 |
| 2 | **BANK_TO_CATEGORY 映射错位** | `咨询→news`（咨询→资讯）、`business→cost`（商业→造价） |
| 3 | **无 subcategory 字段** | 无法表达"验收测评"是"测评"的子类 |
| 4 | **双归属无法表达** | 商业密码测评既是"安全"又是"测评" |
| 5 | **前后端分类脱节** | 13 emoji 分类是两处硬编码，与 9 类 category 完全独立 |
| 6 | **无单点事实源** | DEFAULT_CATEGORIES 在 `banks.py` + `documents.py` 各一份 |

### 11 个新分类映射方案

| # | 用户分类 | 映射方式 | 子类 | 所属大类 | 说明 |
|---|---------|---------|------|---------|------|
| 1 | 信息化管理办法 | `subcategory=it` | → it | 信息化项目 | 现有 category `it` 的子类 |
| 2 | 等级报告/安全文档 | `subcategory=security` | → security | 信息化项目 | 现有 category `security` 的子类 |
| 3 | 验收测评文档(软硬件) | `subcategory=evaluation` | → evaluation | 信息化项目 | 现有 category `evaluation` 的子类 |
| 4 | 商业密码测评文档 | `subcategory=security` | → security | 信息化项目 | 双归属：主→security，副挂 evaluation |
| 5 | 商务文档 | **新增 category=business** | — | 信息化项目 | 原 `BANK_TO_CATEGORY` 错误映射需修复 |
| 6 | 模板文档 | `subcategory=it` | → it | 信息化项目 | 模板→methodology→it |
| 7 | 造价文档 | `subcategory=cost` | → cost | 信息化项目 | 现有 category `cost` 的子类 |
| 8 | 监理文档 | **新增 category=supervision** | — | 信息化项目 | 原无对应类 |
| 9 | 咨询文档 | **新增 category=consulting** | — | 信息化项目 | 修复原 `咨询→news` 错误 |
| 10 | 测评 | `subcategory=evaluation` | → evaluation | 信息化项目 | 现有 category `evaluation` 的子类 |
| 11 | 日常 | `subcategory=daily` | → daily | **个人资讯** | 现有 category `daily` 的子类 |

### 修复方案及文件清单

| 步骤 | 操作 | 文件 | 估时 |
|------|------|------|------|
| 1 | 新增 `subcategory` 字段 | `app/models/document.py` | 0.5h |
| 2 | 扩展 CATEGORIES 为 12-14 类 + 新增 `infer_subcategory()` | `app/services/category_rules.py` | **0.5d** |
| 3 | 修复 BANK_TO_CATEGORY 映射（咨询→consulting，business→business） | `app/services/category_rules.py` | 0.5h |
| 4 | 删除硬编码 DEFAULT_CATEGORIES，改为引用 category_rules | `app/api/banks.py`, `app/api/documents.py` | 0.5h |
| 5 | GET /categories 返回三层结构 | `app/api/admin.py` | 0.5d |
| 6 | 上传时支持 subcategory + infer 逻辑 | `app/api/upload.py` | **0.5d** |
| 7 | 新增回填脚本 | `scripts/backfill_subcategory.py` | 0.5d |
| 8 | 扩展 categoryFilter 支持 subcategory | `app/api/query_engine.py` | 0.5h |
| 9 | 前端分类树两级展示 | 前端 stores + views + UploadView | **1d** |
| | **合计** | | **~3.5d** |

---

## 问题 4：知识库分为"信息化项目"和"个人资讯"两大类

### 现状

11 个 bank 平铺，无顶层大类分组。

### 推荐架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                     知识库全部文档 (3266 篇)                        │
├─────────────────────────────┬───────────────────────────────────────┤
│  📁 信息化项目 (大类)       │  👤 个人资讯 (大类)                   │
├─────────────────────────────┼───────────────────────────────────────┤
│ subcategories:              │ subcategories:                        │
│  ├─ 信息化管理办法          │  ├─ 日常（默认选中）                 │
│  ├─ 等级报告/安全文档       │  ├─ 小红书知识（XHS 默认上传到此）   │
│  ├─ 验收测评文档(软硬件)    │  └─ 技术指导                        │
│  ├─ 商业密码测评文档        │                                       │
│  ├─ 商务文档                │  对应 bank:                          │
│  ├─ 模板文档                │  kb_xhs (27 篇)                     │
│  ├─ 造价文档                │  kb_general (514 篇)                │
│  ├─ 监理文档                │  kb_tech (12 篇)                    │
│  ├─ 咨询文档                │                                       │
│  └─ 测评                    │                                       │
│                              │                                       │
│  对应 bank:                  │                                       │
│  kb_standard (2037)         │                                       │
│  kb_project (41)            │                                       │
│  kb_industry (364)          │                                       │
│  kb_checklist (78)          │                                       │
│  kb (68)                    │                                       │
│  industry_docs (92)         │                                       │
│  business (5)               │                                       │
└─────────────────────────────┴───────────────────────────────────────┘
```

### XHS 默认上传策略

| 动作 | 处理 |
|------|------|
| 小红书内容入库 | 自动分配 `bank=kb_xhs`，`category=daily`，**`super_category=个人资讯`** |
| 前端上传表单 | 默认选中「个人资讯」大类，人工可切换为「信息化项目」 |
| 文档列表 | 默认显示「信息化项目」大类（用户首选视角），顶部大类选择器可切换 |

### 实施方案（不改 Hindsight bank 表）

| 步骤 | 操作 | 文件 | 估时 |
|------|------|------|------|
| 1 | 新增 `SUPER_CATEGORY_MAP`：bank_id → {信息化项目, 个人资讯} | `app/services/category_rules.py` | 0.5h |
| 2 | 前端分类选择器改为两级（大类→子类） | 前端 views/stores | **0.5d** |
| 3 | 文档列表按 super_category 分组 | 前端 DocumentsView | 0.5d |
| 4 | 上传表单默认"个人资讯" | 前端 UploadView | 0.5d |
| | **合计** | | **~2d** |

---

## 实施优先级总表

| 优先级 | 问题 | 要点 | 估时 | 影响等级 |
|--------|------|------|:----:|:--------:|
| **P0** | ① 未知文档 | 来源逆向查询 title（约 30 行代码） | **0.5d** | 🔴 前端展示 bug |
| **P0** | ② 审计全 0 分 | 审计遍历改为 pgvector 源 | **1d** | 🔴 功能完全不可用 |
| **P1** | ③ 分类整理 | subcategory 字段 + 12-14 类 + 修复映射 | **3.5d** | 🟡 用户业务分类 |
| **P1** | ④ 两大层级 | super_category_map + 前端两级分类 | **2d** | 🟡 用户体验 |
| **P2** | BANK_TO_CATEGORY 修复 | 修正 咨询→news, business→cost | **0.5h** | 🟢 分类准确性 |

**总估时：约 7d**（P0+P1 核心 = 6.5d，不含可选 P2）

---

## 文件修改汇总

| # | 文件 | 改动范围 | 问题关联 |
|---|------|---------|---------|
| 1 | `app/services/category_rules.py` | 扩展 CATEGORIES / 新增 infer_subcategory / 修复 BANK_TO_CATEGORY / 新增 SUPER_CATEGORY_MAP | ③④ |
| 2 | `app/models/document.py` | 新增 `subcategory` Column | ③ |
| 3 | `app/api/documents.py` | 审计端点改 pgvector 遍历 + 删除硬编码 DEFAULT_CATEGORIES | ②③ |
| 4 | `app/api/banks.py` | 删除硬编码 DEFAULT_CATEGORIES | ③ |
| 5 | `app/api/admin.py` | GET /categories 返回三层结构 | ③④ |
| 6 | `app/api/query.py` | 来源组装时加逆向 title 查询 | ① |
| 7 | `app/api/upload.py` | 上传时支持 subcategory | ③④ |
| 8 | `app/api/query_engine.py` | 扩展 categoryFilter 支持 subcategory | ③ |
| 9 | `scripts/backfill_subcategory.py` | 新增 -> 回填 subcategory | ③ |
| 10 | 前端 stores/services | 适配两级分类树 | ③④ |
| 11 | 前端 UploadView / QueryView / DocumentsView | 层级分类器 + 默认选中 | ③④ |
