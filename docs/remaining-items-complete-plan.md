# kb2-web 剩余项实施方案全集

> 合并日期: 2026-07-09
> 来源: 5 份 Codex 子代理规划方案
> 原始文件: `frontend/docs/responsive-plan-L01.md`, `frontend/docs/design-tokens.md`, `docs/m02_category_governance_plan.md`, `plans/L03_hollow_bank_cleanup_plan.md`, `docs/l05-ops-observability.md`

---

## 目录

1. [整体优先级推荐](#整体优先级推荐)
2. [M02 — Category 治理](#m02--category-治理)
3. [L01 — 响应式适配](#l01--响应式适配)
4. [L02 — 设计规范](#l02--设计规范)
5. [L03 — 空心 Bank 清理](#l03--空心-bank-清理)
6. [L05 — 运维观测](#l05--运维观测)

---

## 整体优先级推荐（2026-07-09 更新）

| 优先级 | 项 | 工时 | 依赖 | 快速见效 | 状态 |
|:------:|:--|:----:|:----:|:--------:|:----:|
| ✅ | **pgvector 迁移** | — | — | ✅ 已完成 | **已完成** |
| ✅ | **Hindsight 代码清理** | — | — | ✅ 已完成 | **已完成** |
| ✅ | **M02 Category 治理** | — | — | ✅ 已完成 | **已完成** |
| ✅ | **L03 空心 Bank 清理** | — | — | ✅ 已完成 | **已完成** |
| ✅ | **L06 前端视觉优化** | — | — | ✅ 已完成 | **已完成** |
| P1 | L01 响应式适配 | 8.5h | L02 部分 tokens | ✅ 移动端可用 | 待执行 |
| P1 | L05 运维观测 | 20h | 无 | ✅ 查问题不求人 | 待执行 |
| P2 | L02 设计规范 | 5.5天 | L01 先解决功能性问题 | ⚠️ 纯美化，无功能收益 | 待执行 |

---
## M02 — Category 治理

# M02 Category 治理 — 详细实施方案

## 1. 概述

**目标**：为 kb2-web 引入 9 类分类体系，覆盖文档上传、存储、检索全链路。

**9 类分类体系**：

| 分类 | 键值 | 类型 | 说明 |
|------|------|------|------|
| 政务 | `gov` | 业务型 | 政策文件、政府通知、政务管理类文档 |
| 安全 | `security` | 业务型 | 等保、密码安全、网络安全攻防、渗透测试 |
| 信息化 | `it` | 业务型 | 信息化建设、项目管理、技术指南 |
| 造价 | `cost` | 业务型 | 工程造价、取费标准、预算定额 |
| 测评 | `evaluation` | 业务型 | 验收测评、检测评估、质量评测 |
| 法规 | `regulation` | 业务型 | 法律法规、管理条例、行政规章 |
| 标准 | `standard` | 业务型 | GB/GA/T 等标准规范 |
| 日常 | `daily` | 隔离型 | 内部文档、非标内容，**默认对查询隔离** |
| 资讯 | `news` | 隔离型 | 行业新闻、资讯动态，**默认对查询隔离** |

**设计原则**：
- 日常/资讯类文档默认不可检索（仅通过显式指定 `category=daily` 或 `category=news` 可命中）
- 其余 7 类（政务/安全/信息化/造价/测评/法规/标准）正常参与检索
- 分类与现有 bank 体系**正交共存**：bank 控制 Hindsight 向量搜索域，category 控制文档级元数据过滤
- UI 上默认 `auto` → 后端自动推断；用户也可手动指定

---

## 2. 分类映射规则

### 2.1 映射策略（三优先）

```
优先级 1: 用户手动选择（上传表单的下拉选择，最高优先级）
优先级 2: Hindsight bank 映射（bank → category 默认映射表）
优先级 3: 文件名/标题关键词正则匹配
```

### 2.2 Bank → Category 默认映射

基于现有 bank 配置的语义映射：

```python
# backend/app/services/category_rules.py
BANK_TO_CATEGORY = {
    "standards":     "standard",    # 规范 → 标准
    "industry_docs": "it",          # 信息化行业文档 → 信息化
    "project_docs":  "it",          # 项目资料 → 信息化
    "templates":     "it",          # 方案模板 → 信息化
    "tech_guides":   "it",          # 技术指导书 → 信息化
    "checklist":     "evaluation",  # 检查标准 → 测评
    "business":      "cost",        # 商业分析 → 造价
    "xhs":           "news",        # 小红书技术 → 资讯
    "general":       None,          # 综合文件 → 需要关键词匹配兜底
    "methodology":   "it",          # 方法论 → 信息化
}
```

### 2.3 文件名/标题关键词正则规则

```python
# backend/app/services/category_rules.py
CATEGORY_REGEX_RULES = [
    # 标准 — 规范号模式（GB/GA/T/JJF/DB 等）
    (r'(GB/?T?\s*\d+|GA/?T?\s*\d+|JJF\s*\d+|DB\d{2}/?T?\s*\d+|EGAG|GDZW)', "standard"),
    (r'(规范|标准|规程|导则)\s*(GB|GA|DB|JJF)', "standard"),
    (r'^[\[【（(]?(GB|GA|DB|JJF)', "standard"),

    # 法规 — 法/条例/办法/规定
    (r'(法|条例|管理办法|实施办法|管理规定|实施细则)', "regulation"),
    (r'^中华人民共和国\w*法', "regulation"),

    # 政务 — 政府通知/批复/意见
    (r'(通知|批复|意见|函|报告)\s*(\(?\d{4}\)?)', "gov"),
    (r'^(关于|印发|转发).*(通知|意见|批复|方案)', "gov"),
    (r'(国务院|省政府|市政府|区政府|发改委|财政厅|财政|工信厅)', "gov"),

    # 安全 — 等保/密码/安全/渗透
    (r'(等保|等级保护|密码应用|密评|商用密码|网络安全|渗透测试|信息安全)', "security"),
    (r'^(GB/T\s*22239|GB/T\s*28448|GB/T\s*31167|GB/T\s*32916)', "standard"),  # 等保标准归入标准

    # 信息化 — 信息/数据/系统/项目/技术
    (r'(信息化|电子政务|数字化|数字政府|数据治理|项目管理|验收管理)', "it"),
    (r'(需求规格|概要设计|详细设计|技术方案|建设方案|运维方案)', "it"),
    (r'(软件开发|系统集成|数据中台|业务中台|技术架构)', "it"),

    # 造价 — 造价/取费/费用/预算/定额
    (r'(造价|取费|费用|费率|定额|预算|概算|决算)', "cost"),
    (r'(软件造价|工程造价|投资估算)', "cost"),

    # 测评 — 测评/检测/评估/验收
    (r'(测评|评测|检测|评估|验收|测试报告|评估报告)', "evaluation"),
    (r'(检查项|检查要求|核查力度)', "evaluation"),

    # 资讯 — 新闻/资讯/报道/动态
    (r'(新闻|资讯|报道|快讯|动态|周报|月报|趋势)', "news"),
    (r'(20\d{2}年\d{1,2}月)', "news"),

    # 日常 — 通用/综合/日常/笔记/草稿
    (r'(日常|笔记|草稿|memo|note|README)', "daily"),
    (r'(综合|通用)', None),  # 匹配但不自动分类，留给 bank 映射
]
```

### 2.4 自动推断函数

```python
# backend/app/services/category_rules.py

CATEGORIES = {
    "gov":        "政务",
    "security":   "安全",
    "it":         "信息化",
    "cost":       "造价",
    "evaluation": "测评",
    "regulation": "法规",
    "standard":   "标准",
    "daily":      "日常",
    "news":       "资讯",
}

# 隔离型分类（默认不参与查询检索）
ISOLATED_CATEGORIES = frozenset({"daily", "news"})


def infer_category(title: str = "", filename: str = "", bank: str = "") -> str:
    """
    自动推断文档分类。
    优先级: 关键词正则 > bank 映射 > 默认空（让用户手动选或保持 auto）
    """
    # Step 1: 关键词正则匹配（优先级高于 bank）
    source = title or filename
    for pattern, cat in CATEGORY_REGEX_RULES:
        if re.search(pattern, source, re.IGNORECASE):
            if cat is not None:
                return cat
            # cat=None 表示只匹配不分类，继续尝试其他规则
            break

    # Step 2: Bank 映射兜底
    if bank in BANK_TO_CATEGORY and BANK_TO_CATEGORY[bank] is not None:
        return BANK_TO_CATEGORY[bank]

    # Step 3: 默认空 — 表示 auto 未推断出，回退到 ""（不设分类）
    return ""
```

### 2.5 修改文件清单

| 文件 | 操作 | 工时 |
|------|------|------|
| **新增** `backend/app/services/category_rules.py` | 创建分类映射规则模块 | 0.5h |
| `backend/app/api/upload.py` | 导入并使用 `infer_category` | 0.25h |
| `backend/tests/unit/test_category_rules.py` | 新增映射规则单元测试 | 0.5h |

---

## 3. DB 迁移脚本

### 3.1 迁移策略

对现有 299 条 category 为空的文档，基于已有字段（title + filename + bank）自动推断分类。

**迁移脚本路径**：`backend/scripts/backfill_category.py`

### 3.2 脚本设计

```python
#!/usr/bin/env python3
"""
Backfill missing category fields for existing documents.
Based on title + filename + bank → infer_category() logic.
"""
import sys
import logging
from pathlib import Path

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.database import SessionLocal
from app.models.document import Document
from app.services.category_rules import infer_category, CATEGORIES

logger = logging.getLogger(__name__)

def backfill_categories(dry_run: bool = True):
    db = SessionLocal()
    try:
        docs = db.query(Document).filter(
            (Document.category.is_(None)) | (Document.category == "")
        ).all()
        
        stats = {k: 0 for k in CATEGORIES}
        stats["unmatched"] = 0
        stats["skipped"] = 0

        for doc in docs:
            cat = infer_category(
                title=doc.title or "",
                filename=doc.filename or "",
                bank=doc.bank or "",
            )
            if cat and cat in CATEGORIES:
                stats[cat] += 1
                if not dry_run:
                    doc.category = cat
            else:
                stats["unmatched"] += 1
                if not dry_run:
                    # 无法推断的分类设为空或兜底 "it"
                    doc.category = "it"

        if not dry_run:
            db.commit()
        
        # 打印分布
        total_assigned = sum(v for k, v in stats.items() if k != "unmatched" and k != "skipped")
        logger.info("=== Category Backfill %s ===", "DRY RUN" if dry_run else "EXECUTED")
        logger.info("Total empty docs: %d", len(docs))
        for cat_key, count in sorted(stats.items()):
            logger.info("  %s (%s): %d", cat_key, CATEGORIES.get(cat_key, ""), count)
        logger.info("Assigned: %d, Unmatched: %d", total_assigned, stats["unmatched"])
        
        return stats
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--exec", action="store_true", help="Execute (opposite of dry-run)")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    dry_run = not args.exec
    stats = backfill_categories(dry_run=dry_run)
    
    # Exit non-zero if unmatched > 0 (for CI)
    if stats["unmatched"] > 0:
        logger.warning("%d documents could not be matched automatically", stats["unmatched"])
```

### 3.3 使用方式

```bash
# Dry run 预览分布
cd /home/ubuntu/kb2-web
python backend/scripts/backfill_category.py --dry-run

# 确认后执行
python backend/scripts/backfill_category.py --exec
```

### 3.4 修改文件清单

| 文件 | 操作 | 工时 |
|------|------|------|
| **新增** `backend/scripts/backfill_category.py` | 创建迁移脚本 | 0.5h |
| `backend/app/services/category_rules.py` | 确认模块已就绪 | — |

---

## 4. 上传表单改造

### 4.1 前端 UploadView.vue 修改

**当前状态**（line 67-70）：分类为自由文本输入框
```vue
<div class="form-row">
  <label class="form-label">分类</label>
  <input v-model="category" type="text" placeholder="可选分类" />
</div>
```

**改造后**：分类改为下拉选择，默认 `auto`

```vue
<div class="form-row">
  <label class="form-label">分类</label>
  <select v-model="category">
    <option value="auto">自动推断（推荐）</option>
    <option value="gov">政务</option>
    <option value="security">安全</option>
    <option value="it">信息化</option>
    <option value="cost">造价</option>
    <option value="evaluation">测评</option>
    <option value="regulation">法规</option>
    <option value="standard">标准</option>
    <option value="daily">日常</option>
    <option value="news">资讯</option>
  </select>
</div>
```

### 4.2 前端逻辑变更

**新增数据结构**（在 script setup 中）：

```typescript
const CATEGORY_OPTIONS = [
  { key: 'auto', label: '自动推断（推荐）' },
  { key: 'gov', label: '政务' },
  { key: 'security', label: '安全' },
  { key: 'it', label: '信息化' },
  { key: 'cost', label: '造价' },
  { key: 'evaluation', label: '测评' },
  { key: 'regulation', label: '法规' },
  { key: 'standard', label: '标准' },
  { key: 'daily', label: '日常' },
  { key: 'news', label: '资讯' },
] as const
```

**表单重置函数**（line 593-599）：`category.value` 改为 `'auto'`

```typescript
function resetForm() {
  selectedFiles.value = []
  title.value = ''
  category.value = 'auto'  // 改为 auto
  uploadResult.value = null
  if (fileInput.value) fileInput.value.value = ''
}
```

### 4.3 后端上传接收逻辑变更

**`upload_document` endpoint**（`/home/ubuntu/kb2-web/backend/app/api/upload.py` line 117-127）：

```python
@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    category: str = Form("auto"),  # 改为 auto
    bank: str = Form("general"),
    ...
):
```

**auto 解析**（在 `_process_upload_task` 中，约 line 261）：

```python
# 当前代码
doc_category = category.strip()

# 改为
doc_category = category.strip()
if doc_category == "auto" or not doc_category:
    from app.services.category_rules import infer_category
    doc_category = infer_category(
        title=doc_title,
        filename=filename,
        bank=bank,
    )
```

### 4.4 修改文件清单

| 文件 | 操作 | 工时 |
|------|------|------|
| `frontend/src/views/UploadView.vue` | 分类输入框改为 dropdown, 默认 auto, reset 改为 auto | 1h |
| `backend/app/api/upload.py` | category 默认值改为 auto, 引入 infer_category | 0.5h |
| `backend/app/services/category_rules.py` | 确保 infer_category 可用 | — |

---

## 5. 查询过滤与隔离方案

### 5.1 设计决策

**隔离语义**：
- 日常（daily）、资讯（news）两类文档：**默认不参与任何查询检索**
- 仅当查询请求**显式指定** `category=daily` 或 `category=news` 时，才命中这些分类的文档
- 该隔离与 bank 选择正交：即使在 `bank=all` 下，日常/资讯类文档也不返回

**实现层次**：在 `_build_search_context` 中对检索结果做后过滤（post-filter）。

### 5.2 查询接口扩展

**`query()` 签名**（`/home/ubuntu/kb2-web/backend/app/api/query.py` line 627-631）：

```python
@router.post("")
async def query(
    q: str = Form(...),
    bank: str = Form("all"),
    category: str = Form(None),     # 新增：分类过滤（可选）
    history: str = Form(""),
    rerank: str = Form("false"),
    nocache: str = Form(""),
):
```

### 5.3 查询过滤实现

在 `_build_search_context` 的 Phase B（召回融合后）加装分类过滤层。

**修改位置**：`/home/ubuntu/kb2-web/backend/app/api/query.py` line 752（`all_results` 清洗前）

```python
# ── [Phase B-bis] Category 过滤：隔离日常/资讯类文档 ──
if bank != "all" or not category:
    # 默认过滤逻辑：排除隔离型分类（daily, news）
    filtered = []
    for r in all_results:
        doc_id = _extract_doc_id(r)
        if doc_id:
            cat = _get_doc_category(doc_id)
            if cat in ISOLATED_CATEGORIES:
                continue   # 默认排除日常/资讯
        filtered.append(r)
    all_results = filtered
elif category:
    # 显式指定分类：精确匹配
    filtered = []
    for r in all_results:
        doc_id = _extract_doc_id(r)
        if doc_id:
            cat = _get_doc_category(doc_id)
            if cat == category:
                filtered.append(r)
    all_results = filtered
```

**辅助函数**：

```python
# query.py 中新增
_CATEGORY_CACHE: dict[str, str] = {}

def _get_doc_category(doc_id: str) -> str:
    """查询文档分类（带内存缓存）"""
    if doc_id in _CATEGORY_CACHE:
        return _CATEGORY_CACHE[doc_id]
    
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.doc_id == doc_id).first()
        cat = doc.category if doc and doc.category else ""
        _CATEGORY_CACHE[doc_id] = cat
        return cat
    finally:
        db.close()
```

### 5.4 BM25 索引过滤

BM25 索引构建时（`build_bm25_index` in `retrieval.py`），应在 SQL 查询中加入分类过滤：

```python
# retrieval.py 中 build_bm25_index 的 SQL 查询
# 当前（约 line 488）：
docs = db.execute(text("""
    SELECT d.doc_id, d.title, pc.parent_text, pc.parent_idx
    FROM parent_chunks pc
    JOIN documents d ON d.doc_id = pc.doc_id
    WHERE d.searchable = 1 AND d.status = 'active'
    AND d.bank = :bank
"""), {"bank": bank}).fetchall()

# 改为：排除隔离分类
if bank != "all":
    docs = db.execute(text("""
        SELECT d.doc_id, d.title, pc.parent_text, pc.parent_idx
        FROM parent_chunks pc
        JOIN documents d ON d.doc_id = pc.doc_id
        WHERE d.searchable = 1 AND d.status = 'active'
        AND d.bank = :bank
        AND (d.category IS NULL OR d.category = '' OR d.category NOT IN ('daily', 'news'))
    """), {"bank": bank}).fetchall()
```

### 5.5 标准号精确匹配过滤

`boost_exact_standards`（`standard_boost.py`）中使用的 SQL 也需加过滤：

```python
# 约 line 42-50 in standard_boost.py
# 增加 AND (d.category IS NULL OR d.category = '' OR d.category NOT IN ('daily', 'news'))
```

### 5.6 管理员视角

管理后台（`/api/admin` 和 `/api/documents` 端点）**不做隔离**，管理员应能查看所有文档包括日常/资讯。

### 5.7 修改文件清单

| 文件 | 操作 | 工时 |
|------|------|------|
| `backend/app/api/query.py` | 新增 category 参数、_get_doc_category 函数、Phase B-bis 过滤 | 1.5h |
| `backend/app/services/retrieval.py` | build_bm25_index SQL 加分类过滤 | 0.5h |
| `backend/app/services/standard_boost.py` | SQL 加分类过滤 | 0.25h |
| `backend/app/services/category_rules.py` | 确保 ISOLATED_CATEGORIES 导出 | — |

---

## 6. 验证方案

### 6.1 迁移后分布验证

```bash
# 迁移前快照
sqlite3 /home/ubuntu/kb-web/data/kb.db \
  "SELECT category, COUNT(*) FROM documents GROUP BY category ORDER BY category;"

# 执行迁移
cd /home/ubuntu/kb2-web
python backend/scripts/backfill_category.py --exec

# 迁移后验证
sqlite3 /home/ubuntu/kb-web/data/kb.db \
  "SELECT category, COUNT(*) FROM documents GROUP BY category ORDER BY category;"

# 验证零空值
sqlite3 /home/ubuntu/kb-web/data/kb.db \
  "SELECT COUNT(*) FROM documents WHERE category IS NULL OR category = '';"
```

**预期分布示例**：

| category | count | 说明 |
|----------|-------|------|
| standard | ~174 | 大部分 standards bank 文档 |
| it | ~95 | industry_docs + project_docs + templates + tech_guides + general |
| security | ~10 | 标题含安全关键词的 |
| regulation | ~8 | 法规类文档 |
| cost | ~21 | business bank（造价相关） |
| evaluation | ~1 | checklist bank |
| news | ~16 | xhs bank |
| daily | ~2 | methodology / 未匹配文档 |

### 6.2 查询隔离测试脚本

**测试脚本路径**：`backend/scripts/test_category_isolation.py`

```python
#!/usr/bin/env python3
"""
Test category query isolation.
"""
import sys, json, logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.database import SessionLocal
from app.models.document import Document
from app.services.category_rules import ISOLATED_CATEGORIES

logger = logging.getLogger(__name__)

def test_isolation():
    """验证日常/资讯类文档正确隔离"""
    db = SessionLocal()
    try:
        # 1. 检查隔离类文档确实存在
        isolated = db.query(Document).filter(
            Document.category.in_(ISOLATED_CATEGORIES)
        ).all()
        logger.info("Isolated docs: %d (daily=%d, news=%d)",
            len(isolated),
            sum(1 for d in isolated if d.category == "daily"),
            sum(1 for d in isolated if d.category == "news"),
        )
        assert len(isolated) > 0, "应该存在隔离类文档"

        # 2. 检查非隔离查询不应返回隔离文档ID
        # 模拟默认查询的 bank 过滤条件
        visible = db.query(Document).filter(
            (Document.category.is_(None)) | (Document.category == "")
            | (Document.category.notin_(ISOLATED_CATEGORIES))
        ).all()
        visible_ids = {d.doc_id for d in visible}
        isolated_ids = {d.doc_id for d in isolated}
        overlap = visible_ids & isolated_ids
        assert len(overlap) == 0, f"隔离文档不应出现在默认查询中: {overlap}"

        logger.info("✓ Isolation test passed: %d visible, %d isolated, 0 overlap",
            len(visible), len(isolated))
        return True
    finally:
        db.close()


def test_category_distribution():
    """验证分类分布合理"""
    db = SessionLocal()
    try:
        results = db.query(
            Document.category,
            db.func.count(Document.doc_id)
        ).group_by(Document.category).all()
        
        total = sum(count for _, count in results)
        logger.info("=== Category Distribution (total=%d) ===", total)
        for cat, count in sorted(results):
            pct = count / total * 100
            logger.info("  %-15s %4d (%5.1f%%)", cat or "(空)", count, pct)

        # 零空值检查
        empty_count = db.query(Document).filter(
            (Document.category.is_(None)) | (Document.category == "")
        ).count()
        assert empty_count == 0, f"仍有 {empty_count} 个文档分类为空"
        logger.info("✓ Zero empty categories: %d", empty_count)
        return True
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ok1 = test_isolation()
    ok2 = test_category_distribution()
    if ok1 and ok2:
        logger.info("ALL TESTS PASSED")
    else:
        logger.error("SOME TESTS FAILED")
        sys.exit(1)
```

### 6.3 API 级别集成测试

**测试位置**：`backend/tests/integration/test_category_query.py`

测试用例：
1. **默认查询不应返回日常/资讯文档**
   - POST `/api/query` 不带 category 参数
   - 验证返回的 sources 中没有 category=daily 或 category=news 的文档

2. **显式指定 category 应返回对应分类文档**
   - POST `/api/query` 带 `category=daily`
   - 验证返回的 sources 中 category=daily 的文档占比合理

3. **上传文档后 category 正确存储**
   - POST `/api/upload` 指定 `category=cost`
   - 查询 DB 验证文档的 category 字段为 "cost"

4. **auto 推断正确**
   - 上传标题为 "GB/T 22239-2019" 的文档
   - 验证 category 自动推断为 "standard"

5. **管理员 API 不受隔离限制**
   - GET `/api/admin/documents` 应返回所有分类的文档

### 6.4 修改文件清单

| 文件 | 操作 | 工时 |
|------|------|------|
| **新增** `backend/scripts/test_category_isolation.py` | 创建验证脚本 | 0.5h |
| **新增** `backend/tests/integration/test_category_query.py` | 创建集成测试 | 1h |
| `backend/tests/unit/test_category_rules.py` | 单元测试（映射规则） | 0.5h |

---

## 7. 完整文件修改汇总

| # | 文件 | 操作 | 修改内容 | 工时 |
|---|------|------|----------|------|
| 1 | **新增** `backend/app/services/category_rules.py` | CREATE | 分类映射规则、CATEGORIES、ISOLATED_CATEGORIES、infer_category() | 0.5h |
| 2 | `backend/app/api/upload.py` | MODIFY | category 默认 auto、引入 infer_category、auto 解析 | 0.5h |
| 3 | `backend/app/api/query.py` | MODIFY | 新增 category 参数、_get_doc_category()、Phase B-bis 过滤 | 1.5h |
| 4 | `backend/app/services/retrieval.py` | MODIFY | build_bm25_index SQL 加分类过滤 | 0.5h |
| 5 | `backend/app/services/standard_boost.py` | MODIFY | SQL 加分类过滤 | 0.25h |
| 6 | `frontend/src/views/UploadView.vue` | MODIFY | 分类 dropdown、default auto、reset 逻辑 | 1h |
| 7 | **新增** `backend/scripts/backfill_category.py` | CREATE | 迁移脚本（dry-run + exec） | 0.5h |
| 8 | **新增** `backend/scripts/test_category_isolation.py` | CREATE | 隔离验证脚本 | 0.5h |
| 9 | **新增** `backend/tests/unit/test_category_rules.py` | CREATE | 映射规则单元测试 | 0.5h |
| 10 | **新增** `backend/tests/integration/test_category_query.py` | CREATE | 查询隔离集成测试 | 1h |

**总工时估计：7.25 小时**

---

## 8. 执行顺序

```
Phase 1 — 规则层（0.5h）
  └─ 创建 category_rules.py + 单元测试

Phase 2 — 后端迁移（0.75h）
  └─ 创建 backfill_category.py
  └─ 执行 dry-run → 验证 → 执行

Phase 3 — 上传改造（1.5h）
  └─ 前端 UploadView.vue dropdown 改造
  └─ 后端 upload.py auto 解析

Phase 4 — 查询隔离（2.25h）
  └─ query.py category 参数 + 过滤逻辑
  └─ retrieval.py BM25 过滤
  └─ standard_boost.py 过滤

Phase 5 — 验证（2h）
  └─ 隔离验证脚本
  └─ 集成测试
  └─ 手动验证（API 测试）
```

---

## 9. 风险与注意事项

1. **Bank 与 Category 的语义重叠**：standards bank → standard category 高度重叠，无需额外处理
2. **空 category 兜底**：auto 推断失败的文档不应报错，应回退到空字符串（不设分类），不影响检索
3. **Hindsight tags 同步**：上传时已有 `cat:<value>` tag 逻辑（upload.py line 334），新分类将自动写入 tag
4. **缓存失效**：修改 category 后需考虑缓存（bm25_index 缓存、query cache）的失效策略
5. **存量数据**：9 条已有 category 的文档（8 规范 + 1 行业文档）需重新映射到新体系
6. **前端无关性**：隔离过滤在后端实现，前端只改上传表单，不影响查询界面

---
# L01 — 响应式适配

# L01 响应式适配实施方案

> 项目: kb2-web/frontend  
> 日期: 2026-07-09  
> 当前状态: 仅 `main.css` 有一个 `@media (max-width: 768px)` 断点，隐藏 Sidebar 并清零 margin-left  
> 目标: 覆盖 **mobile (< 640px)** / **tablet (640–1024px)** / **desktop (> 1024px)** 三个断点

---

## 目录

1. [断点方案](#1-断点方案)
2. [Sidebar 折叠方案](#2-sidebar-折叠方案)
3. [逐组件评估与修改](#3-逐组件评估与修改)
4. [逐视图评估与修改](#4-逐视图评估与修改)
5. [移动端表格展示方案](#5-移动端表格展示方案)
6. [文件修改清单](#6-文件修改清单)
7. [工时估计](#7-工时估计)

---

## 1. 断点方案

### 1.1 断点定义（CSS 自定义属性 + 媒体查询）

```css
/* main.css 新增 */
/* 断点 tokens（供 JS 和 CSS 引用） */
:root {
  --bp-mobile:  640px;
  --bp-tablet:  1024px;
}

/* 三个断点层级 */
@media (max-width: 639px)  { /* mobile */ }
@media (min-width: 640px) and (max-width: 1023px) { /* tablet */ }
@media (min-width: 1024px) { /* desktop — 已经是当前默认行为 */ }
```

### 1.2 设计原则

| 断点 | 视口宽度 | 行为 |
|------|---------|------|
| **Desktop** | ≥ 1024px | **当前行为不变**：Sidebar 常开, Header nav 行内, 表格 grid 列展示 |
| **Tablet** | 640–1023px | Sidebar 可折叠（按钮切换, 覆盖层）, Header nav 可滚动, 表格列自适应 |
| **Mobile** | < 640px | Sidebar 全屏覆盖层, Header 汉堡菜单, 表格横向滚动 / 卡片化, 表单单列 |

### 1.3 当前 main.css 已有内容

```css
/* 仅有的响应式代码 — 过于简陋 */
@media (max-width: 768px) {
  :root { --sidebar-w: 0px; }
  .app-main { margin-left: 0; padding: 1rem; }
}
```

需要替换为更精确的三段式断点。

---

## 2. Sidebar 折叠方案

### 2.1 问题

- 当前 `< 768px` 时 Sidebar `display: none`，用户无法切换知识库
- 无切换按钮，Sidebar 内容完全不可达
- Sidebar 固定定位 `top: var(--header-h)`，与 Header 存在层叠关系

### 2.2 方案：Slide-over 抽屉（覆盖层）

#### 2.2.1 响应式行为

| 断点 | Sidebar 状态 | 触发方式 |
|------|-------------|---------|
| Desktop (≥ 1024px) | 常开, `position: fixed`, `width: var(--sidebar-w)` | 无切换 |
| Tablet (640–1023px) | 默认关闭, 打开时覆盖在主内容之上 | Header 中汉堡按钮切换 |
| Mobile (< 640px) | 默认关闭, 打开时全屏覆盖层 | 同上 |

#### 2.2.2 具体实现

**App.vue** 新增响应式 Sidebar 状态：

```ts
// 新增响应式状态
const sidebarOpen = ref(false)

// 监听路由变化，切换路由时自动关闭 Sidebar（移动端/平板）
watch(() => route.path, () => {
  if (window.innerWidth < 1024) sidebarOpen.value = false
})
```

**AppSidebar.vue** 改造：

```vue
<template>
  <!-- Tablet/Mobile: 遮罩层 -->
  <Transition name="sidebar-fade">
    <div
      v-if="isBelowTablet && open"
      class="sidebar-overlay"
      @click="$emit('close')"
    />
  </Transition>

  <!-- Sidebar 本体 -->
  <aside
    class="app-sidebar"
    :class="{
      'sidebar-open': open,
      'sidebar-collapsed': !open && isBelowTablet,
    }"
  >
    <!-- 内容不变 -->
  </aside>
</template>
```

新增 props/emits: `open: boolean`, `@close`

CSS 关键变更：

```css
/* Desktop 模式 — 不变 */
.app-sidebar {
  position: fixed;
  top: var(--header-h);
  left: 0;
  bottom: 0;
  width: var(--sidebar-w);
  z-index: 90;
}

/* Tablet/Mobile 关闭时移出视口 */
@media (max-width: 1023px) {
  .app-sidebar {
    transform: translateX(-100%);
    transition: transform 0.2s ease;
    z-index: 110; /* 高于 header */
  }
  .app-sidebar.sidebar-open {
    transform: translateX(0);
  }
}

/* 遮罩层 */
.sidebar-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.35);
  z-index: 105;
}

/* 过渡动画 */
.sidebar-fade-enter-active,
.sidebar-fade-leave-active { transition: opacity 0.2s; }
.sidebar-fade-enter-from,
.sidebar-fade-leave-to { opacity: 0; }
```

#### 2.2.3 Header 切换按钮

**AppHeader.vue** 新增：

```vue
<template>
  <header class="app-header">
    <!-- 汉堡菜单按钮 — 仅 tablet/mobile 可见 -->
    <button
      v-if="!isDesktop"
      class="header-menu-btn"
      @click="$emit('toggle-sidebar')"
      aria-label="切换侧边栏"
    >
      <span class="hamburger" :class="{ active: sidebarOpen }">
        <span class="hamburger-line" />
        <span class="hamburger-line" />
        <span class="hamburger-line" />
      </span>
    </button>

    <div class="header-brand">
      <span class="brand-mark">KB2</span>
      <span class="brand-sub">知识库</span>
    </div>
    <nav class="header-nav"><!-- 现有 nav links --></nav>
  </header>
</template>
```

新增 emits: `toggle-sidebar`

---

## 3. 逐组件评估与修改

### 3.1 AppHeader.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| 9 个 nav links 在 < 768px 时溢出换行 | 所有移动端页面 | 添加 `overflow-x: auto` + `flex-shrink: 0`；Brand 区 `min-width` 改为响应式 |
| 无汉堡菜单按钮 | Tablet/Mobile | 新增 toggle 按钮（见 2.2.3） |
| Brand 区 `min-width: calc(var(--sidebar-w) - 1.5rem)` | < 640px 时 sidebar-w=0 导致负值 | 改用固定值或断点内重写 |

```css
/* 修改 */
.header-brand {
  min-width: auto; /* 移除固定 min-width */
}

.header-nav {
  display: flex;
  align-items: center;
  gap: 0;
  overflow-x: auto;
  white-space: nowrap;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}

.header-nav::-webkit-scrollbar { display: none; }

.nav-link {
  flex-shrink: 0;
  padding: 0 0.6rem;
  font-size: 0.8rem;
}

@media (max-width: 639px) {
  .header-nav { gap: 0; }
  .nav-link { padding: 0 0.5rem; font-size: 0.75rem; }
}
```

### 3.2 AppSidebar.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| `< 768px` 时 `display: none`，完全不可用 | 所有移动端页面 | 替换为 slide-over 抽屉（见 §2） |
| 无响应式过渡动画 | Tablet/Mobile | 添加 CSS transition |
| 需要遮罩层 | Tablet/Mobile | 新增 `.sidebar-overlay` |

修改范围：
- 新增 `open` prop, `close` emit
- 新增 responsive CSS 块（取代现有 `display: none`）
- 新增 Transition 组件包裹遮罩层
- 新增 slot/class 控制

### 3.3 ConfirmDialog.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| 已用 `width: 90%; max-width: 400px` | — | 基本 OK |
| 按钮 `flex-end` 在小屏上可能溢出 | < 400px | 可选: 按钮改用 `flex-direction: column` 或 `flex-wrap: wrap` |

**修改量极小**，可选操作：

```css
@media (max-width: 400px) {
  .confirm-actions { flex-direction: column-reverse; }
  .confirm-actions button { width: 100%; }
}
```

### 3.4 LoadingSpinner.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| 无 | — | **无需修改** |

已有 `inline` 模式，`flex-direction` 自动适应，字体由 clamp 控制。

### 3.5 ResultCard.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| source-item `max-width: 400px` | < 640px 时仍为 400px 导致溢出 | 改为响应式 |
| source-text `word-break: break-all` | 中文换行点不当 | 改用 `word-break: break-word` + `overflow-wrap: break-word` |
| source-doc `max-width: 200px` | 移动端过宽 | 改为百分比 |
| suggestion-panel 内部布局 | 基本 OK | 仅微调 padding |

```css
@media (max-width: 639px) {
  .source-item { max-width: 100%; }
  .source-doc,
  .source-doc-link { max-width: 140px; }
  .source-text { word-break: break-word; overflow-wrap: break-word; }
  .suggestion-panel { padding: 0.5rem; }
}
```

### 3.6 Toast.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| `max-width: 360px`, `right: 1rem` | < 400px 时可能右侧溢出 | 改为 `left: 1rem; right: 1rem; max-width: none` |

```css
@media (max-width: 400px) {
  .toast {
    left: 0.5rem;
    right: 0.5rem;
    max-width: none;
    top: calc(var(--header-h) + 0.5rem);
  }
}
```

---

## 4. 逐视图评估与修改

### 4.1 QueryView.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| `query-options` flex 行包含多选框 + select + 按钮 | < 640px 时换行混乱 | 改用 grid 2列或 flex-wrap + 缩小 gap |
| 搜索按钮和联网搜索按钮并排 | < 400px 时按钮文字重叠 | 按钮 flex-grow+缩小 gap |
| 查询历史 item 三栏（文本+时间+删除） | < 480px 时时间列被挤压 | 移动端隐藏时间戳 |

```css
@media (max-width: 639px) {
  .query-options {
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  .option-label { font-size: 0.75rem; }
  .query-input-row button {
    flex: 1;
    font-size: 0.8rem;
    padding: 0.5rem 0.5rem;
  }
  .history-time { display: none; }
}
```

### 4.2 DocumentsView.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| 表格使用 grid 6列固定宽度 `1fr 100px 60px 50px 100px 130px` | 所有 < 800px 视口完全破碎 | 参见 §5 表格方案 |
| 工具栏三栏（搜索 + select + 按钮） | < 500px 时溢出 | 移动端垂直堆叠 |

```css
@media (max-width: 639px) {
  .toolbar { flex-direction: column; }
  .search-input, .bank-filter { width: 100%; }
}
```

### 4.3 AdminView.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| 审计表格 `1fr 100px 60px 1fr` | < 700px 时溢出 | 参见 §5 |
| 成本表格 `1fr 80px 100px 100px 100px` | < 800px 时溢出 | 参见 §5 |
| `stats-grid` flex 布局 | 基本 OK（自动换行） | 仅调整 gap |
| `health-row` `max-width: 400px` | < 480px 时 OK | 可选改为 100% |

```css
@media (max-width: 639px) {
  .stats-grid, .audit-summary {
    flex-wrap: wrap;
    gap: 0.75rem;
  }
  .stat-value { font-size: 1.2rem; }  /* 缩小数值字号 */
  .health-row { max-width: 100%; }
}
```

### 4.4 UploadView.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| drop-zone `padding: 2.5rem` | < 480px 时浪费空间 | 缩小 padding |
| 上传结果行 `justify-content: space-between` | < 500px 时 label/value 换行错位 | 改为列布局 |
| 批量结果 `batch-summary` flex 行 | 基本 OK | 仅微调 |

```css
@media (max-width: 639px) {
  .drop-zone { padding: 1.5rem 1rem; }
  .drop-text { font-size: 0.8rem; }
  .result-row { flex-direction: column; gap: 0.2rem; }
  .batch-result-item { flex-direction: column; align-items: flex-start; gap: 0.2rem; }
}
```

### 4.5 DocumentsView.vue, AdminView.vue, SynonymsView.vue — 额外视图

| 视图 | 问题 | 修改 |
|------|------|------|
| **BanksView.vue** | 已用 `auto-fill, minmax(260px, 1fr)` — **无需修改** | — |
| **SynonymsView.vue** | 表格 `1fr 1fr 120px 130px` | 参见 §5 |
| **DocumentDetail.vue** | `info-grid` 2列在 < 500px 太挤 | 改为单列 |
| **WikiView.vue** | 树形结构已响应式 | 仅微调 padding |
| **LoginView.vue** | `padding: 2.5rem` 在小屏过大 | 缩小 padding |

**DocumentDetail.vue 修改**：

```css
@media (max-width: 480px) {
  .info-grid { grid-template-columns: 1fr; }
}
```

**LoginView.vue 修改**：

```css
@media (max-width: 400px) {
  .login-card { padding: 1.5rem; }
}
```

---

## 5. 移动端表格展示方案

### 5.1 涉及的表格

| 视图 | CSS Grid 列定义 | 问题 |
|------|----------------|------|
| DocumentsView | `1fr 100px 60px 50px 100px 130px` | 6列，320px 视口下每列仅 ~50px |
| AdminView (audit) | `1fr 100px 60px 1fr` | 4列，列宽不足 |
| AdminView (costs) | `1fr 80px 100px 100px 100px` | 5列，严重不足 |
| SynonymsView | `1fr 1fr 120px 130px` | 4列，操作列溢出 |

### 5.2 方案 A：横向滚动表格（推荐，改动最小）

保持 grid 布局不变，在 < 640px 时外层容器添加横向滚动。

```css
@media (max-width: 639px) {
  .doc-table, .syn-table, .audit-table, .costs-table {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
  .table-header, .table-row {
    /* 保持原有 grid-template-columns，但父容器可滚动 */
    min-width: 600px; /* 保证所有列可见 */
  }
}
```

**优点**：改动最小，仅需在每个 table 容器加 overflow-x + min-width  
**缺点**：用户需要横向滚动，体验略差但功能完整

### 5.3 方案 B：卡片式列表（推荐，体验最佳）

在 < 480px 时表格行转为卡片式布局。

**DocumentsView 示例**：

```css
@media (max-width: 480px) {
  .table-header { display: none; }  /* 隐藏表头 */
  
  .doc-table .table-row {
    display: flex;
    flex-direction: column;
    padding: 0.75rem;
    gap: 0.3rem;
    border-bottom: 1px solid var(--border);
  }
  
  .table-row .col-title { font-size: 0.9rem; font-weight: 600; }
  .table-row .col-bank { order: -1; }
  .table-row .col-chunks::before { content: "分块: "; color: var(--fg-muted); }
  .table-row .col-date::before { content: "日期: "; color: var(--fg-muted); }
  .table-row .col-actions { margin-top: 0.3rem; }
}
```

**SynonymsView 示例**：

```css
@media (max-width: 480px) {
  .syn-table .table-header { display: none; }
  .syn-table .table-row {
    display: flex;
    flex-direction: column;
    padding: 0.75rem;
    gap: 0.3rem;
  }
  .table-row .col-term { font-size: 0.9rem; font-weight: 600; }
  .table-row .col-category { order: -1; }
  .table-row .col-actions { margin-top: 0.3rem; }
}
```

**AdminView audit/costs 示例**：

```css
@media (max-width: 480px) {
  .audit-table .table-header { display: none; }
  .audit-table .table-row {
    display: flex;
    flex-direction: column;
    padding: 0.75rem;
    gap: 0.3rem;
  }
  .table-row .col-doc { font-size: 0.9rem; font-weight: 600; }
  .table-row .col-issues { margin-top: 0.2rem; }
}
```

### 5.4 方案选择

| 断点 | 方案 |
|------|------|
| 640–1023px (Tablet) | **方案 A** — 横向滚动。保留列布局但容器可滚动 |
| < 480px (Mobile) | **方案 B** — 卡片式。隐藏表头，行内用 `::before` 伪元素展示标签 |

实际实现时，两个方案通过两个媒体查询并存。

---

## 6. 文件修改清单

### 6.1 修改列表

| 序号 | 文件 | 修改范围 | 预期变更行数 |
|------|------|---------|-------------|
| 1 | `src/assets/main.css` | 替换现有 `@media (max-width: 768px)` 为三段式断点；新增全局 app-layout 响应式规则 | ~30 行 |
| 2 | `src/App.vue` | 新增 `sidebarOpen` 响应式状态、路由变化自动关闭的逻辑；向 AppHeader 传递 `toggle-sidebar` 事件 | ~10 行 |
| 3 | `src/components/AppHeader.vue` | 新增汉堡菜单按钮（tablet/mobile 可见）；nav 添加横向滚动；brand min-width 修正 | ~25 行 |
| 4 | `src/components/AppSidebar.vue` | 替换 `display: none` 为 slide-over + transition + 遮罩层；新增 `open` prop / `close` emit | ~30 行 |
| 5 | `src/components/ConfirmDialog.vue` | 按钮区小屏垂直堆叠 | ~5 行 |
| 6 | `src/components/Toast.vue` | 小屏下左右撑满 | ~5 行 |
| 7 | `src/components/ResultCard.vue` | 移动端 source-item / source-doc / suggestion-panel 响应式调整 | ~15 行 |
| 8 | `src/views/QueryView.vue` | query-options flex-wrap；按钮移动端缩放；history-time 小屏隐藏 | ~15 行 |
| 9 | `src/views/DocumentsView.vue` | toolbar 垂直堆叠；表格响应式（方案 A+B 两段 media query） | ~30 行 |
| 10 | `src/views/AdminView.vue` | stats-grid 间距调整；audit/costs 表格响应式 | ~25 行 |
| 11 | `src/views/UploadView.vue` | drop-zone 小屏 padding；result-row 列布局；batch-item 自适应 | ~15 行 |
| 12 | `src/views/SynonymsView.vue` | 表格响应式（方案 A+B）；与 DocumentsView 相同模式 | ~20 行 |
| 13 | `src/views/DocumentDetail.vue` | info-grid 小屏单列 | ~5 行 |
| 14 | `src/views/LoginView.vue` | card padding 小屏缩小 | ~3 行 |

### 6.2 无需修改的文件

| 文件 | 原因 |
|------|------|
| `LoadingSpinner.vue` | 已自适应 |
| `BanksView.vue` | CSS Grid `auto-fill` 已天然响应式 |
| `WikiView.vue` | 树形结构已全宽自适应 |

### 6.3 修改预览（总行数）

| 类别 | 文件数 | 总新增/修改行数 |
|------|--------|---------------|
| 基础样式 (main.css) | 1 | ~30 |
| 布局/壳 (App.vue) | 1 | ~10 |
| 组件 (5 个) | 5 | ~80 |
| 视图 (6 个) | 6 | ~113 |
| **合计** | **13** | **~233** |

---

## 7. 工时估计

| 阶段 | 工时 | 说明 |
|------|------|------|
| **基础样式与断点** | 0.5h | main.css 断点定义 + app-layout 全局适配 |
| **App.vue 改造** | 0.5h | 新增 sidebar 状态管理 + 路由监听 |
| **AppHeader 改造** | 1.0h | 汉堡按钮 + nav 滚动 + brand 修正 |
| **AppSidebar 抽屉改造** | 1.5h | slide-over 动画 + 遮罩层 + transition |
| **表格响应式（4 个视图）** | 2.0h | DocumentsView + SynonymsView + AdminView(audit/costs) |
| **其他视图微调** | 1.5h | QueryView + UploadView + DocumentDetail + LoginView |
| **组件微调** | 0.5h | ConfirmDialog + Toast + ResultCard |
| **测试与调试** | 1.0h | 3 个断点逐页验证 + 交互检查 |
| **总计** | **8.5h** | — |

### 7.1 依赖关系

```
main.css (基础断点)
  ├── App.vue (sidebar 状态)
  │   ├── AppHeader.vue (汉堡按钮 + nav 滚动)
  │   └── AppSidebar.vue (抽屉 + 遮罩)
  ├── ConfirmDialog.vue, Toast.vue, ResultCard.vue (组件微调 — 可并行)
  ├── QueryView.vue, UploadView.vue, DocumentDetail.vue, LoginView.vue (视图微调 — 可并行)
  └── DocumentsView.vue, SynonymsView.vue, AdminView.vue (表格响应式 — 可并行)
```

### 7.2 并行路径

- **路径 A**（核心骨架）：main.css → App.vue → AppHeader + AppSidebar（~3.5h, 阻塞后续）
- **路径 B**（可并行于 A 之后）：组件微调（0.5h）
- **路径 C**（可并行于 A 之后）：视图微调（2.5h）
- **路径 D**（可并行于 A 之后）：表格响应式（2.0h）
- **路径 E**（收尾）：全流程测试（1.0h）

**最短工期（2 人并行）**：**~5h**  
**单人顺序工期**：**~8.5h**

---
# L02 — 设计规范

# L02 设计规范实施方案

> 项目: kb2-web 前端  
> 当前版本: CSS Variables + Vue SFC scoped styles  
> 无 UI 框架  
> 日期: 2026-07-09

---

## 目录

1. [现有 CSS Tokens 审核](#1-现有-css-tokens-审核)
2. [建议新增 Tokens](#2-建议新增-tokens)
3. [组件规范清单](#3-组件规范清单)
4. [迁移步骤](#4-迁移步骤)
5. [工时估计](#5-工时估计)
6. [交付物清单](#6-交付物清单)

---

## 1. 现有 CSS Tokens 审核

### 1.1 现状总览 (`frontend/src/assets/main.css` — 18 个 tokens)

| 类别 | 现有 Token | 值 | 审核结论 |
|---|---|---|---|
| **背景色** | `--bg` | `hsl(220,20%,98%)` | ✅ 正确 |
| | `--bg-alt` | `hsl(220,18%,95%)` | ✅ 正确 |
| **前景色** | `--fg` | `hsl(220,25%,12%)` | ✅ 正确 |
| | `--fg-muted` | `hsl(220,15%,45%)` | ✅ 正确 |
| **强调色** | `--accent` | `hsl(210,70%,48%)` | ✅ 正确 |
| | `--accent-hover` | `hsl(210,70%,40%)` | ✅ 正确 |
| | `--accent-light` | `hsl(210,60%,95%)` | ✅ 正确 |
| **边框** | `--border` | `hsl(220,15%,88%)` | ✅ 正确 |
| **语义色** | `--danger` | `hsl(0,65%,52%)` | ✅ 正确 |
| | `--danger-hover` | `hsl(0,65%,44%)` | ✅ 正确 |
| | `--success` | `hsl(145,55%,42%)` | ✅ 正确 |
| | `--warning` | `hsl(38,85%,50%)` | ✅ 正确 |
| **圆角** | `--radius` | `0px` | ⚠️ 值为 0，但多处组件使用硬编码非零圆角 → 实际设计意图并非直角 |
| **布局** | `--sidebar-w` | `220px` | ✅ 正确 |
| | `--header-h` | `52px` | ✅ 正确 |
| **字体** | `--font-sans` | `'Inter', ...` | ✅ 正确 |
| | `--font-mono` | `'JetBrains Mono', ...` | ✅ 正确 |

### 1.2 缺失大类（8 个类别缺失）

| 缺失类别 | 严重程度 | 证据 |
|---|---|---|
| **字号尺度** | 🔴 高 | 所有组件使用硬编码 `font-size: 0.7rem ~ 1.5rem`，无层级统一 |
| **字重** | 🟡 中 | 硬编码 `font-weight: 500/600/700` 散落各处 |
| **行高** | 🟡 中 | 硬编码 `line-height: 1.5/1.6` |
| **间距尺度** | 🔴 高 | `padding: 0.5rem/1rem/1.5rem/2rem` 散落各处，无复用 |
| **阴影** | 🔴 高 | 完全无阴影 token — 对话框、卡片需要 |
| **层级 (z-index)** | 🔴 高 | 硬编码 `100, 90, 200, 300, 1000` 散落在 5+ 组件中 |
| **过渡动画** | 🟡 中 | 硬编码 `0.15s, 0.1s, 0.2s` |
| **断点** | 🟡 中 | `768px` 唯一断点，硬编码在 main.css 和 AppSidebar |

### 1.3 已使用但未定义的 Tokens（运行时错误风险）

| 被引用的 Token | 使用位置 | 影响 |
|---|---|---|
| `--card` | `LoginView.vue:72` | 页面背景无效果 |
| `--accent-fg` | `LoginView.vue:133` | 按钮文字颜色无效果 |
| `--fg2` | `LoginView.vue:86` | 副标题文字颜色无效果 |
| `--bg-elevated` | `UploadView.vue:648` | 存在硬编码 fallback |
| `--bg-hover` | `UploadView.vue:658` | 存在硬编码 fallback |

### 1.4 硬编码颜色实例

```css
/* AppSidebar.vue:78 — hover 背景 */
background: hsl(220, 15%, 92%);

/* UploadView.vue:648-658 — 次级按钮 */
background: var(--bg-elevated, #f3f3f3);
color: var(--fg, #333);
border: 1px solid var(--border, #d0d0d0);
&:hover { background: var(--bg-hover, #e8e8e8); }

/* ResultCard.vue:651-665 — 标签徽章 */
.fee-badge  { background: #fff3e0; color: #e65100; border-color: #ffe0b2; }
.kw-badge   { background: #e3f2fd; color: #1565c0; border-color: #bbdefb; }
mark.kw-highlight { background: #fff176; color: #333; }

/* LoginView.vue:123-127 — 错误提示 */
.login-error { color: #c0392b; border-color: #e8c4c0; background: #fdf2f1; }

/* ConfirmDialog.vue:32 — 遮罩层 */
background: rgba(0, 0, 0, 0.4);

/* SynonymsView.vue:258 — 遮罩层 */
background: rgba(0, 0, 0, 0.25);
```

### 1.5 硬编码圆角实例（既然 `--radius: 0px`）

| 位置 | 值 | 与 `--radius` 矛盾 |
|---|---|---|
| `WikiView.vue:128, DocumentDetail.vue:265` | `6px` | 是 |
| `AdminView.vue:437` | `6px` | 是 |
| `UploadView.vue:652` | `6px` | 是 |
| `DocumentDetail.vue:302` | `8px` | 是 |
| `DocumentDetail.vue:333` | `4px` | 是 |
| `UploadView.vue:715` | `4px` | 是 |
| `ResultCard.vue:514, 646` | `3px` | 是 |
| `ResultCard.vue:530` (suggestion chip) | `1rem` | 是 |

### 1.6 重复样式（提取到 main.css 会显著瘦身）

| 重复块 | 出现次数 | 影响行数 |
|---|---|---|
| `.page-title` (完全一致) | 8 次 | ~40 行 |
| `.toolbar` (高度相似) | 4 次 | ~20 行 |
| `.table-header` + `.table-row` (高度相似) | 3 次 | ~60 行 |
| `.section-title` | 3 次 | ~12 行 |
| `.form-row` + `.form-label` + `.form-actions` | 3 次 | ~30 行 |
| `.btn-sm` | 3 次 | ~12 行 |
| `.empty-state` | 3 次 | ~12 行 |
| `.error-msg` | 2 次 | ~8 行 |
| `.badge` (部分覆盖) | 2 次 | ~12 行 |

---

## 2. 建议新增 Tokens

### 2.1 新增原则

1. **不破坏现有 token 名称** — 只追加、不改名
2. **按功能模块分组** — 清晰的命名空间
3. **值从现有设计推导** — 取现有硬编码值的中位数/众数，保持一致
4. **渐进式采用** — 新增 token 定义后，组件逐步迁移而非一次性重写

### 2.2 新增 Tokens 完整列表

#### 2.2.1 Surface / 背景层 (新增 3 个)

```css
/* ── Surface / 背景层 ── */
--surface:          hsl(0, 0%, 100%);       /* 卡片/弹窗背景，替代 white */
--surface-hover:    hsl(220, 15%, 92%);     /* hover 状态背景，替换硬编码 */
--surface-elevated: hsl(0, 0%, 95%);         /* 次级按钮背景，替换硬编码 */
```

**来源**: `white` 出现最多作为卡片背景；`hsl(220,15%,92%)` 出现在 `AppSidebar:hover`；`#f3f3f3` 在 `UploadView`

#### 2.2.2 语义色补全 (新增 2 个)

```css
/* ── 语义色补全 ── */
--danger-bg:   hsl(0, 80%, 96%);            /* 错误背景，替换硬编码 #fdf2f1 */
--warning-bg:  hsl(38, 80%, 96%);           /* 警告背景 */
--success-bg:  hsl(145, 50%, 95%);          /* 成功背景 */
--info-bg:     hsl(210, 60%, 96%);          /* 信息背景 — Toast 缺 info 类型 */
```

#### 2.2.3 文字色补全 (新增 2 个)

```css
/* ── 文字色层级 ── */
--fg-secondary: hsl(220, 15%, 35%);         /* 次要文字（比 muted 重一点） */
--fg-on-accent: hsl(0, 0%, 100%);           /* 强调色上的文字，替代 white */
--fg-on-danger: hsl(0, 0%, 100%);           /* 危险色上的文字 */
```

**来源**: `color: white` 用于 primary/danger 按钮；`--accent-fg` 和 `--fg2` 在 LoginView 未定义

#### 2.2.4 字号尺度 (新增 8 个)

```css
/* ── 字号尺度 ── */
--text-xs:    0.7rem;    /* 徽章、统计标签、辅助信息 */
--text-sm:    0.75rem;   /* 日期、计数、次要元数据 */
--text-base:  0.825rem;  /* 正文（现有组件使用最密集的尺寸） */
--text-md:    0.875rem;  /* 按钮、输入框 */
--text-lg:    0.95rem;   /* 卡片标题 */
--text-xl:    1.1rem;    /* 页面标题 base */
--text-2xl:   1.4rem;    /* 页面标题 large (配合 clamp) */
--text-3xl:   1.5rem;    /* 登录页标题 */
```

#### 2.2.5 字重 (新增 3 个)

```css
/* ── 字重 ── */
--weight-medium: 500;
--weight-semibold: 600;
--weight-bold: 700;
```

#### 2.2.6 行高 (新增 2 个)

```css
/* ── 行高 ── */
--leading-tight:   1.4;
--leading-normal:  1.6;
```

#### 2.2.7 间距尺度 (新增 6 个)

```css
/* ── 间距尺度 (4/8/12/16/24/32) ── */
--space-1:   0.25rem;  /* 4px 基准 */
--space-2:   0.5rem;   /* 8px — 组件内间距 */
--space-3:   0.75rem;  /* 12px */
--space-4:   1rem;     /* 16px — 卡片内边距 */
--space-5:   1.5rem;   /* 24px — 页面边距 */
--space-6:   2rem;     /* 32px — 大间距 */
```

#### 2.2.8 圆角 (新增 3 个 — 修正当前 contradictions)

```css
/* ── 圆角 (调整 radius 为合理值) ── */
--radius-sm:  3px;     /* 徽章、小标签 */
--radius:     6px;     /* 默认圆角（重要：从 0px→6px 对齐实际使用） */
--radius-lg:  8px;     /* 大卡片、代码块 */
--radius-full: 9999px; /* 圆形胶囊 */
```

**⚠️ 注意**: 这是 breaking change — `--radius` 从 `0px` 改为 `6px`。需与团队确认。也可保留 `--radius: 0px` 并新增 `--radius-md: 6px` 让组件自行选择。**建议方案**：保留 `--radius: 0px` 作为兼容别名，新增 `--radius-sm/md/lg/full` 供新组件和迁移使用。

#### 2.2.9 阴影 (新增 3 个)

```css
/* ── 阴影 ── */
--shadow-sm:  0 1px 2px rgba(0,0,0,0.06);
--shadow:     0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
--shadow-lg:  0 4px 12px rgba(0,0,0,0.1);
```

#### 2.2.10 Z-index 层级 (新增 5 个)

```css
/* ── Z-index 层级 ── */
--z-sidebar:    90;
--z-header:     100;
--z-toast:      200;
--z-dialog:     300;
--z-modal:      1000;
```

#### 2.2.11 过渡动画 (新增 2 个)

```css
/* ── 过渡动画 ── */
--transition-fast: 0.1s ease;
--transition:      0.15s ease;
--transition-slow: 0.2s ease;
```

#### 2.2.12 响应式断点 (新增 1 个)

```css
/* ── 响应式断点 (仅供 @media 使用，无 var()) ── */
/* 已在 main.css 底部使用 */
```

### 2.3 完整 `:root` 区块（增量版本）

参见 [tokens/_index.css](./tokens/_index.css) — 或直接追加到 `main.css` `:root` 块内。

### 2.4 Token 命名规范

| 规范 | 示例 |
|---|---|
| 颜色语义: `--{用途}` | `--bg`, `--fg`, `--accent` |
| 状态变体: `--{base}-{state}` | `--accent-hover`, `--danger-bg` |
| 字号: `--text-{size}` | `--text-xs`, `--text-lg` |
| 间距: `--space-{n}` | `--space-1` ~ `--space-6` |
| 圆角: `--radius-{variant}` | `--radius-sm`, `--radius-lg` |
| 阴影: `--shadow-{variant}` | `--shadow-sm`, `--shadow-lg` |
| 层级: `--z-{layer}` | `--z-header`, `--z-dialog` |

---

## 3. 组件规范清单

### 3.1 组件与 View 一览

| # | 文件 | 类型 | 行数 | scoped CSS | 不规范项 |
|---|---|---|---|---|---|
| 1 | `AppHeader.vue` | 组件 | 56 | ✅ | — |
| 2 | `AppSidebar.vue` | 组件 | 107 | ✅ | 1 处硬编码色值 |
| 3 | `LoadingSpinner.vue` | 组件 | 63 | ✅ | — |
| 4 | `Toast.vue` | 组件 | 103 | ✅ | — |
| 5 | `ResultCard.vue` | 组件 | 670 | ✅ | 5+ 硬编码色值/圆角 |
| 6 | `ConfirmDialog.vue` | 组件 | 57 | ✅ | 硬编码遮罩色值 |
| 7 | `QueryView.vue` | View | 410 | ✅ | — |
| 8 | `BanksView.vue` | View | 207 | ✅ | 重复结构样式 |
| 9 | `DocumentsView.vue` | View | 242 | ✅ | 重复结构样式 |
| 10 | `DocumentDetail.vue` | View | 345 | ✅ | 硬编码圆角/色值 |
| 11 | `LoginView.vue` | View | 148 | ✅ | **使用未定义 tokens** |
| 12 | `UploadView.vue` | View | 865 | ✅ | 硬编码色值/fallback |
| 13 | `SynonymsView.vue` | View | 300 | ✅ | 重复结构样式 |
| 14 | `AdminView.vue` | View | 473 | ✅ | 重复结构样式 |
| 15 | `WikiView.vue` | View | 241 | ✅ | 硬编码圆角 |

### 3.2 按迁移优先级分组的组件规范

#### P0 — 紧急修复（未定义 token 引用，运行时可能无效果）

| 文件 | 行号 | 当前代码 | 替换为 |
|---|---|---|---|
| `LoginView.vue` | 72 | `background: var(--card)` | `background: var(--surface)` |
| `LoginView.vue` | 86 | `color: var(--fg2)` | `color: var(--fg-muted)` |
| `LoginView.vue` | 133 | `color: var(--accent-fg)` | `color: var(--fg-on-accent)` |

#### P1 — 硬编码色值 → token

| 文件 | 行号 | 当前值 | 替换为 |
|---|---|---|---|
| `AppSidebar.vue` | 78 | `hsl(220,15%,92%)` | `var(--surface-hover)` |
| `ResultCard.vue` | 651-659 | `#fff3e0/#e65100/#ffe0b2` / `#e3f2fd/#1565c0/#bbdefb` | CSS 变量引导类别色或保持 badge 硬编码（功能色，可接受） |
| `ResultCard.vue` | 661 | `#fff176/#333` | token 化或保持（功能高亮色，可接受） |
| `LoginView.vue` | 123-127 | `#c0392b/#e8c4c0/#fdf2f1` | `var(--danger)` / `var(--danger)` / `var(--danger-bg)` |
| `ConfirmDialog.vue` | 32 | `rgba(0,0,0,0.4)` | `var(--z-modal)` 无关，改用 named 或保持 |
| `SynonymsView.vue` | 258 | `rgba(0,0,0,0.25)` | 同上，统一为 `var(--overlay)` (建议新增) |
| `UploadView.vue` | 648-658 | 含 fallback 的色值 | `var(--surface-elevated)` / `var(--fg)` / `var(--border)` |

**新增** `--overlay: rgba(0,0,0,0.35)` — 统一对话框遮罩颜色

#### P2 — 硬编码圆角 → token

| 文件 | 位置 | 当前值 | 替换为 |
|---|---|---|---|
| `WikiView.vue` | 128 | `border-radius: 6px` | `var(--radius-md)` |
| `DocumentDetail.vue` | 193, 265, 302, 333 | `6px / 8px / 8px / 4px` | `var(--radius-md/lg/lg/sm)` |
| `UploadView.vue` | 652, 715 | `6px / 4px` | `var(--radius-md) / var(--radius-sm)` |
| `ResultCard.vue` | 514, 530, 646 | `3px / 1rem / 3px` | `var(--radius-sm) / var(--radius-full) / var(--radius-sm)` |
| `AdminView.vue` | 437 | `6px` | `var(--radius-md)` |

#### P3 — 重复样式提取为全局 utility

| 目标类 | 来源文件 | 提取到 | 预计瘦身 |
|---|---|---|---|
| `.page-title` | 8 个 View 文件 | `main.css` 公共区 | -40 行 scoped |
| `.toolbar` | 4 个 View | `main.css` | -20 行 |
| `.table-header` + `.table-row` | 3 个 View | `main.css` | -60 行 |
| `.section-title` | 3 个 View | `main.css` | -12 行 |
| `.form-row` / `.form-label` / `.form-actions` | 3 个 View | `main.css` | -30 行 |
| `.btn-sm` | 3 个 View | `main.css` | -12 行 |
| `.empty-state` | 3 个 View | `main.css` | -12 行 |
| `.error-msg` / `.error-state` | 2-3 个 View | `main.css` | -10 行 |
| `.badge` (二次定义覆盖) | 2 个文件 | `main.css` 增强 | -8 行 |

#### P4 — 字号/间距/字重 token 化

**所有 View 和组件**中的以下样式替换：

```css
/* Before */
font-size: 0.7rem;    →  var(--text-xs)
font-size: 0.75rem;   →  var(--text-sm)
font-size: 0.825rem;  →  var(--text-base)
font-size: 0.875rem;  →  var(--text-md)
font-size: 0.95rem;   →  var(--text-lg)
font-size: 1.1rem;    →  var(--text-xl)
font-weight: 600;     →  var(--weight-semibold)
font-weight: 700;     →  var(--weight-bold)
padding: 0.5rem 1rem; →  padding: var(--space-2) var(--space-4)
padding: 1rem;        →  padding: var(--space-4)
padding: 1.5rem;      →  padding: var(--space-5)
gap: 0.5rem;          →  gap: var(--space-2)
gap: 0.75rem;         →  gap: var(--space-3)
gap: 1rem;            →  gap: var(--space-4)
```

**注意**: P4 是纯纯的机械替换，建议最后做或用全局搜索替换。

---

## 4. 迁移步骤

### Phase 0 — 准备 (0.5 天)

1. 创建 docs/ 目录结构
2. 编写 `design-tokens.md`（本文档）
3. 编写 `tokens/_index.css` — 新 token 定义文件（供引用和审查）

### Phase 1 — 修复 Bug (0.5 天)

1. **修复 `LoginView.vue` 三个未定义 token** → 替换为实际存在的变量
2. **新增 `--overlay`** 并统一 ConfirmDialog + SynonymsView 遮罩色
3. **更新 `main.css`**: 追加 token 增量块（不修改现有 token）

### Phase 2 — 核心样式提取 (1 天)

1. 在 `main.css` 新增公共 utility 样式区
2. 从各 View 迁移 `.page-title` 到公共区（删除 scoped 中的副本）
3. 迁移 `.toolbar`、`.section-title`、`.empty-state`、`.error-msg`
4. 统一 `.table-header` + `.table-row` 布局模式
5. 统一 `.form-row` + `.form-label` + `.form-actions` 布局模式
6. 统一 `.btn-sm` 到公共区

### Phase 3 — 语义化 token 迁移 (1.5 天)

1. **颜色替换**: AppSidebar, UploadView, LoginView, DocumentDetail
2. **圆角替换**: WikiView, DocumentDetail, UploadView, ResultCard, AdminView
3. **阴影引入**: Card 组件加 `var(--shadow-sm)`，Dialog 加 `var(--shadow-lg)`
4. **z-index 替换**: 所有组件中的硬编码 z-index → `var(--z-*)`

### Phase 4 — 字号/间距 token 化 (1 天)

1. 机械替换 font-size → var(--text-*)
2. 机械替换 font-weight → var(--weight-*)
3. 机械替换 padding/gap → var(--space-*)
4. 机械替换 line-height → var(--leading-*)

### Phase 5 — ResultCard 专项 (0.5 天)

1. 功能标签色 token 化或确认保留硬编码
2. 圆角统一
3. `.badge` scoped 覆盖移除，使用全局增强版

### Phase 6 — 验证与回归 (0.5 天)

1. 全局无未定义 CSS 变量引用
2. 全局无硬编码色值（功能色除外）
3. 所有 View scoped CSS 至少减少 30% 体积
4. 视觉对比：前后截图对比

---

## 5. 工时估计

| Phase | 工作内容 | 预估工时 | 依赖 |
|---|---|---|---|
| P0 | 准备文档 | 0.5 天 | — |
| P1 | 修复 Bug | 0.5 天 | P0 |
| P2 | 核心样式提取 | 1 天 | P1 |
| P3 | 语义化 token 迁移 | 1.5 天 | P2 |
| P4 | 字号/间距 token 化 | 1 天 | P3 |
| P5 | ResultCard 专项 | 0.5 天 | P3 |
| P6 | 验证与回归 | 0.5 天 | P4-P5 |
| **合计** | | **5.5 天** | |

### 按角色分配

| 角色 | 工作内容 | 工时 |
|---|---|---|
| 前端工程师 | P1-P6 代码修改 | 4.5 天 |
| 设计师/审校 | P0 规范评审 + P6 视觉回归 | 1 天 |
| **总计** | | **5.5 天** |

---

## 6. 交付物清单

| # | 交付物 | 文件路径 | 状态 |
|---|---|---|---|
| 1 | 设计规范文档（本文） | `frontend/docs/design-tokens.md` | ✅ 完成 |
| 2 | 新增 Tokens CSS 定义 | `frontend/src/assets/tokens/_index.css` | 📝 待创建 |
| 3 | 更新后的 `main.css` | `frontend/src/assets/main.css` | 📝 Phase 1-2 |
| 4 | 组件 scoped CSS 修改 | 14 个 .vue 文件 | 📝 Phase 1-5 |
| 5 | 验证报告 | `frontend/docs/variation-report.md` | 📝 Phase 6 |

---

## 附录 A: Tokens 新增 CSS 代码块

```css
/* === 新增 Tokens 块 — 追加到 :root 末尾 === */

/* Surface / 背景层 */
--surface:          hsl(0, 0%, 100%);
--surface-hover:    hsl(220, 15%, 92%);
--surface-elevated: hsl(0, 0%, 95%);
--overlay:          rgba(0, 0, 0, 0.35);

/* 文字色层级 */
--fg-secondary: hsl(220, 15%, 35%);
--fg-on-accent: hsl(0, 0%, 100%);
--fg-on-danger: hsl(0, 0%, 100%);

/* 语义色背景 */
--danger-bg:  hsl(0, 80%, 96%);
--warning-bg: hsl(38, 80%, 96%);
--success-bg: hsl(145, 50%, 95%);
--info-bg:    hsl(210, 60%, 96%);

/* 字号 */
--text-xs:    0.7rem;
--text-sm:    0.75rem;
--text-base:  0.825rem;
--text-md:    0.875rem;
--text-lg:    0.95rem;
--text-xl:    1.1rem;
--text-2xl:   1.4rem;
--text-3xl:   1.5rem;

/* 字重 */
--weight-medium:   500;
--weight-semibold: 600;
--weight-bold:     700;

/* 行高 */
--leading-tight:  1.4;
--leading-normal: 1.6;

/* 间距 (4/8/12/16/24/32) */
--space-1: 0.25rem;
--space-2: 0.5rem;
--space-3: 0.75rem;
--space-4: 1rem;
--space-5: 1.5rem;
--space-6: 2rem;

/* 圆角 */
--radius-sm:   3px;
--radius-md:   6px;
--radius-lg:   8px;
--radius-full: 9999px;

/* 阴影 */
--shadow-sm: 0 1px 2px rgba(0,0,0,0.06);
--shadow-md: 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
--shadow-lg: 0 4px 12px rgba(0,0,0,0.1);

/* Z-index */
--z-sidebar: 90;
--z-header:  100;
--z-toast:   200;
--z-dialog:  300;
--z-modal:   1000;

/* 过渡 */
--transition-fast: 0.1s ease;
--transition:      0.15s ease;
--transition-slow: 0.2s ease;
```

---

## 附录 B: 现有 token → 新增 token 映射

| 现有 Token | 建议保留？ | 备注 |
|---|---|---|
| `--bg` | ✅ 保留 | 全局背景 |
| `--bg-alt` | ✅ 保留 | 次要背景 |
| `--fg` | ✅ 保留 | 主文字 |
| `--fg-muted` | ✅ 保留 | 弱化文字 |
| `--accent` | ✅ 保留 | 强调色 |
| `--accent-hover` | ✅ 保留 | 强调 hover |
| `--accent-light` | ✅ 保留 | 强调背景 |
| `--border` | ✅ 保留 | 边框 |
| `--danger` / `--danger-hover` | ✅ 保留 | 危险色 |
| `--success` | ✅ 保留 | 成功色 |
| `--warning` | ✅ 保留 | 警告色 |
| `--radius` | ⚠️ 保留但建议弃用 | 新增 `--radius-sm/md/lg/full` |
| `--sidebar-w` | ✅ 保留 | 布局 |
| `--header-h` | ✅ 保留 | 布局 |
| `--font-sans` / `--font-mono` | ✅ 保留 | 字体 |

---

*文档版本: v1.0  
*最后更新: 2026-07-09  
*作者: Hermes Agent (L02 实施方案自动生成)*

---
# L03 — 空心 Bank 清理

# L03 空心 Bank 清理 — 详细实施方案

> 调查日期：2026-07-09
> 数据源：Hindsight API（http://localhost:8888）+ 代码分析（retrieval.py / banks.py / documents.py / upload.py / query.py）+ kb-web DB

---

## 一、12 个 Bank 状态总表

### 1.1 Hindsight 注册状态

| # | bank_id | fact_count | 最后写入时间(UTC) | 创建时间(UTC) | 状态判定 |
|---|---------|-----------|-------------------|--------------|---------|
| 1 | `kb_general` | **6,710** | 2026-07-08 15:32 | 2026-06-05 | ✅ 活跃 — 综合文件、商业分析、方法论共用 |
| 2 | `kb_standard` | **10,346** | 2026-07-01 06:36 | 2026-06-05 | ✅ 活跃 — 规范标准主库 |
| 3 | `kb_checklist` | **4,434** | 2026-06-19 17:33 | 2026-06-07 | ✅ 活跃 — 检查标准 |
| 4 | `kb` | **2,838** | 2026-07-02 15:44 | 2026-06-07 | ⚠️ 活跃但冗余 — 旧聚合库，被 `kb_general/standard/industry` 替代 |
| 5 | `kb_industry` | **1,812** | 2026-07-01 11:47 | 2026-06-05 | ✅ 活跃 — 信息化行业文档 |
| 6 | `kb_project` | **699** | 2026-06-24 14:43 | 2026-06-05 | ✅ 活跃 — 项目资料 |
| 7 | `kb_tech` | **407** | 2026-06-24 15:24 | 2026-06-06 | ✅ 活跃 — 技术指导书 |
| 8 | `general` | **50** | 2026-06-02 11:13 | 2026-06-01 | 🔴 空心 — 被 `kb_general` 替代，无文档引用 |
| 9 | `kb_xhs` | **1** | 2026-07-08 09:55 | 2026-06-24 | ✅ 活跃（新库，数据少但持续写入中） |
| 10 | `kb_standards` | **0** | 2026-06-30 23:09 | 2026-06-30 | 🔴 空心重复 — `kb_standard` 的重复空库 |
| 11 | `industry_docs` | **0** | 2026-06-30 04:46 | 2026-06-30 | 🔴 空心重复 — `kb_industry` 的重复空库 |
| 12 | `default` | **0** | 2026-06-30 03:24 | 2026-06-30 | 🔴 空心孤儿 — 未在任何配置中被引用 |

### 1.2 前端 Bank 配置 → Hindsight 映射（`retrieval.py:33-45`）

| 前端 Key | 显示名 | hindsight bank | 状态 |
|----------|-------|---------------|------|
| `all` | 全部 | None（聚合查询所有 active banks） | ✅ |
| `standards` | 规范 | `kb_standard` | ✅ |
| `project_docs` | 项目资料 | `kb_project` | ✅ |
| `industry_docs` | 信息化行业文档 | `kb_industry` | ✅ |
| `general` | 综合文件 | `kb_general` | ✅ |
| `checklist` | 检查标准 | `kb_checklist` | ✅ |
| `xhs` | 小红书技术 | `kb_xhs` | ✅ |
| `business` | 商业分析 | `kb_general` | ✅（共享） |
| `methodology` | 方法论 | `kb_general` | ✅（共享） |
| `tech_guides` | 技术指导书 | `kb_tech` | ✅ |
| `templates` | 方案模板 | ❌ `kb_template` **不存在于 Hindsight** | ⚠️ 悬空引用 |

### 1.3 DB 文档→hs_bank 分布（kb-web DB）

| hs_bank | 文档数 | 说明 |
|---------|--------|------|
| `kb_standard` | 174 | 规范标准文档 |
| `kb_general` | 95 | 综合 + 商业 + 方法论文档 |
| `kb_xhs` | 16 | 小红书技术文档 |
| `kb_industry` | 15 | 行业文档 |
| `kb_project` | 6 | 项目资料 |
| `kb_tech` | 2 | 技术指导书 |
| `kb_checklist` | 1 | 检查标准 |

确认：**没有任何 DB 文档引用以下 hs_bank**：`kb`, `kb_standards`, `industry_docs`, `default`, `general`

---

## 二、空心 / 冗余 Bank 详细分析

### 🔴 A 组 — 立即删除（0 facts，无文档引用，无配置引用）

| bank | 原因 | 说明 |
|------|------|------|
| `kb_standards` | 空心重复 | `kb_standard`（10,346 facts）的重复创建，0 facts |
| `industry_docs` | 空心重复 | `kb_industry`（1,812 facts）的重复创建，0 facts |
| `default` | 空心孤儿 | Hindsight 自动创建的默认 bank，未被 kb2-web 任何组件引用 |

### 🔴 B 组 — 建议迁移/清理（有少量 facts 但被替代）

| bank | fact_count | 问题 | 处理建议 |
|------|-----------|------|---------|
| `kb` | 2,838 | 旧聚合库。`recall()` 中 `bank="kb"` 等同于 `bank="all"`(查所有 active banks)。文档 `_verify_searchable` 硬编码 `v_bank="kb"` | ⚠️ 迁移到 `kb_general` 后再删除 |
| `general` | 50 | Hindsight 自创建的老 bank，被 `kb_general`（6,710 facts）替代，无文档引用 | 确认无引用后可直接删除 |
| _(missing)_ `kb_template` | N/A | 配置中引用但 Hindsight 中没有该 bank | 需创建空 bank 或移除配置引用 |

### ✅ C 组 — 保留（活跃使用中）

`kb_general`, `kb_standard`, `kb_industry`, `kb_project`, `kb_tech`, `kb_checklist`, `kb_xhs`

---

## 三、代码依赖分析

### 3.1 `bank="kb"` 遗留引用

**文件：** `backend/app/services/retrieval.py:260`
```python
async def recall(query, limit=5, bank="kb", ...):
    # bank="kb" → 查询所有 active hindsight banks
```

`bank="kb"` 被用作默认参数，但实际行为等同于 `bank="all"`（走第 280 行的聚合查询分支）。删除 `kb` Hindsight bank 后不会影响 recall 功能，但需要更新：

- `retrieval.py:260` — 默认参数从 `"kb"` 改为 `"all"`
- `retrieval.py:280` — 条件 `bank in ("all", "kb")` 改为 `bank in ("all",)`

**文件：** `backend/app/api/documents.py:71`
```python
async def _verify_searchable(v_doc_id, v_title, v_original_len, v_bank="kb"):
```
上传后的可搜索验证使用 `v_bank="kb"` 作为默认 bank。需要改为 `v_bank="kb_general"`。

**文件：** `backend/app/api/documents.py:459` 中的 rag-eval recall：
```python
recalled = await recall(tc["q"], limit=10, bank="kb")
```
需要改为 `bank="all"`。

### 3.2 `general` bank 被 `kb_general` 取代

- 前端 `business` 和 `methodology` 均使用 `kb_general`（共享）
- DB 中无文档使用 `general` 作为 hs_bank
- 删除安全

### 3.3 `kb_template` 缺失

**文件：** `backend/app/services/retrieval.py:38`
```python
"templates": {"name": "方案模板", "hindsight": "kb_template", ...}
```
配置存在，Hindsight 中无此 bank。上传文档时若选择「方案模板」bank，上传到空的 `kb_template` 会因 Hindsight 404 失败。需要创建该 bank 或暂时注释该配置。

---

## 四、清理方案

### 方案 A — 立即删除 3 个空心 bank（无风险）

```
DELETE /v1/default/banks/kb_standards    # 已测试：成功返回 {"success":true}
DELETE /v1/default/banks/industry_docs
DELETE /v1/default/banks/default
```

**验证方法：**
```bash
curl http://localhost:8888/v1/default/banks
# 确认返回中不再包含上述 3 个 bank
```

### 方案 B1 — 迁移 `kb` 数据并删除（中风险，需分步执行）

`kb` 有 2,838 facts，需要先确认这些 facts 是否已经被其他 bank 覆盖。

**步骤：**
1. 从 `kb` 中抽样 recall 验证是否已被 `kb_general`/`kb_standard`/`kb_industry` 覆盖
2. 更新代码中的 `"kb"` 引用为 `"all"`（见第五节）
3. 执行 DELETE

**验证方法：**
```bash
# 验证 kb 中的内容在其他 bank 中可召回
curl -X POST http://localhost:8888/v1/default/banks/kb/memories/recall \
  -H 'Content-Type: application/json' \
  -d '{"query":"政务信息化项目","limit":5}'

curl -X POST http://localhost:8888/v1/default/banks/kb_general/memories/recall \
  -H 'Content-Type: application/json' \
  -d '{"query":"政务信息化项目","limit":5}'
# 比较结果，如果 kb_general 结果覆盖 kb 则 kb 可安全删除
```

### 方案 B2 — 删除 `general` bank（低风险）

- fact_count=50，最后写入 2026-06-02，无文档引用
- 直接 DELETE

**验证方法：**
```bash
curl http://localhost:8888/v1/default/banks
# 确认不含 general
```

### 方案 C — 创建 `kb_template`（可选）

若需要修复「方案模板」bank，执行：
```
POST /v1/default/banks  {"bank_id": "kb_template", "name": "kb_template"}
```

### 方案 D — `business` / `methodology` bank 独立化（远期优化）

当前 `business`(商业分析) 和 `methodology`(方法论) 共享 `kb_general` bank，导致「商业分析」问答时也召回到「综合文件」的内容。远期可考虑：
1. 在 Hindsight 中创建 `kb_business` 和 `kb_methodology`
2. 迁移对应文档
3. 更新 `_HARDCODED_BANKS`

**本次不执行，列为远期建议。**

---

## 五、代码修改清单

### 5.1 `retrieval.py` — 更新 `bank="kb"` 默认参数

| 位置 | 当前代码 | 修改后 |
|------|---------|--------|
| L260 | `async def recall(..., bank: str = "kb", ...)` | `async def recall(..., bank: str = "all", ...)` |
| L280 | `if bank in ("all", "kb") or not hs_bank:` | `if bank == "all" or not hs_bank:` |

### 5.2 `documents.py` — 更新 `_verify_searchable` bank 默认值

| 位置 | 当前代码 | 修改后 |
|------|---------|--------|
| L71 | `v_bank="kb"` | `v_bank="all"` |
| L459 | `bank="kb"` | `bank="all"` |

### 5.3 `documents.py` — 更新 rag-eval recall bank（可选）

| 位置 | 当前代码 | 修改后 |
|------|---------|--------|
| L459 | `bank="kb"` | `bank="all"` |

---

## 六、验证方法

### 6.1 删除前验证

```bash
# 1. 确认空心 bank 列表
curl http://localhost:8888/v1/default/banks | python3 -m json.tool

# 2. 验证 kb 是否与 kb_general 内容重叠
curl -X POST http://localhost:8888/v1/default/banks/kb/memories/recall \
  -H 'Content-Type: application/json' -d '{"query":"测试","limit":3}'
curl -X POST http://localhost:8888/v1/default/banks/kb_general/memories/recall \
  -H 'Content-Type: application/json' -d '{"query":"测试","limit":3}'
```

### 6.2 删除后验证

```bash
# 1. 确认 bank 列表已清理
curl http://localhost:8888/v1/default/banks

# 2. 确认 recall 仍然正常工作（使用 all 或具体 bank）
curl -X POST http://localhost:8888/v1/default/banks/kb_general/memories/recall \
  -H 'Content-Type: application/json' -d '{"query":"政务信息化","limit":5}'

# 3. 重启 kb2-web 后端，确认接口正常
# 4. 跑一条完整问答验证流程
```

### 6.3 代码修改后验证

```bash
# 1. 运行单元测试
cd /home/ubuntu/kb2-web
python -m pytest backend/tests/ -x -v --timeout=60 2>&1 | tail -50

# 2. 启动后端并测试 API
curl http://localhost:3002/api/banks
curl http://localhost:3002/api/query -X POST -H 'Content-Type: application/json' \
  -d '{"query":"等保2.0 安全要求","bank":"standards"}'
```

---

## 七、执行计划汇总

| 优先级 | Bank | 操作 | 风险 | 前置条件 |
|--------|------|------|------|---------|
| P0 | `kb_standards` | DELETE | 无 | 无 |
| P0 | `industry_docs` | DELETE | 无 | 无 |
| P0 | `default` | DELETE | 无 | 无 |
| P1 | `general` | DELETE | 低 | 无文档引用（已验证） |
| P1 | `kb` | 代码修改 → 迁移确认 → DELETE | 中 | 需更新代码中的 `"kb"` 引用为 `"all"` |
| P2 | `kb_template` | 创建 bank 或注释配置 | 低 | 确认是否需要修复 |
| 远期 | `business`/`methodology` | 独立 bank | 低 | 未来再做 |

---

## 附录 A：依赖文件清单

| 文件路径 | 涉及内容 |
|---------|---------|
| `backend/app/services/retrieval.py` | `_HARDCODED_BANKS`, `recall()` bank 默认值 |
| `backend/app/api/documents.py` | `_verify_searchable()`, `get_document_content()`, rag-eval |
| `backend/app/api/upload.py` | `hs_bank` 路由（读取配置） |
| `backend/app/api/banks.py` | bank CRUD（删除 API） |
| `backend/app/services/concept_gen.py` | `_BANK_TO_DOMAIN` 映射 |
| `backend/app/repositories/document_repo.py` | `save()` 的 `hs_bank` 参数 |
| `backend/app/repositories/vector_repo.py` | `HindsightStore` 写入 |
| `backend/tests/integration/test_api_endpoints.py` | 集成测试 mock |
| `scripts/reindex_hindsight.py` | 重索引脚本 |
| `backend/scripts/backfill_*.py` | 数据回填脚本（含 `bank="kb"` 引用） |

## 附录 B：Hindsight API 参考

```bash
# 列出所有 bank
GET /v1/default/banks

# 删除 bank（含所有 memories）
DELETE /v1/default/banks/{bank_id}

# 创建 bank
POST /v1/default/banks  {"bank_id": "xxx", "name": "xxx"}

# 验证 recall
POST /v1/default/banks/{bank_id}/memories/recall  {"query":"...", "limit":5}
```

---
# L05 — 运维观测

# L05 运维观测实施方案 — kb2-web v2

> 项目: kb2-web | 服务端口: 3027 (kb2-web), 8888 (Hindsight)  
> DB: `/home/ubuntu/kb-web/data/kb.db` | 后端: FastAPI (uvicorn, single worker)  
> 系统: Linux (systemd) | 发布日期: 2026-07-09

---

## 目录

1. [现状分析](#1-现状分析)
2. [整体架构](#2-整体架构)
3. [健康检查方案](#3-健康检查方案)
4. [查询指标采集方案](#4-查询指标采集方案)
5. [日报生成方案](#5-日报生成方案)
6. [告警阈值与通知](#6-告警阈值与通知)
7. [交付物清单](#7-交付物清单)
8. [工时估计](#8-工时估计)
9. [附录：SQL 查询 & 脚本参考](#9-附录sql-查询--脚本参考)

---

## 1. 现状分析

### 1.1 现有基础设施

| 项目 | 状态 | 说明 |
|------|------|------|
| `/health` 端点 (kb2-web) | ✅ 可用 | 返回 `{"status":"ok","version":"2.0.0"}`，无需认证 |
| `/api/admin/health` 端点 | ✅ 可用 | 含 DB 连接 + Hindsight 连通性检查 |
| Hindsight `/health` | ✅ 可用 | 返回 `{"status":"healthy","database":"connected"}` |
| systemd 服务 | ✅ 已配 | `kb2-web.service` (3027), `kb-web.service` (旧版) |
| 审计日志 (audit_log 表) | ✅ 已存在 | 含 user_id, query, tokens_used, response_ms, rejected, created_at |
| 主动监控 | ❌ 无 | 仅手动 curl 检查 |
| 集中式日志收集 | ❌ 无 | 仅 stdout |
| 告警通知 | ❌ 无 | 无 |
| 日报生成 | ❌ 无 | 无 |

### 1.2 audit_log 表结构（核心指标数据源）

```sql
CREATE TABLE audit_log (
    id            INTEGER   PRIMARY KEY AUTOINCREMENT,
    user_id       VARCHAR(64) NOT NULL,     -- 查询用户
    query         VARCHAR(500) NOT NULL,     -- 查询内容
    answer        TEXT,                      -- 回答内容
    sources       TEXT,                      -- 来源 JSON
    tokens_used   INTEGER    DEFAULT 0,      -- 消耗 token 数
    cache_hit     INTEGER    DEFAULT 0,      -- 0=未命中, 1=精确命中, 2=语义命中
    response_ms   INTEGER    DEFAULT 0,      -- 响应耗时 (毫秒)
    rejected      VARCHAR(32),               -- NULL=已应答, 其他=拒答原因
    created_at    DATETIME   DEFAULT (datetime('now')),
    INDEX ix_audit_log_created_at (created_at),
    INDEX ix_audit_log_user_id (user_id)
);
```

> **关键字段**：`response_ms` 用于延迟分析, `rejected` 用于拒答率, `cache_hit` 用于缓存命中率, `created_at` 用于时间窗口过滤。

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        cron (每5分钟 / 每日)                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────┐    ┌──────────────────┐    ┌──────────────┐  │
│  │ Health Check       │    │ Metric Collector  │    │ Daily Report │  │
│  │ (每5分钟)           │    │ (每5分钟聚合)      │    │ (每日 08:00) │  │
│  └────────┬──────────┘    └────────┬─────────┘    └──────┬───────┘  │
│           │                        │                     │          │
│           ▼                        ▼                     ▼          │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    日志 / 通知层                                │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐ │  │
│  │  │ kb2-web/logs │  │ Terminal    │  │ (未来: Slack/邮件)    │ │  │
│  │  │  (本地文件)     │  │ stdout      │  │                      │ │  │
│  │  └─────────────┘  └──────────────┘  └──────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 健康检查方案

### 3.1 方案选择

**选型：systemd `ExecStartPre` + 外部 cron 检查双重机制**  
理由：已有 systemd 管理，无需额外部署成本；cron 可提供更丰富的健康状态日志和自愈。

### 3.2 systemd 自动重启（已有）

`kb2-web.service` 已配置 Restart=on-failure。确认/增强配置：

```ini
[Unit]
Description=kb2-web v2
After=network.target hindsight.service

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/kb2-web/backend
ExecStart=/home/ubuntu/kb2-web/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 3027
Restart=on-failure
RestartSec=10
User=ubuntu
Environment=PYTHONPATH=/home/ubuntu/kb2-web/backend

[Install]
WantedBy=multi-user.target
```

> systemd 负责进程级守护；Restart=on-failure 在进程崩溃时自动拉起。

### 3.3 外部健康检查脚本（新增）

**文件**：`backend/scripts/health_check.sh`

功能：
1. 检查 kb2-web `/health` 端点 (127.0.0.1:3027)
2. 检查 Hindsight `/health` 端点 (127.0.0.1:8888)
3. 检查 DB 连通性（通过 kb2-web `/api/admin/health` 端点）
4. 服务挂掉时自动 systemctl restart
5. 持续失败时写报警文件到日志

```bash
#!/usr/bin/env bash
# ── Health check: kb2-web + Hindsight + DB ──
# Runs every 5 minutes via cron.
#
# Install:
#   */5 * * * * /home/ubuntu/kb2-web/backend/scripts/health_check.sh >> /home/ubuntu/kb2-web/logs/health.log 2>&1

set -euo pipefail

BASE=/home/ubuntu/kb2-web
LOG_DIR=$BASE/logs
mkdir -p "$LOG_DIR"

NOW=$(date '+%Y-%m-%d %H:%M:%S')
FAILURES=0
ALERT_FILE="$LOG_DIR/.health_alert"

# ── Check kb2-web ──
if curl -sf http://127.0.0.1:3027/health > /dev/null 2>&1; then
    echo "$NOW [OK] kb2-web: /health reachable"
else
    echo "$NOW [FAIL] kb2-web: /health unreachable → restarting"
    sudo systemctl restart kb2-web.service
    FAILURES=$((FAILURES + 1))
fi

# ── Check Hindsight ──
if curl -sf http://127.0.0.1:8888/health > /dev/null 2>&1; then
    echo "$NOW [OK] Hindsight: /health reachable"
else
    echo "$NOW [FAIL] Hindsight: /health unreachable"
    FAILURES=$((FAILURES + 1))
fi

# ── Check kb2-web detailed health (DB) ──
DETAILED=$(curl -sf http://127.0.0.1:3027/api/admin/health 2>&1) || true
if echo "$DETAILED" | grep -q '"db":"ok"'; then
    echo "$NOW [OK] DB: connected"
else
    echo "$NOW [FAIL] DB: $(echo $DETAILED | grep -oP '"db":"[^"]*"' || echo 'unknown')"
    FAILURES=$((FAILURES + 1))
fi

# ── Alert file management ──
if [ "$FAILURES" -ge 2 ]; then
    # Two or more failures → write alert
    echo "$NOW CRITICAL: $FAILURES services failed" > "$ALERT_FILE"
    echo "$NOW [ALERT] $FAILURES checks failed (threshold ≥ 2)"
else
    # Clear alert when healthy
    if [ -f "$ALERT_FILE" ]; then
        echo "$NOW [RECOVER] All services healthy again" | tee >(cat >> "$ALERT_FILE")
        rm -f "$ALERT_FILE"
    fi
fi
```

### 3.4 健康检查执行计划

| 执行方式 | 频率 | 检查项 | 失败动作 |
|----------|------|--------|----------|
| systemd | 即时 | 进程存活 | `Restart=on-failure` 自动拉起 |
| cron (`health_check.sh`) | 每 5 分钟 | kb2-web /health | systemctl restart |
| cron (`health_check.sh`) | 每 5 分钟 | Hindsight /health | 写日志告警 |
| cron (`health_check.sh`) | 每 5 分钟 | DB 连通性 | 写日志告警 |

### 3.5 自愈策略

| 故障场景 | 恢复手段 | 预期恢复时间 |
|----------|----------|-------------|
| kb2-web 进程 OOM | systemd `Restart=on-failure` | ≤15s |
| kb2-web 无响应(stuck) | cron 检测 → systemctl restart | ≤30s |
| Hindsight 挂掉 | cron 检测 → 写告警文件 | 人工介入 |
| DB 损坏 | cron 检测 → 写告警文件 | 人工修复 |
| 内存泄漏 | 3 次重启仍失败 → 不再自动重启 | 人工介入 |

---

## 4. 查询指标采集方案

### 4.1 指标定义（基于 audit_log 表）

| 指标名称 | 计算公式 | 数据源 | 用途 |
|----------|----------|--------|------|
| 总查询次数 | `COUNT(*)` | audit_log | 系统负载 |
| 独立用户数 | `COUNT(DISTINCT user_id)` | audit_log | 用户活跃度 |
| 平均响应延迟(ms) | `AVG(response_ms)` | audit_log | 性能基准 |
| P50/P95/P99 延迟 | percentile | audit_log | 长尾延迟 |
| 拒答率 | `COUNT(rejected)/COUNT(*)` | audit_log | 质量监控 |
| 缓存命中率 | `SUM(cache_hit>0)/COUNT(*)` | audit_log | 缓存效率 |
| Token 消耗 | `SUM(tokens_used)` | audit_log | LLM 成本 |
| 拒答类型分布 | `rejected` 分组计数 | audit_log | 拒答原因分析 |
| 按小时查询分布 | 按 `created_at` 分组 | audit_log | 高峰时段 |
| Top-N 高频用户 | 按 user_id 分组排序 | audit_log | 用户画像 |
| Top-N 高频查询 | 按 query 分组排序 | audit_log | 热门查询 |

### 4.2 指标采集脚本

**文件**：`backend/scripts/collect_metrics.py`

```python
#!/usr/bin/env python3
"""查询指标采集 — 从 audit_log 表每日聚合。

输出: /home/ubuntu/kb2-web/logs/metrics/<YYYY-MM-DD>.json

配合 cron 每 5 分钟写入增量数据，日报从中读取。
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── 路径 ──
BASE = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(BASE))

DB_PATH = os.environ.get("KB_DB_PATH", "/home/ubuntu/kb-web/data/kb.db")

# ── SQLite raw 连接（避免启动 FastAPI）──
import sqlite3
from collections import defaultdict


def get_connection():
    return sqlite3.connect(DB_PATH)


def collect_hourly_stats(conn, date_str: str):
    """按小时聚合指标。"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            strftime('%H', created_at) AS hour,
            COUNT(*)                                           AS total_queries,
            COUNT(DISTINCT user_id)                            AS unique_users,
            ROUND(AVG(CAST(response_ms AS REAL)), 1)           AS avg_latency_ms,
            ROUND(AVG(CASE WHEN response_ms > 0 THEN CAST(response_ms AS REAL) END), 1) AS avg_latency_ms_nonzero,
            SUM(CASE WHEN rejected IS NOT NULL THEN 1 ELSE 0 END) AS rejected_count,
            SUM(CASE WHEN cache_hit > 0 THEN 1 ELSE 0 END)        AS cache_hit_count,
            SUM(COALESCE(tokens_used, 0))                      AS total_tokens
        FROM audit_log
        WHERE date(created_at) = ?
        GROUP BY hour
        ORDER BY hour
    """, (date_str,))
    rows = cursor.fetchall()

    hourly = []
    for r in rows:
        hourly.append({
            "hour": r[0],
            "total_queries": r[1],
            "unique_users": r[2],
            "avg_latency_ms": r[3],
            "avg_latency_ms_nonzero": r[4],
            "rejected_count": r[5],
            "cache_hit_count": r[6],
            "total_tokens": r[7],
        })
    return hourly


def collect_totals(conn, date_str: str):
    """全天汇总指标。"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COUNT(*)                                           AS total_queries,
            COUNT(DISTINCT user_id)                            AS unique_users,
            ROUND(AVG(CAST(response_ms AS REAL)), 1)           AS avg_latency_ms,
            ROUND(AVG(CASE WHEN response_ms > 0 THEN CAST(response_ms AS REAL) END), 1) AS avg_latency_ms_nonzero,
            SUM(CASE WHEN rejected IS NOT NULL THEN 1 ELSE 0 END) AS rejected_count,
            SUM(CASE WHEN cache_hit > 0 THEN 1 ELSE 0 END)        AS cache_hit_count,
            SUM(COALESCE(tokens_used, 0))                      AS total_tokens
        FROM audit_log
        WHERE date(created_at) = ?
    """, (date_str,))
    r = cursor.fetchone()

    # 百分位延迟
    cursor.execute("""
        SELECT response_ms FROM audit_log
        WHERE date(created_at) = ? AND response_ms > 0
        ORDER BY response_ms
    """, (date_str,))
    latencies = [row[0] for row in cursor.fetchall()]

    percentiles = {}
    if latencies:
        n = len(latencies)
        percentiles = {
            "p50": latencies[n // 2],
            "p90": latencies[int(n * 0.9)],
            "p95": latencies[int(n * 0.95)],
            "p99": latencies[int(n * 0.99)],
        }

    return {
        "date": date_str,
        "total_queries": r[0],
        "unique_users": r[1],
        "avg_latency_ms": r[2],
        "avg_latency_ms_nonzero": r[3],
        "rejected_count": r[4],
        "rejected_rate": round(r[4] / r[0] * 100, 2) if r[0] > 0 else 0,
        "cache_hit_count": r[5],
        "cache_hit_rate": round(r[5] / r[0] * 100, 2) if r[0] > 0 else 0,
        "total_tokens": r[6],
        "percentiles": percentiles,
        "hourly": collect_hourly_stats(conn, date_str),
    }


def collect_top_users(conn, date_str: str, limit: int = 10):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id, COUNT(*) AS cnt
        FROM audit_log
        WHERE date(created_at) = ?
        GROUP BY user_id
        ORDER BY cnt DESC
        LIMIT ?
    """, (date_str, limit))
    return [{"user_id": r[0], "query_count": r[1]} for r in cursor.fetchall()]


def collect_top_queries(conn, date_str: str, limit: int = 10):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT query, COUNT(*) AS cnt
        FROM audit_log
        WHERE date(created_at) = ?
        GROUP BY query
        ORDER BY cnt DESC
        LIMIT ?
    """, (date_str, limit))
    return [{"query": r[0], "count": r[1]} for r in cursor.fetchall()]


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    conn = get_connection()
    try:
        result = collect_totals(conn, date_str)
        result["top_users"] = collect_top_users(conn, date_str)
        result["top_queries"] = collect_top_queries(conn, date_str)

        # 写入文件
        out_dir = BASE / "logs" / "metrics"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{date_str}.json"

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"[OK] 指标已写入 {out_path}")
        print(f"     查询: {result['total_queries']}, 用户: {result['unique_users']}, "
              f"平均延迟: {result['avg_latency_ms']}ms, "
              f"拒答率: {result['rejected_rate']}%, "
              f"缓存命中率: {result['cache_hit_rate']}%")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

### 4.3 增量采集模式（可选优化）

如需每 5 分钟采集，可扩展脚本记录 `last_id`：

```
# 持久化 last_id：
echo "LAST_ID=12345" > /home/ubuntu/kb2-web/logs/metrics/.cursor
# 下次只查 id > 12345 的记录
```

增量模式适合 Dashboard 实时刷新；首期建议只做每日聚合。

---

## 5. 日报生成方案

### 5.1 脚本设计

**文件**：`backend/scripts/daily_report.py`

```python
#!/usr/bin/env python3
"""日报生成 — 从 metrics JSON 生成 Markdown 报告。

输出: /home/ubuntu/kb2-web/logs/reports/<YYYY-MM-DD>.md
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/


def load_metrics(date_str: str) -> dict | None:
    path = BASE / "logs" / "metrics" / f"{date_str}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fmt_ms(ms: float) -> str:
    if ms >= 1000:
        return f"{ms/1000:.2f}s"
    return f"{ms:.0f}ms"


def generate_report(metrics: dict) -> str:
    d = metrics
    lines = []

    lines.append(f"# kb2-web 运维日报 — {d['date']}")
    lines.append(f"")
    lines.append(f"> 生成时间: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append(f"")
    lines.append(f"## 总体概况")
    lines.append(f"")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 总查询次数 | {d['total_queries']} |")
    lines.append(f"| 独立用户数 | {d['unique_users']} |")
    lines.append(f"| 平均延迟 (含 0) | {fmt_ms(d['avg_latency_ms'])} |")
    lines.append(f"| 平均延迟 (仅非零) | {fmt_ms(d['avg_latency_ms_nonzero'])} |")
    lines.append(f"| 拒答数 / 拒答率 | {d['rejected_count']} / {d['rejected_rate']}% |")
    lines.append(f"| 缓存命中 / 命中率 | {d['cache_hit_count']} / {d['cache_hit_rate']}% |")
    lines.append(f"| Token 消耗 | {d['total_tokens']:,} |")
    lines.append(f"")

    # 百分位延迟
    p = d.get("percentiles", {})
    if p:
        lines.append(f"## 延迟百分位")
        lines.append(f"")
        lines.append(f"| 百分位 | 延迟 |")
        lines.append(f"|--------|------|")
        lines.append(f"| P50 | {fmt_ms(p.get('p50', 0))} |")
        lines.append(f"| P90 | {fmt_ms(p.get('p90', 0))} |")
        lines.append(f"| P95 | {fmt_ms(p.get('p95', 0))} |")
        lines.append(f"| P99 | {fmt_ms(p.get('p99', 0))} |")
        lines.append(f"")

    # 告警标记
    alerts = []
    if d["rejected_rate"] > 5:
        alerts.append(f"⚠️ **拒答率 {d['rejected_rate']}% 超过阈值 5%**")
    if p and p.get("p95", 0) > 60000:
        alerts.append(f"⚠️ **P95 延迟 {fmt_ms(p['p95'])} 超过阈值 60s**")
    if p and p.get("p99", 0) > 120000:
        alerts.append(f"🔴 **P99 延迟 {fmt_ms(p['p99'])} 超过严重阈值 120s**")
    if d["total_queries"] == 0:
        alerts.append(f"🔴 **当日无查询 — 服务可能异常**")
    if alerts:
        lines.append(f"## ⚠️ 告警汇总")
        lines.append(f"")
        for a in alerts:
            lines.append(f"- {a}")
        lines.append(f"")

    # 按小时分布
    hourly = d.get("hourly", [])
    if hourly:
        lines.append(f"## 小时级查询分布")
        lines.append(f"")
        lines.append(f"| 小时 | 查询数 | 用户数 | 平均延迟 | 拒答数 | 缓存命中 | Token |")
        lines.append(f"|------|--------|--------|----------|--------|----------|-------|")
        for h in hourly:
            lines.append(
                f"| {h['hour']}:00 | {h['total_queries']} | {h['unique_users']} "
                f"| {fmt_ms(h['avg_latency_ms'])} | {h['rejected_count']} "
                f"| {h['cache_hit_count']} | {h['total_tokens']:,} |"
            )
        lines.append(f"")

    # Top 用户
    top_users = d.get("top_users", [])
    if top_users:
        lines.append(f"## Top 活跃用户")
        lines.append(f"")
        lines.append(f"| 排名 | 用户 | 查询次数 |")
        lines.append(f"|------|------|----------|")
        for i, u in enumerate(top_users, 1):
            lines.append(f"| {i} | {u['user_id']} | {u['query_count']} |")
        lines.append(f"")

    # Top 查询
    top_q = d.get("top_queries", [])
    if top_q:
        lines.append(f"## Top 高频查询")
        lines.append(f"")
        lines.append(f"| 排名 | 查询内容 | 次数 |")
        lines.append(f"|------|----------|------|")
        for i, q in enumerate(top_q, 1):
            truncated = q["query"][:60] + ("..." if len(q["query"]) > 60 else "")
            lines.append(f"| {i} | `{truncated}` | {q['count']} |")
        lines.append(f"")

    return "\n".join(lines)


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    metrics = load_metrics(date_str)
    if metrics is None:
        print(f"[WARN] {date_str} 的指标数据不存在。请先运行 collect_metrics.py {date_str}")
        sys.exit(1)

    report = generate_report(metrics)

    out_dir = BASE / "logs" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_str}.md"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"[OK] 日报已写入 {out_path}")
    print(report[:500] + "\n...")


if __name__ == "__main__":
    main()
```

### 5.2 日报示例输出

> **注**：以下为格式示例，首日运行后实际数据取决于 audit_log 表内容。

```markdown
# kb2-web 运维日报 — 2026-07-08

> 生成时间: 2026-07-09 00:05:00 UTC

## 总体概况

| 指标 | 数值 |
|------|------|
| 总查询次数 | 1,247 |
| 独立用户数 | 23 |
| 平均延迟 | 3.2s |
| 拒答率 | 2.8% |
| 缓存命中率 | 41.5% |
| Token 消耗 | 891,234 |

## 延迟百分位

| 百分位 | 延迟 |
|--------|------|
| P50 | 1.8s |
| P90 | 8.5s |
| P95 | 15.2s |
| P99 | 42.1s |

## 小时级查询分布
...

## 告警汇总
- ⚠️ P99 延迟 42.1s 接近阈值 60s
```

### 5.3 cron 定时执行

```bash
# crontab -e 添加以下条目：

# ── 每 5 分钟健康检查 ──
*/5 * * * * /home/ubuntu/kb2-web/backend/scripts/health_check.sh >> /home/ubuntu/kb2-web/logs/health.log 2>&1

# ── 每日 00:05 采集前一日指标 ──
5 0 * * * /home/ubuntu/kb2-web/backend/scripts/cron_collect_metrics.sh >> /home/ubuntu/kb2-web/logs/cron_metrics.log 2>&1

# ── 每日 00:10 生成前一日日报 ──
10 0 * * * /home/ubuntu/kb2-web/backend/scripts/cron_daily_report.sh >> /home/ubuntu/kb2-web/logs/cron_report.log 2>&1
```

---

## 6. 告警阈值与通知

### 6.1 阈值定义

| 指标 | 正常 | 警告 (WARN) | 严重 (CRITICAL) | 依据 |
|------|------|-------------|-----------------|------|
| 查询平均延迟 | < 10s | 10s–30s | > 30s | LLM 推理典型时间 |
| P95 延迟 | < 30s | 30s–60s | > 60s (任务要求) | L05 要求 >60s 告警 |
| P99 延迟 | < 60s | 60s–120s | > 120s | 长尾容忍度 |
| 拒答率 (rejected) | < 3% | 3%–5% | > 5% (任务要求) | L05 要求 >5% 告警 |
| 缓存命中率 | > 30% | 15%–30% | < 15% | 缓存效率 |
| 每小时无查询 | - | - | 连续 2 小时 0 查询 | 服务异常信号 |
| kb2-web 服务状态 | 运行 | - | 不健康 / 不可达 | 进程级 |
| Hindsight 状态 | 健康 | - | 不可达 | 依赖服务 |
| DB 连通性 | 正常 | - | 异常 | 数据层 |
| 内存使用 | < 70% | 70%–85% | > 85% | OOM 防范 |
| 磁盘使用 | < 80% | 80%–90% | > 90% | 日志/DB 空间 |

### 6.2 告警通知方式

**第一期（无外部通知基础设施）：**

| 级别 | 通知方式 | 内容 |
|------|----------|------|
| WARN | 日报标注 | 日报中「告警汇总」章节 |
| CRITICAL | 日报标注 + 写入 `logs/.health_alert` | 日报 + 健康检查输出加 [ALERT] 标记 |
| 服务重启 | 写入 `logs/health.log` | systemd 或 cron 触发重启时记录 |

**第二期（推荐后续接入）：**

| 方式 | 集成成本 | 说明 |
|------|----------|------|
| Slack Webhook | 低 (~2h) | POST JSON 到 Slack |
| 飞书/钉钉 Webhook | 低 (~2h) | 国内团队首选 |
| 邮件 (smtplib) | 低 (~1h) | 简单可靠 |
| Telegram Bot | 低 (~1h) | 个人运维者 |

### 6.3 告警延迟等级与响应

| 严重度 | 响应 SLA | 升级路径 |
|--------|----------|----------|
| CRITICAL (P99>120s / 服务全挂) | 15min 内响应 | 立即 SSH / systemctl status |
| WARN (P95>60s / 拒答>5%) | 2h 内确认 | 次日日报分析根因 |
| INFO (缓存命中率低) | 下个迭代 | 优化缓存策略 |

---

## 7. 交付物清单

### 7.1 脚本文件

| # | 文件路径 | 类型 | 说明 |
|---|----------|------|------|
| 1 | `backend/scripts/health_check.sh` | Shell | 每 5 分钟健康检查 + 自愈 |
| 2 | `backend/scripts/collect_metrics.py` | Python | 查询指标聚合 (从 audit_log) |
| 3 | `backend/scripts/daily_report.py` | Python | 日报生成 (Markdown) |
| 4 | `backend/scripts/cron_collect_metrics.sh` | Shell | cron 包装脚本 (指标采集) |
| 5 | `backend/scripts/cron_daily_report.sh` | Shell | cron 包装脚本 (日报生成) |

### 7.2 输出目录结构

```
/home/ubuntu/kb2-web/
└── logs/
    ├── health.log               # 健康检查日志 (持续追加)
    ├── .health_alert            # 告警标记文件 (存在 = CRITICAL)
    ├── cron_metrics.log         # 指标采集 cron 日志
    ├── cron_report.log          # 日报 cron 日志
    ├── metrics/
    │   └── 2026-07-08.json      # 每日指标 JSON
    └── reports/
        └── 2026-07-08.md        # 每日日报 Markdown
```

### 7.3 配置变更

| # | 变更对象 | 变更内容 | 说明 |
|---|----------|----------|------|
| 6 | `crontab` | 新增 3 条 cron 条目 | health, metrics, report |
| 7 | `kb2-web.service` | 确认 Restart 配置 | 可选增强 |

### 7.4 文档

| # | 文件 | 说明 |
|---|------|------|
| 8 | `docs/l05-ops-observability.md` | 本方案文档 |

---

## 8. 工时估计

### 8.1 开发工时

| 任务 | 工时 (人·时) | 依赖 | 负责人 |
|------|-------------|------|--------|
| **P1: 健康检查** | **4h** | - | 运维/后端 |
| ├─ 编写 health_check.sh | 1.5h | - | |
| ├─ 配置 cron | 0.5h | health_check.sh | |
| └─ 验证 systemd 自动重启 | 2h | kb2-web.service | |
| **P2: 指标采集** | **6h** | - | 后端 |
| ├─ 实现 collect_metrics.py | 3h | audit_log 表现用字段 | |
| ├─ 编写 cron 包装脚本 | 0.5h | collect_metrics.py | |
| ├─ 测试 SQL 聚合查询 | 1h | DB 连通 | |
| └─ 首日历史数据回填 | 1.5h | collect_metrics.py | |
| **P3: 日报生成** | **3h** | P2 完成 | 后端 |
| ├─ 实现 daily_report.py | 2h | collect_metrics.py 输出 | |
| └─ 编写 cron 包装脚本 | 1h | daily_report.py | |
| **P4: 告警集成** | **4h** | P1–P3 | 运维 |
| ├─ 实施阈值逻辑（hardcode 日报内） | 1h | daily_report.py | |
| ├─ 异常/边界行为验证 | 2h | 全流程 | |
| └─ 编写操作手册 (runbook) | 1h | 全流程 | |
| **P5: 测试与验证** | **3h** | P1–P4 | QA/后端 |
| ├─ 健康检查故障注入测试 | 1h | P1 | |
| ├─ 指标准确性验证 | 1h | P2 | |
| └─ 日报格式验证 | 1h | P3 | |

### 8.2 总计

| 阶段 | 工时 | 日历参考 (1 人) |
|------|------|-----------------|
| **开发** | 17h | 2.5 工作日 |
| **测试** | 3h | 同开发期 |
| **合计** | **20h** | **3 工作日内交付** |

### 8.3 第二期预算（推荐）

| 任务 | 工时 | 说明 |
|------|------|------|
| 接入 Slack/飞书 Webhook | 2h | 告警通知 |
| 可视化 Dashboard (Grafana) | 8h | SQLite → Grafana |
| 日志集中化 (Loki/Syslog) | 4h | 弃用本地文件 |
| **二期合计** | **14h** | 可按需拆分 |

---

## 9. 附录：SQL 查询 & 脚本参考

### 9.1 核心 SQL 查询（可直接用于验证）

```sql
-- 日聚合
SELECT
    DATE(created_at) AS day,
    COUNT(*) AS total,
    COUNT(DISTINCT user_id) AS users,
    ROUND(AVG(response_ms), 1) AS avg_latency,
    SUM(CASE WHEN rejected IS NOT NULL THEN 1 ELSE 0 END) AS rejected,
    SUM(CASE WHEN cache_hit > 0 THEN 1 ELSE 0 END) AS cache_hit,
    SUM(tokens_used) AS tokens
FROM audit_log
WHERE created_at >= '2026-07-08' AND created_at < '2026-07-09'
GROUP BY day;

-- 小时聚合
SELECT
    strftime('%H', created_at) AS hour,
    COUNT(*) AS queries,
    ROUND(AVG(response_ms), 1) AS avg_latency_ms,
    SUM(CASE WHEN rejected IS NOT NULL THEN 1 ELSE 0 END) AS rejected,
    SUM(CASE WHEN cache_hit > 0 THEN 1 ELSE 0 END) AS cache_hit
FROM audit_log
WHERE DATE(created_at) = '2026-07-08'
GROUP BY hour
ORDER BY hour;

-- 百分位延迟（SQLite 不支持内置 percentile，用 Python 排序后取索引）
-- 参考 collect_metrics.py 中的实现

-- 拒答类型分布
SELECT rejected, COUNT(*) AS cnt
FROM audit_log
WHERE rejected IS NOT NULL AND DATE(created_at) = '2026-07-08'
GROUP BY rejected
ORDER BY cnt DESC;

-- 高频查询 Top-20
SELECT query, COUNT(*) AS cnt
FROM audit_log
WHERE DATE(created_at) = '2026-07-08'
GROUP BY query
ORDER BY cnt DESC
LIMIT 20;
```

### 9.2 故障排查命令

```bash
# 检查服务状态
sudo systemctl status kb2-web.service
sudo journalctl -u kb2-web.service -n 50 --no-pager

# 查看最新健康检查日志
tail -20 /home/ubuntu/kb2-web/logs/health.log

# 查看告警状态
cat /home/ubuntu/kb2-web/logs/.health_alert 2>/dev/null || echo "无告警"

# 查看最新日报
ls -lt /home/ubuntu/kb2-web/logs/reports/ | head -3

# 手动触发指标采集（某日）
python3 /home/ubuntu/kb2-web/backend/scripts/collect_metrics.py 2026-07-08

# 手动生成日报
python3 /home/ubuntu/kb2-web/backend/scripts/daily_report.py 2026-07-08

# 手动健康检查
bash /home/ubuntu/kb2-web/backend/scripts/health_check.sh

# 查看当日指标 JSON
cat /home/ubuntu/kb2-web/logs/metrics/$(date '+%Y-%m-%d').json

# DB 直查
sqlite3 /home/ubuntu/kb-web/data/kb.db "SELECT COUNT(*) FROM audit_log WHERE date(created_at)='2026-07-08'"
```

### 9.3 关键审计日志字段释义

| 字段 | 类型 | 含义 | 备注 |
|------|------|------|------|
| `response_ms` | INT | 从收到请求到返回回答的端到端耗时(毫秒) | 0 可能表示缓存命中极快或异常 |
| `cache_hit` | INT | 0=未命中, 1=精确命中, 2=语义命中 | 语义命中是向量缓存 |
| `rejected` | VARCHAR(32) | 拒答类型，如 `knowledge_gap`, `low_coverage` | NULL 表示正常回答 |
| `tokens_used` | INT | LLM 调用消耗的 token 数 | 仅实际调用 LLM 时有值 |
| `created_at` | DATETIME | 查询时间戳 (UTC) | 所有时间窗口以此为准 |

---

---

## L06 — 前端视觉优化

> 新增日期: 2026-07-09
> 当前状态: CSS Variables + Vue SFC scoped styles，无 UI 框架
> 问题: 功能完整但视觉风格朴素——纯白背景、直角/近直角、缺乏层次感、色彩平淡

### 1. 现状诊断

**现有设计资产**：
- `frontend/src/assets/main.css` — 18 个 CSS 变量，`--radius: 0px`（直角），4 色语义体系
- 9 个 views + 5 个 components，全部用 scoped styles
- 无阴影、无渐变、无过渡动画体系、无图标库

**用户感知问题**（基于界面直观测评）：
1. 整体「白板感」 — 背景纯白，卡片与背景边界靠细边框区分，缺乏层次
2. 按钮平淡 — 直角 + 无阴影，hover 仅变色
3. 侧栏列表密集 — 无间距、无图标，11 个 bank 条目文字堆叠
4. 搜索结果卡片 — 无层级，来源标签拥挤
5. 上传/文档管理表格 — 直角表头，视觉单调
6. 登录页 — 居中布局但无品牌感

### 2. 优化原则

1. **不改功能逻辑** — 只改 CSS/scoped styles，不动 Vue template 结构和 JS/TS 逻辑
2. **不引入 UI 框架** — 保持纯 CSS Variables + scoped styles，不引入 Element Plus / Naive UI 等重框架
3. **渐进式** — 先改 main.css（全局变量），再改各组件 scoped styles
4. **保留现有 token 名称** — 只追加、不改名

### 3. CSS 变量补充

在 `frontend/src/assets/main.css` 追加：

```css
:root {
  /* ── 圆角（改为 6px 柔角） ── */
  --radius-sm: 4px;
  --radius: 6px;            /* 原 0px → 6px */
  --radius-md: 8px;
  --radius-lg: 12px;

  /* ── 阴影层级 ── */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.04);
  --shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md: 0 4px 6px rgba(0,0,0,0.04), 0 2px 4px rgba(0,0,0,0.03);
  --shadow-lg: 0 10px 15px rgba(0,0,0,0.05), 0 4px 6px rgba(0,0,0,0.03);

  /* ── 背景层级 ── */
  --surface: hsl(0, 0%, 100%);
  --surface-hover: hsl(220, 15%, 95%);
  --surface-elevated: hsl(0, 0%, 97%);
  --bg-card: hsl(0, 0%, 100%);
  --bg-input: hsl(0, 0%, 100%);

  /* ── 文字层级补全 ── */
  --fg-secondary: hsl(220, 15%, 35%);
  --fg-on-accent: hsl(0, 0%, 100%);
  --fg-on-danger: hsl(0, 0%, 100%);

  /* ── 语义色补全（浅色背景） ── */
  --danger-bg:  hsl(0, 80%, 96%);
  --warning-bg: hsl(38, 80%, 96%);
  --success-bg: hsl(145, 50%, 95%);
  --info-bg:    hsl(210, 60%, 96%);

  /* ── 字号尺度 ── */
  --text-xs:    0.7rem;
  --text-sm:    0.75rem;
  --text-base:  0.825rem;
  --text-md:    0.875rem;
  --text-lg:    0.95rem;
  --text-xl:    1.1rem;
  --text-2xl:   1.4rem;
  --text-3xl:   1.5rem;

  /* ── 间距尺度 ── */
  --space-xs:   0.25rem;
  --space-sm:   0.5rem;
  --space-md:   0.75rem;
  --space:      1rem;
  --space-lg:   1.5rem;
  --space-xl:   2rem;

  /* ── 过渡 ── */
  --transition: 0.15s ease;
  --transition-slow: 0.25s ease;
}
```

### 4. 全局样式改造

```css
/* main.css 新增 */
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: var(--space);
}

button, input, textarea, select {
  border-radius: var(--radius-sm);
}

.page-title {
  font-size: var(--text-xl, 1.1rem);
  font-weight: 600;
  color: var(--fg);
  margin-bottom: var(--space-lg);
}
```

### 5. 组件级优化清单

#### 5.1 AppSidebar.vue
- 侧栏卡片添加 `box-shadow: var(--shadow)`
- 当前 bank 高亮加左边界 `border-left: 3px solid var(--accent)`
- bank 项 hover 用 `var(--surface-hover)` 替代当前硬编码色
- bank 条目添加间距 `gap: 2px`
- 按钮样式统一用 token

#### 5.2 AppHeader.vue
- 顶部加 `box-shadow: var(--shadow-sm)` 分隔感
- 导航链接 hover 用 `var(--surface-hover)` 背景

#### 5.3 QueryView.vue
- 搜索输入框添加 `box-shadow: var(--shadow-sm)`（聚焦时用 `--shadow`）
- 搜索结果卡片添加 `box-shadow: var(--shadow)`，hover 升到 `--shadow-md`
- 搜索按钮用渐变背景或主色填充
- 历史记录条目用 `--surface-hover` 区分
- 来源标签徽章用 token 化颜色（`--info-bg`, `--warning-bg` 等）

#### 5.4 ResultCard.vue
- 卡片加 `border-radius: var(--radius)` + `box-shadow: var(--shadow)`
- source-item hover 加浅色背景
- 标签颜色用 token：`.fee-badge` → `var(--warning-bg)`, `.kw-badge` → `var(--info-bg)`
- 高亮标记用 `background: var(--warning)` + `color: white`（而非 #fff176）

#### 5.5 LoginView.vue
- 登录框加 `box-shadow: var(--shadow-lg)` + `border-radius: var(--radius-lg)`
- 品牌标识增加间距
- 错误提示 token 化

#### 5.6 DocumentsView.vue / UploadView.vue / BanksView.vue 等管理页
- 表头用 `background: var(--bg-alt)` + `font-weight: 600`
- 表格行 hover 用 `var(--surface-hover)`
- 空状态区域居中加灰
- 按钮系统化（btn-sm, btn-primary, btn-danger 用 token）

#### 5.7 Toast.vue
- `border-radius: var(--radius)`
- `box-shadow: var(--shadow-lg)`
- 背景色用语义 token

### 6. 不做的（保持现状）

- ❌ 不替换字体（保留 Inter + JetBrains Mono）
- ❌ 不引入图标库（保持纯文字 UI）
- ❌ 不改功能逻辑
- ❌ 不改 template HTML 结构
- ❌ 不引入 dark mode
- ❌ 不引入 CSS-in-JS / Tailwind

### 7. 验收标准

1. 全局 `--radius: 6px` 生效——所有按钮/输入框/卡片应有柔角
2. 卡片有 `box-shadow` 视觉层次——页面不再「平」
3. 查询页搜索结果卡片有层次感
4. 侧栏 bank 列表有视觉反馈（hover 高亮、选中标记）
5. 所有硬编码颜色替换为 CSS 变量
6. `npm run build` 无报错
7. 服务重启后看浏览器端效果

### 8. 修改文件清单

| 文件 | 改动类型 |
|------|---------|
| `frontend/src/assets/main.css` | 追加 CSS 变量 + 更新全局样式 |
| `frontend/src/components/AppSidebar.vue` | scoped styles token 化 + 视觉增强 |
| `frontend/src/components/AppHeader.vue` | 顶部阴影 + 导航 hover |
| `frontend/src/components/ResultCard.vue` | 卡片阴影 + 标签 token 化 |
| `frontend/src/components/Toast.vue` | 阴影 + 圆角 |
| `frontend/src/components/ConfirmDialog.vue` | 圆角 + 阴影 |
| `frontend/src/views/QueryView.vue` | 搜索框 + 结果卡片视觉增强 |
| `frontend/src/views/LoginView.vue` | 登录框阴影 + 圆角 |
| `frontend/src/views/DocumentsView.vue` | 表格样式 token 化 |
| `frontend/src/views/UploadView.vue` | 按钮/区域 token 化 |
| `frontend/src/views/BanksView.vue` | 表格样式 token 化 |
| `frontend/src/views/AdminView.vue` | 卡片样式 token 化 |
| `frontend/src/views/DocumentDetail.vue` | 详情卡片 token 化 |

### 9. 工时估计

| 阶段 | 工时 | 说明 |
|:----|:-----|:-----|
| main.css 变量追加 + 全局样式 | 1h | 核心 token 定义 |
| 查询页（QueryView + ResultCard） | 3h | 用户使用最频繁 |
| 侧栏 + 顶部（AppSidebar + AppHeader） | 1.5h | 首屏感知 |
| 管理页（6 个 views 统一样式） | 4h | Documents/Upload/Banks/Admin/Detail |
| Toast + ConfirmDialog | 0.5h | 弹出组件 |
| LoginView | 0.5h | 品牌感 |
| npm run build + 服务重启验证 | 2h | |
| **合计** | **~12h** | 2 个工作日内 |

---

## 变更历史

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| v1.1 | 2026-07-09 | Hermes Agent | 新增 L06 前端视觉优化 + 更新优先级表（标注 pgvector 完成状态）|
| v1.0 | 2026-07-09 | Hermes Agent | 初版 — 完整 L05 运维观测实施方案 |
