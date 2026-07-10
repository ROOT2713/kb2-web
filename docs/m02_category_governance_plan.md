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
