# LLM Wiki V2 + OKF 深度分析报告
## —— 如何帮助 kb2-web 知识库改进内容管理与检索能力

**日期**: 2026-06-21  
**分析对象**: kb2-web (FastAPI + SQLite + Hindsight 向量库)  
**参考框架**: LLM Wiki V2 (rohitg00) + OKF v0.1 (Google Cloud)

---

## 一、核心诊断：kb2-web 当前架构的能力边界

### 1.1 现有架构一览

```
┌─────────────────────────────────────────────────────────────┐
│  Upload Pipeline                                             │
│  上传文档 → parse_document(PDF/MD/TXT/XLSX)                │
│         → profile_document(doc_type: gb/regulation/generic)  │
│         → heading_chunk (parent-child, 512 token)           │
│         → Hindsight upsert (向量存储 + tags)                 │
│         → SQLite documents 表 (元数据)                        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Query Pipeline                                              │
│  用户查询 → 精确标题匹配 → BM25 检索                         │
│           → Hindsight dense recall (向量)                    │
│           → RRF 融合排序                                     │
│           → keyword_rerank (词面信号重排)                     │
│           → llm_rerank (LLM 语义重排, 可选)                  │
│           → _generate_answer (LLM 生成答案)                  │
│           → logic_validate (数字/标准号一致性校验)             │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 当前能力与不足

| 维度 | 当前能力 | 核心不足 |
|------|---------|---------|
| **文档存储** | SQLite 元数据 + Hindsight 向量 | 无结构化 frontmatter、无 concept_id、无版本管理 |
| **分块策略** | heading-based parent-child chunking | 纯文本切割，无元数据继承，chunk 间无关联 |
| **检索** | BM25 + Dense + RRF + keyword_rerank | 无 graph 关系检索、无 confidence 权重、无时效性排序 |
| **质量评估** | assess_quality (文本质量) + logic_validate (答案一致性) | 无 confidence 评分、无过时检测、无自动 review |
| **生命周期** | created_at / updated_at | 无 superseded/stale/last_confirmed、无遗忘曲线 |
| **知识组织** | 6 个 bank 分类 | 无 concept 关系图、无 citation 追溯、无知识聚合 |
| **输出能力** | 单次问答 + sources 列表 | 无提取、无多源组合生成、无结构化报告输出 |

---

## 二、LLM Wiki V2 的 9 个概念 → kb2-web 映射分析

### 2.1 概念总览映射表

| # | V2 概念 | kb2-web 现状 | 落地方案 | 难度 | 优先级 |
|---|---------|-------------|---------|------|--------|
| 1 | **Confidence** (置信度) | quality_score (文本质量 0-100, 仅评估字符) | 扩展为知识置信度：多源支撑度 + 时效性 + 被引用次数 | ⭐⭐ | P0 |
| 2 | **Last Confirmed** (最后确认时间) | 无 | 新增字段 + 自动衰减计算 | ⭐ | P0 |
| 3 | **Superseded** (被取代) | 无 | 新增 superseded_by 字段 + 版本链 | ⭐⭐ | P1 |
| 4 | **Stale / Review Required** (过时/待审) | 无 | 基于 last_confirmed + access_count 计算 | ⭐ | P1 |
| 5 | **Typed Knowledge Graph** (类型化知识图谱) | chunks 之间无关联关系 | 新增 knowledge_edges 表 + 基于 heading/引用自动生成 | ⭐⭐⭐ | P2 |
| 6 | **Hybrid Retrieval** (BM25+Vector+Graph+RRF) | BM25+Vector+RRF 已有 | 加入 Graph 邻域扩展检索 | ⭐⭐ | P1 |
| 7 | **Quality Gates** (质量门禁) | assess_quality + logic_validate | 扩展为自动 review pipeline | ⭐⭐ | P1 |
| 8 | **Crystallization** (结晶化) | 无 | 多 chunk 合并为精炼知识条目 | ⭐⭐⭐ | P2 |
| 9 | **YAML Frontmatter** (结构化元数据) | 无结构化元数据 | OKF 格式集成 | ⭐⭐ | P0 |

### 2.2 逐概念深度分析

---

#### 概念 1: Confidence（置信度）

**V2 定义**: 每条事实都应携带置信度分数，反映其被多少来源支撑、最近何时确认、是否有矛盾。

**kb2-web 现状**: 
- `quality_score` 字段（0-100）实际来自 `assess_quality()` 函数，只评估文本字符质量（有意义字符占比、乱码比例、重复字符），**不是知识置信度**
- Hindsight 的 chunks 有 `tags` 但无 confidence 标注
- `coverage_pct` 和 `searchable` 只是上传后验证字段

**落地方案**:

```python
# === 数据库变更 ===
# documents 表新增字段
ALTER TABLE documents ADD COLUMN confidence REAL DEFAULT 0.5;
ALTER TABLE documents ADD COLUMN source_count INTEGER DEFAULT 1;
ALTER TABLE documents ADD COLUMN last_accessed_at DATETIME;
ALTER TABLE documents ADD COLUMN access_count INTEGER DEFAULT 0;

# === confidence 计算公式 ===
def compute_confidence(doc_id: str) -> float:
    """
    confidence = f(source_count, time_decay, access_frequency, contradiction_count)
    
    基础分 = min(source_count / 3, 1.0) * 0.4   # 多源支撑
    时效分 = exp(-days_since_confirmed / 180) * 0.3  # 半衰期180天
    活跃分 = min(access_count / 20, 1.0) * 0.2     # 被引用次数
    矛盾分 = (1 - contradiction_ratio) * 0.1        # 无矛盾加分
    """
```

**实现要点**:
1. 在 `documents` 表新增 `confidence` (REAL)、`source_count` (INT)、`last_accessed_at` (DATETIME)、`access_count` (INT)
2. 上传时：同标题文档匹配 → source_count 递增
3. 查询时：每次命中 → access_count++，更新 last_accessed_at
4. 定期 cron：重新计算所有文档的 confidence（含时间衰减）

**难度**: ⭐⭐（中等，主要是数据模型扩展 + 定时任务）

---

#### 概念 2: Last Confirmed（最后确认时间）

**V2 定义**: 知识条目最后一次被验证/确认的时间戳。

**kb2-web 现状**: 仅有 `updated_at`（任何更新都触发），不区分"内容更新"和"知识确认"。

**落地方案**:

```python
# documents 表新增
ALTER TABLE documents ADD COLUMN last_confirmed_at DATETIME;
ALTER TABLE documents ADD COLUMN confirm_count INTEGER DEFAULT 0;

# 触发时机：
# 1. 上传新文档匹配已有主题 → 确认旧文档仍有效
# 2. 用户查询命中后反馈"有用" → 确认
# 3. 定期 review job → 人工/自动确认
```

**与 confidence 联动**: last_confirmed_at 直接影响 confidence 的时效分计算。

**难度**: ⭐（简单，字段 + 简单触发逻辑）

---

#### 概念 3: Superseded（被取代）

**V2 定义**: 新信息取代旧信息时，旧条目应被标记为 superseded，保留但不活跃。

**kb2-web 现状**: 无此能力。同标题文档上传时 `content_hash` 去重，但没有版本链概念。

**落地方案**:

```python
# 新增表：knowledge_versions
CREATE TABLE knowledge_versions (
    version_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,           -- 当前有效版本
    superseded_by TEXT,             -- 被哪个版本取代
    superseded_at DATETIME,
    version_note TEXT,              -- 取代原因
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);

# documents 表新增
ALTER TABLE documents ADD COLUMN is_superseded INTEGER DEFAULT 0;
ALTER TABLE documents ADD COLUMN superseded_by TEXT;  -- 指向新版本 doc_id

# 上传流程变更：
# 1. 匹配同标题文档
# 2. 比较 content_hash
# 3. 若不同 → 旧文档标记 superseded_by = 新 doc_id
# 4. Hindsight 中旧 chunks 标记 tag: superseded
```

**检索影响**: query pipeline 中过滤 `is_superseded=1` 的文档，或降低其权重。

**难度**: ⭐⭐（中等，需要上传流程改造 + 版本链管理）

---

#### 概念 4: Stale / Review Required（过时/待审）

**V2 定义**: 长期未被访问或确认的知识应标记为过时，触发人工审核。

**kb2-web 现状**: 无此能力。139+ 文档中可能存在过时内容但无法识别。

**落地方案**:

```python
# documents 表新增
ALTER TABLE documents ADD COLUMN status TEXT DEFAULT 'active';
-- status 枚举: active | stale | review_required | archived

# 自动检测逻辑（每日 cron job）
def detect_stale_documents():
    """
    规则：
    1. confidence < 0.3 → review_required
    2. last_confirmed_at 超过 180 天 → stale
    3. access_count = 0 且 created_at > 90 天 → review_required
    4. 被 superseded → archived
    """
```

**与用户需求的关联**: "提取特定主题所有内容"时，需要过滤掉 stale 文档。

**难度**: ⭐（简单，cron job + 规则判断）

---

#### 概念 5: Typed Knowledge Graph（类型化知识图谱）

**V2 定义**: Wiki 中的知识条目之间应有显式的类型化关系（depends_on, contradicts, refines 等）。

**kb2-web 现状**: chunks 之间完全无关联。唯一结构是 parent-child chunk 层级（来自 heading chunking）。

**落地方案**:

```python
# 新增表：knowledge_edges
CREATE TABLE knowledge_edges (
    edge_id TEXT PRIMARY KEY,
    source_doc_id TEXT NOT NULL,
    target_doc_id TEXT NOT NULL,
    relation TEXT NOT NULL,       -- related | depends_on | supersedes | contradicts | refines | cites
    weight REAL DEFAULT 1.0,
    created_at DATETIME,
    FOREIGN KEY (source_doc_id) REFERENCES documents(doc_id),
    FOREIGN KEY (target_doc_id) REFERENCES documents(doc_id)
);

# 自动生成关系的策略：
# 1. 标题相似度 → related
# 2. 引用相同标准号 → related (shared_citation)
# 3. superseded_by → supersedes
# 4. LLM 批量分析文档对 → depends_on, refines, contradicts

# 检索增强：graph-aware retrieval
def graph_expand(doc_ids: list, depth: int = 1) -> list:
    """从命中文档出发，沿关系图谱扩展 N 距离内的关联文档"""
```

**检索影响**: 在 RRF 融合后，加入 graph 信号作为第三路。

**难度**: ⭐⭐⭐（复杂，需要图谱构建 + 批量分析 + 检索 pipeline 改造）

---

#### 概念 6: Hybrid Retrieval（混合检索）

**V2 定义**: BM25 + Dense + Graph + RRF 的四路融合。

**kb2-web 现状**: 已有 BM25 + Dense + RRF 三路 + keyword_rerank + llm_rerank。缺少 Graph 路。

**落地方案**:

```python
# 当前 pipeline:
# dense_recall → bm25_search → rrf_merge → keyword_rerank → [llm_rerank]

# 增强 pipeline:
# dense_recall → bm25_search → graph_expand → rrf_merge(三路) → 
#   multidim_rerank(confidence + freshness + keyword + length) → [llm_rerank]

def rrf_merge_three(dense, bm25, graph, k=60):
    """三路 RRF: Dense + BM25 + Graph"""
    # Dense: 语义相似度
    # BM25: 关键词匹配
    # Graph: 关系图谱邻域
```

**难度**: ⭐⭐（中等，需要 Graph 路实现 + RRF 三路融合）

---

#### 概念 7: Quality Gates（质量门禁）

**V2 定义**: 知识从 raw → crystallized 的每个阶段都应有自动校验。

**kb2-web 现状**: 
- `assess_quality()`: 上传时评估文本字符质量
- `logic_validate()`: 查询后检查答案-来源一致性
- `_verify_searchable()`: 上传后异步验证可检索性
- 无自动 review pipeline

**落地方案**:

```python
# === 上传时 Quality Gate ===
class UploadQualityGate:
    """上传文档的多阶段质量检查"""
    
    def gate_1_text_quality(self, text) -> QualityResult:
        """现有 assess_quality"""
        
    def gate_2_content_freshness(self, title, text, bank) -> QualityResult:
        """检查是否与已有文档重复/矛盾"""
        
    def gate_3_cross_reference(self, text) -> QualityResult:
        """检查引用的标准号是否真实存在"""
        
    def gate_4_structural_completeness(self, text, profile) -> QualityResult:
        """检查文档结构完整性（有无标题、目录等）"""

# === 查询时 Quality Gate ===
class QueryQualityGate:
    """查询结果的质量门禁"""
    
    def gate_answer_source_alignment(self, answer, sources) -> QualityResult:
        """现有 logic_validate"""
        
    def gate_confidence_check(self, sources) -> QualityResult:
        """检查引用来源的 confidence 水平"""
        
    def gate_staleness_check(self, sources) -> QualityResult:
        """检查引用来源是否过时"""
```

**难度**: ⭐⭐（中等，框架设计 + 规则实现）

---

#### 概念 8: Crystallization（结晶化）

**V2 定义**: 从多个原始观察中提炼出精炼的、高置信度的知识条目。类似从笔记到教科书的转化。

**kb2-web 现状**: 无此能力。chunks 保持原始状态，不会被合并或精炼。

**落地方案**:

```python
# 新增表：crystallized_knowledge
CREATE TABLE crystallized_knowledge (
    crystal_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,                    -- 主题
    content TEXT NOT NULL,                  -- 精炼后的内容
    source_doc_ids TEXT,                    -- JSON array of source doc_ids
    confidence REAL DEFAULT 0.5,
    version INTEGER DEFAULT 1,
    created_at DATETIME,
    updated_at DATETIME
);

# Crystallization Pipeline:
# 1. 检测主题聚类：多个文档讨论同一主题
# 2. LLM 综合：把多个 chunk 综合成一个精炼条目
# 3. 人工审核：用户确认/修改
# 4. 替换检索：查询时优先返回 crystallized 条目

# 示例：
# 输入：5 个关于"等保测评流程"的不同文档片段
# 输出：1 个结构化的等保测评流程精炼知识条目，带 citation
```

**用户需求关联**: 这直接服务于"组合生成"需求 —— crystallization 是离线版的 synthesize。

**难度**: ⭐⭐⭐（复杂，需要聚类 + LLM 综合 + 审核 UI）

---

#### 概念 9: YAML Frontmatter（结构化元数据）

**V2 定义**: 每个知识文件都应有 YAML frontmatter，包含结构化元数据。

**kb2-web 现状**: 无结构化元数据。上传时只提取 title/category/bank，chunk 时只保留 heading + text。

**落地方案**: 详见第三节 OKF 集成分析。

**难度**: ⭐⭐（中等，需要上传流程 + chunking 流程改造）

---

## 三、OKF 对 kb2-web 内容结构的提升分析

### 3.1 OKF 核心概念与 kb2-web 的映射

| OKF 概念 | 定义 | kb2-web 对应 | 改进方向 |
|----------|------|-------------|---------|
| **Knowledge Bundle** | 知识的分发单元（目录树） | bank（知识库分类） | bank → OKF Bundle，支持跨 bank 知识分发 |
| **Concept** | 单个知识条目（markdown 文件） | document（一条上传文档） | document → Concept，增加 concept_id |
| **Concept ID** | 文件路径去掉 .md 后缀 | doc_id（UUID） | 引入语义化 concept_id（如 `tech/redis-caching`） |
| **Frontmatter** | YAML 元数据块 | 无 | 新增 frontmatter 解析和存储 |
| **Link** | markdown 链接表达关系 | 无 | 在 frontmatter 中声明 related_concepts |
| **Citation** | 引用外部源 | 无 | 新增 citation 追溯能力 |

### 3.2 OKF Frontmatter 集成方案

**目标**: 上传文档时，如果包含 YAML frontmatter，解析并存储；如果没有，自动生成。

```yaml
---
concept_id: standards/gb-t-22239-2019
version: "2019"
status: active
confidence: 0.9
tags: [等保, 网络安全, GB标准]
sources:
  - type: standard
    identifier: "GB/T 22239-2019"
    title: "信息安全技术 网络安全等级保护基本要求"
related_concepts:
  - standards/gb-t-25070-2019
  - standards/gb-t-28448-2019
citations:
  - url: "https://openstd.samr.gov.cn/"
    title: "国家标准全文公开系统"
superseded_by: null
created_at: "2024-01-15"
last_confirmed_at: "2024-06-01"
---

# GB/T 22239-2019 网络安全等级保护基本要求

## 1 范围
本标准规定了网络安全等级保护的基本要求...
```

### 3.3 OKF 集成对 kb2-web 的具体改进

#### 改进 1: 上传流程增强

```python
# 现有流程:
# file → parse_document → text → profile_document → heading_chunk → upsert

# OKF 增强流程:
# file → parse_document → text → parse_frontmatter(text)
#    → extract_metadata(frontmatter, inferred)
#    → profile_document → heading_chunk(保留 frontmatter)
#    → upsert(with concept_id, version, tags, sources)
```

**关键变更**:
- `parsing.py` 增加 frontmatter 解析
- `chunking.py` 的 `Chunk` dataclass 增加 `concept_id`、`source_doc_id`、`tags` 字段
- `document_repo.py` 的 `save()` 方法接受新参数
- Hindsight upsert 时 tags 中加入 `concept_id:xxx`、`version:xxx`、`confidence:xxx`

#### 改进 2: Chunk 元数据继承

```python
@dataclass
class Chunk:
    text: str
    index: int
    heading: str = ""
    parent_idx: Optional[int] = None
    metadata: dict = field(default_factory=dict)
    # === 新增 ===
    concept_id: str = ""           # 从 frontmatter 或自动生成
    source_doc_id: str = ""        # 来源文档 ID
    source_title: str = ""         # 来源文档标题
    tags: list = field(default_factory=list)  # 从 frontmatter tags 继承
    confidence: float = 0.5        # 从文档级 confidence 继承
```

#### 改进 3: 检索时按 concept_id 聚合

```python
# 新增功能：提取特定主题的所有相关内容
async def extract_by_concept(concept_id: str, bank: str = "all") -> dict:
    """
    按 concept_id 聚合提取：
    1. 搜索所有 tagged with concept_id 的 chunks
    2. 按 parent_idx 重组为完整段落
    3. 按 confidence 排序
    4. 返回结构化知识条目（非碎片）
    """

# 新增功能：按 tag 聚合
async def extract_by_tag(tag: str, bank: str = "all") -> dict:
    """
    按 tag 聚合提取：
    1. BM25 + Dense 检索
    2. 过滤匹配 tag 的结果
    3. 按文档聚合
    4. 返回每个文档的完整相关段落
    """
```

---

## 四、用户需求的三步实现方案

### 4.1 提取（Extract）

**用户需求**: "从知识库中提取特定主题的所有相关内容"

**现状分析**:
- `/api/query` 返回 top-K 片段，是碎片化的
- 按 bank 过滤是唯一的"范围控制"
- 无法按概念/主题/标签聚合

**实现方案**:

```python
# === 新增 API: POST /api/extract ===

@router.post("")
async def extract(
    topic: str = Form(...),           # 主题/概念
    bank: str = Form("all"),
    format: str = Form("structured"), # structured | markdown | json
    include_stale: bool = Form(False),
    min_confidence: float = Form(0.0),
):
    """
    提取特定主题的所有相关内容。
    
    与 /api/query 的区别：
    - query: 返回 top-K 片段，适合快速问答
    - extract: 返回完整知识条目，适合深度研究
    
    流程：
    1. 多路检索（BM25 + Dense + Graph）
    2. 按 concept_id / document 聚合
    3. 过滤 (stale, confidence)
    4. 按 confidence + relevance 排序
    5. 组装为结构化输出
    """
    
    # Step 1: 检索（复用现有 pipeline，top_k 放大到 50）
    search_results = await _build_search_context(
        q=topic, bank=bank, top_k=50, ...
    )
    
    # Step 2: 按 document 聚合
    doc_groups = defaultdict(list)
    for result in search_results["all_results"]:
        doc_id = _extract_doc_id(result)
        doc_groups[doc_id].append(result)
    
    # Step 3: 过滤
    if not include_stale:
        doc_groups = {k: v for k, v in doc_groups.items() 
                      if not _is_stale(k)}
    if min_confidence > 0:
        doc_groups = {k: v for k, v in doc_groups.items()
                      if _get_confidence(k) >= min_confidence}
    
    # Step 4: 排序
    ranked = sorted(doc_groups.items(), 
                    key=lambda x: _extract_score(x), reverse=True)
    
    # Step 5: 组装输出
    extracted = []
    for doc_id, chunks in ranked:
        extracted.append({
            "doc_id": doc_id,
            "title": _get_title(doc_id),
            "confidence": _get_confidence(doc_id),
            "chunks": [_format_chunk(c) for c in chunks],
            "total_chars": sum(len(c.get("text", "")) for c in chunks),
            "sources": _get_citations(doc_id),
        })
    
    return {
        "topic": topic,
        "total_documents": len(extracted),
        "total_chunks": sum(len(e["chunks"]) for e in extracted),
        "results": extracted,
    }
```

**前端交互**: 在 QueryView 旁边新增"深度提取"模式开关，切换后调用 `/api/extract`。

---

### 4.2 重排（Rerank）

**用户需求**: "按相关性/置信度/时效性重新排序"

**现状分析**:
- `keyword_rerank`: 基于词面覆盖、密度、标题匹配、长度、RRF先验
- `llm_rerank`: LLM 语义判断相关性（可选，需 LLM 调用）
- 无 confidence/freshness/source_count 维度

**实现方案**:

```python
# === 多维度重排 ===

def multidim_rerank(
    results: list,
    query_keywords: list,
    weights: dict = None,
) -> list:
    """
    多维度重排：相关性 + 置信度 + 时效性 + 来源丰富度
    
    weights 默认值：
    {
        "relevance": 0.40,    # 原 keyword_rerank 得分
        "confidence": 0.25,   # 文档 confidence
        "freshness": 0.20,    # last_confirmed_at 距今
        "source_diversity": 0.15  # 来自不同文档的 chunk 多样性
    }
    """
    if weights is None:
        weights = {"relevance": 0.40, "confidence": 0.25, 
                   "freshness": 0.20, "source_diversity": 0.15}
    
    scored = []
    for item in results:
        # 维度 1: 相关性（现有 keyword_rerank 得分）
        relevance = _keyword_relevance_score(item, query_keywords)
        
        # 维度 2: 置信度
        doc_confidence = _get_doc_confidence(item)
        
        # 维度 3: 时效性
        freshness = _compute_freshness(item)
        
        # 维度 4: 来源丰富度（后续计算）
        source_diversity = 1.0  # 占位，聚合后调整
        
        combined = (
            weights["relevance"] * relevance +
            weights["confidence"] * doc_confidence +
            weights["freshness"] * freshness +
            weights["source_diversity"] * source_diversity
        )
        scored.append((combined, item))
    
    # 聚合后调整 source_diversity
    # 确保 top-K 结果来自不同文档
    final = _diversify_by_doc(scored, top_k=10)
    
    return final


def _compute_freshness(item: dict) -> float:
    """
    时效性评分：
    - 7天内确认: 1.0
    - 30天内: 0.8
    - 90天内: 0.6
    - 180天内: 0.4
    - 超过180天: 0.2
    """
    doc_id = _extract_doc_id(item)
    last_confirmed = _get_last_confirmed(doc_id)
    if not last_confirmed:
        return 0.3  # 无确认记录，给中等分
    
    days = (datetime.now(timezone.utc) - last_confirmed).days
    if days <= 7: return 1.0
    if days <= 30: return 0.8
    if days <= 90: return 0.6
    if days <= 180: return 0.4
    return 0.2
```

**API 变更**: `/api/query` 的 rerank 参数扩展：

```python
@router.post("")
async def query(
    q: str = Form(...),
    bank: str = Form("all"),
    rerank: bool = Form(False),
    # === 新增 ===
    rerank_mode: str = Form("keyword"),  # keyword | multidim | llm
    # multidim 模式下可调权重
    weight_confidence: float = Form(0.25),
    weight_freshness: float = Form(0.20),
):
```

---

### 4.3 组合生成（Synthesize）

**用户需求**: "把多个来源的内容组合成结构化输出（报告/方案/分析）"

**现状分析**:
- `/api/query` 的 `_generate_answer()` 是单轮问答，输入是拼接的 context_parts
- 无多源引用追踪、无结构化输出格式

**实现方案**:

```python
# === 新增 API: POST /api/synthesize ===

@router.post("")
async def synthesize(
    topic: str = Form(...),
    bank: str = Form("all"),
    output_format: str = Form("report"),  # report | comparison | summary | analysis
    max_sources: int = Form(10),
    include_citations: bool = Form(True),
):
    """
    从多个来源组合生成结构化输出。
    
    与 /api/query 的区别：
    - query: 基于检索结果生成答案（单次 LLM 调用）
    - synthesize: 提取多源 → 组织结构 → 生成带引用的综合输出
    
    支持的输出格式：
    - report: 结构化报告（引言-主体-结论）
    - comparison: 多源对比分析
    - summary: 多源综合摘要
    - analysis: 深度分析报告
    """
    
    # Step 1: 提取多源内容
    extracted = await _extract_for_synthesis(topic, bank, max_sources)
    
    # Step 2: 组织结构
    structured_input = _organize_sources(extracted, output_format)
    
    # Step 3: 生成带引用的综合输出
    prompt = _build_synthesis_prompt(topic, structured_input, output_format)
    answer = await chat(messages=[{"role": "user", "content": prompt}])
    
    # Step 4: 提取并验证引用
    citations = _extract_citations_from_answer(answer, extracted)
    citation_valid = _validate_citations(answer, citations)
    
    return {
        "topic": topic,
        "format": output_format,
        "answer": answer,
        "citations": citations,
        "citation_valid": citation_valid,
        "source_count": len(extracted),
        "sources": [{"doc_id": s["doc_id"], "title": s["title"], 
                     "confidence": s["confidence"]} for s in extracted],
    }


def _build_synthesis_prompt(topic, structured_input, output_format):
    """构建组合生成的 prompt"""
    
    format_instructions = {
        "report": """
请根据以下多源信息，生成一份关于"{topic}"的结构化报告。
要求：
1. 引言：概述主题背景
2. 主体：综合各来源信息，分要点阐述
3. 结论：总结关键发现
每段落标注来源 [来源X]，确保信息有据可查。
""",
        "comparison": """
请根据以下多源信息，对"{topic}"进行对比分析。
要求：
1. 列出各来源的主要观点/内容
2. 指出共识点和分歧点
3. 给出综合判断
每个观点标注来源 [来源X]。
""",
        "summary": """
请根据以下多源信息，生成关于"{topic}"的综合摘要。
要求：
1. 提炼核心要点（不超过5点）
2. 合并重复信息
3. 保留关键数据和引用
""",
        "analysis": """
请根据以下多源信息，对"{topic}"进行深度分析。
要求：
1. 现状梳理
2. 问题识别
3. 趋势判断
4. 建议方案
每个论点标注来源 [来源X]，区分事实与推理。
""",
    }
    
    instruction = format_instructions.get(output_format, format_instructions["report"])
    
    sources_text = "\n\n".join([
        f"[来源{i+1}] {s['title']} (置信度: {s['confidence']:.0%})\n{s['content']}"
        for i, s in enumerate(structured_input["sources"])
    ])
    
    return f"""{instruction}

=== 多源信息 ===
{sources_text}
"""


def _extract_citations_from_answer(answer: str, sources: list) -> list:
    """从生成的答案中提取引用标记并映射到源文档"""
    citations = []
    for match in re.finditer(r'\[来源(\d+)\]', answer):
        idx = int(match.group(1)) - 1
        if 0 <= idx < len(sources):
            citations.append({
                "marker": match.group(0),
                "doc_id": sources[idx]["doc_id"],
                "title": sources[idx]["title"],
            })
    return citations
```

**前端交互**: 新增 SynthesizeView.vue：

```
┌─────────────────────────────────────────────────┐
│  知识合成                                        │
│                                                   │
│  主题: [________________________]                 │
│  知识库: [全部知识库 ▼]                            │
│  输出格式: (●)报告 (○)对比 (○)摘要 (○)分析        │
│  最多引用: [10] 篇文档                            │
│                                                   │
│  [生成综合报告]                                    │
│                                                   │
│  ┌─────────────────────────────────────────┐     │
│  │ ## GB/T 22239-2019 等保测评综合报告       │     │
│  │                                          │     │
│  │ ### 引言                                 │     │
│  │ 网络安全等级保护制度... [来源1]            │     │
│  │                                          │     │
│  │ ### 主体                                 │     │
│  │ 1. 基本要求：... [来源1][来源3]           │     │
│  │ 2. 测评流程：... [来源2]                  │     │
│  │                                          │     │
│  │ ### 结论                                 │     │
│  │ 综合分析表明...                           │     │
│  └─────────────────────────────────────────┘     │
│                                                   │
│  📋 引用来源:                                     │
│  [1] GB/T 22239-2019 基本要求 (置信度 92%)       │
│  [2] 等保测评操作指南 (置信度 85%)                │
│  [3] 等保2.0解读 (置信度 78%)                    │
│                                                   │
│  ✅ 引用验证: 全部引用有效                        │
└─────────────────────────────────────────────────┘
```

---

## 五、具体技术方案

### 5.1 数据库 Schema 变更

```sql
-- === documents 表新增字段 ===
ALTER TABLE documents ADD COLUMN confidence REAL DEFAULT 0.5;
ALTER TABLE documents ADD COLUMN source_count INTEGER DEFAULT 1;
ALTER TABLE documents ADD COLUMN last_confirmed_at DATETIME;
ALTER TABLE documents ADD COLUMN access_count INTEGER DEFAULT 0;
ALTER TABLE documents ADD COLUMN is_superseded INTEGER DEFAULT 0;
ALTER TABLE documents ADD COLUMN superseded_by TEXT;
ALTER TABLE documents ADD COLUMN status TEXT DEFAULT 'active';
-- status: active | stale | review_required | archived
ALTER TABLE documents ADD COLUMN concept_id TEXT DEFAULT '';
ALTER TABLE documents ADD COLUMN version TEXT DEFAULT '1';
ALTER TABLE documents ADD COLUMN tags TEXT DEFAULT '[]';
-- JSON array of tags
ALTER TABLE documents ADD COLUMN sources_json TEXT DEFAULT '[]';
-- JSON array of citation sources
ALTER TABLE documents ADD COLUMN related_concepts TEXT DEFAULT '[]';
-- JSON array of related concept_ids
ALTER TABLE documents ADD COLUMN frontmatter_json TEXT DEFAULT '{}';
-- 完整 frontmatter 存储

-- === 新增表：knowledge_edges ===
CREATE TABLE IF NOT EXISTS knowledge_edges (
    edge_id TEXT PRIMARY KEY,
    source_doc_id TEXT NOT NULL,
    target_doc_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    -- related | depends_on | supersedes | contradicts | refines | cites
    weight REAL DEFAULT 1.0,
    created_by TEXT DEFAULT 'system',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_doc_id) REFERENCES documents(doc_id),
    FOREIGN KEY (target_doc_id) REFERENCES documents(doc_id)
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON knowledge_edges(source_doc_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON knowledge_edges(target_doc_id);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON knowledge_edges(relation);

-- === 新增表：crystallized_knowledge ===
CREATE TABLE IF NOT EXISTS crystallized_knowledge (
    crystal_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    content TEXT NOT NULL,
    source_doc_ids TEXT DEFAULT '[]',
    confidence REAL DEFAULT 0.5,
    version INTEGER DEFAULT 1,
    status TEXT DEFAULT 'draft',
    -- draft | review | published | archived
    created_by TEXT DEFAULT 'system',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- === 新增表：knowledge_audit_log ===
CREATE TABLE IF NOT EXISTS knowledge_audit_log (
    log_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    action TEXT NOT NULL,
    -- created | updated | superseded | stale_detected | crystallized | reviewed
    detail TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);
```

### 5.2 新增 API 端点设计

```python
# === backend/app/api/extract.py ===
# POST /api/extract — 提取特定主题的所有相关内容
# GET  /api/extract/concept/{concept_id} — 按 concept_id 获取完整知识条目
# GET  /api/extract/tag/{tag} — 按 tag 聚合提取

# === backend/app/api/synthesize.py ===
# POST /api/synthesize — 组合多源生成结构化输出
# POST /api/synthesize/preview — 预览将要使用的源文档

# === backend/app/api/knowledge_graph.py ===
# GET  /api/graph/{doc_id} — 获取文档的关系图谱
# POST /api/graph/edges — 添加关系
# GET  /api/graph/neighbors/{doc_id} — 获取邻域文档

# === backend/app/api/lifecycle.py ===
# POST /api/lifecycle/confirm/{doc_id} — 确认文档仍有效
# POST /api/lifecycle/supersede — 标记旧文档被取代
# GET  /api/lifecycle/stale — 获取过时文档列表
# POST /api/lifecycle/review/{doc_id} — 标记为待审

# === backend/app/api/crystallize.py ===
# POST /api/crystallize — 触发结晶化（多 chunk → 精炼条目）
# GET  /api/crystallize — 获取已结晶的知识条目列表
# POST /api/crystallize/{crystal_id}/approve — 审核通过
```

### 5.3 Chunking 改进

```python
# === parsing.py 新增 frontmatter 解析 ===

import yaml

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """
    解析 YAML frontmatter + 正文。
    返回 (frontmatter_dict, body_text)
    
    兼容：
    1. 用户上传的带 frontmatter 的 markdown
    2. 无 frontmatter 的纯文本（返回空 dict）
    """
    if not text.startswith("---"):
        return {}, text
    
    # 找到第二个 ---
    end_idx = text.find("---", 3)
    if end_idx == -1:
        return {}, text
    
    frontmatter_str = text[3:end_idx].strip()
    body = text[end_idx + 3:].strip()
    
    try:
        frontmatter = yaml.safe_load(frontmatter_str) or {}
    except yaml.YAMLError:
        frontmatter = {}
    
    return frontmatter, body


def infer_concept_id(title: str, category: str, bank: str) -> str:
    """
    从标题/分类推断 concept_id。
    示例：
    - "GB/T 22239-2019 网络安全等级保护基本要求" 
      → "standards/gb-t-22239-2019"
    - "Redis缓存设计最佳实践"
      → "tech/redis-caching-best-practices"
    """
    # 标准号提取
    std_match = re.search(r'(GB|ISO|T/EGAG)\s*/?\s*T?\s*(\d+[\-\.]\d+)', title)
    if std_match:
        std_type = std_match.group(1).lower().replace("/", "-")
        std_num = std_match.group(2).replace(".", "-")
        return f"{bank}/{std_type}-{std_num}"
    
    # 通用标题 → slug
    slug = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]+', '-', title.lower()).strip('-')[:60]
    return f"{bank}/{slug}"
```

### 5.4 检索 Pipeline 改进

```python
# === retrieval.py 增强 ===

async def enhanced_recall(
    q: str,
    bank: str,
    top_k: int = 20,
    use_graph: bool = False,     # 新增：是否启用图谱扩展
    use_multidim: bool = False,  # 新增：是否启用多维重排
    min_confidence: float = 0.0, # 新增：最低置信度过滤
    include_stale: bool = False, # 新增：是否包含过时内容
) -> dict:
    """
    增强检索 pipeline:
    1. Dense recall (Hindsight)
    2. BM25 search
    3. [可选] Graph expand
    4. RRF merge (三路)
    5. [可选] Multidim rerank
    6. [可选] LLM rerank
    7. 过滤 (stale, confidence)
    """
    
    # Step 1-2: 复用现有
    dense_results = await recall(q, bank=bank, limit=top_k * 2)
    bm25_results = bm25_search(q, bank=bank, top_k=top_k * 2)
    
    # Step 3: Graph expand (可选)
    graph_results = []
    if use_graph:
        # 从 dense/bm25 命中中提取 doc_ids
        hit_doc_ids = set()
        for r in dense_results:
            hit_doc_ids.add(_extract_doc_id(r))
        for r in bm25_results:
            hit_doc_ids.add(r.get("doc_id"))
        
        # 沿图谱扩展 1 距离
        graph_results = await _graph_expand(list(hit_doc_ids), depth=1)
    
    # Step 4: RRF merge
    if graph_results:
        merged = rrf_merge_three(dense_results, bm25_results, graph_results)
    else:
        merged = rrf_merge(dense_results, bm25_results)
    
    # Step 5: Multidim rerank (可选)
    if use_multidim:
        merged = multidim_rerank(merged, q.split())
    else:
        merged = keyword_rerank(merged, q.split())
    
    # Step 6: LLM rerank (可选)
    # ... 现有逻辑
    
    # Step 7: 过滤
    if not include_stale:
        merged = [r for r in merged if not _is_stale(_extract_doc_id(r))]
    if min_confidence > 0:
        merged = [r for r in merged 
                  if _get_doc_confidence(_extract_doc_id(r)) >= min_confidence]
    
    return {"results": merged[:top_k]}
```

### 5.5 前端交互变更

```typescript
// === 新增路由 ===
{
  path: '/extract',
  name: 'extract',
  component: () => import('@/views/ExtractView.vue'),
},
{
  path: '/synthesize',
  name: 'synthesize', 
  component: () => import('@/views/SynthesizeView.vue'),
},
{
  path: '/graph',
  name: 'graph',
  component: () => import('@/views/GraphView.vue'),
},
{
  path: '/lifecycle',
  name: 'lifecycle',
  component: () => import('@/views/LifecycleView.vue'),
},

// === QueryView.vue 增强 ===
// 新增模式切换：快速查询 | 深度提取 | 知识合成
// 新增过滤器：置信度滑块、时效性过滤、过时文档开关
```

---

## 六、实施路线图

### P0 — 基础设施（Confidence + Frontmatter + 提取能力）
**目标**: 让知识有"质量意识"，支持主题提取

| 任务 | 人天 | 依赖 |
|------|------|------|
| documents 表新增 confidence/source_count/last_confirmed_at/access_count/status 字段 | 0.5 | 无 |
| confidence 自动计算 + cron job | 1.5 | 上述字段 |
| upload 流程集成 confidence 初始化 | 1 | confidence 计算 |
| OKF frontmatter 解析 (parse_frontmatter) | 1 | 无 |
| upload 流程支持 frontmatter 元数据提取和存储 | 1.5 | frontmatter 解析 |
| concept_id 推断逻辑 (infer_concept_id) | 1 | frontmatter 解析 |
| chunking 改进：Chunk 增加 concept_id/source_doc_id/tags 字段 | 1 | concept_id 推断 |
| Hindsight upsert 增加新 tags (concept_id/confidence/version) | 0.5 | chunking 改进 |
| POST /api/extract 端点 | 2 | 上述全部 |
| ExtractView.vue 前端页面 | 2 | /api/extract |
| **小计** | **12 人天** | |

### P1 — 生命周期管理（Superseded + Stale + 多维重排 + Quality Gates）
**目标**: 知识有"生命周期"，检索有"多维度"

| 任务 | 人天 | 依赖 |
|------|------|------|
| knowledge_versions 表 + superseded 逻辑 | 2 | P0 |
| stale/review_required 自动检测 cron job | 1.5 | P0 |
| upload 流程支持版本对比和 supersede | 1.5 | P0 |
| multidim_rerank 多维重排实现 | 2 | P0 |
| /api/query 扩展 rerank_mode 参数 | 0.5 | multidim_rerank |
| UploadQualityGate 上传质量门禁扩展 | 2 | P0 |
| GET /api/lifecycle/stale 端点 | 0.5 | stale 检测 |
| POST /api/lifecycle/confirm/{doc_id} 端点 | 0.5 | P0 |
| LifecycleView.vue 前端页面 | 1.5 | lifecycle API |
| QueryView.vue 增加多维重排选项 | 0.5 | multidim_rerank |
| **小计** | **13.5 人天** | |

### P2 — 知识图谱 + 组合生成（Graph + Synthesize）
**目标**: 知识有"关系"，输出有"结构"

| 任务 | 人天 | 依赖 |
|------|------|------|
| knowledge_edges 表 + CRUD API | 2 | P0 |
| 自动关系生成（标题相似/共享引用/superseded） | 2 | P1 |
| LLM 批量分析文档关系 | 1.5 | P0 |
| graph_expand 邻域检索实现 | 2 | knowledge_edges |
| 三路 RRF 融合 (dense + bm25 + graph) | 1 | graph_expand |
| POST /api/synthesize 端点 | 2.5 | extract + generation |
| SynthesizeView.vue 前端页面 | 2 | /api/synthesize |
| GET /api/graph/{doc_id} + GraphView.vue | 2 | knowledge_edges |
| **小计** | **15 人天** | |

### P3 — 结晶化 + 高级功能（Crystallization + 完整闭环）
**目标**: 知识自动"沉淀"，形成完整闭环

| 任务 | 人天 | 依赖 |
|------|------|------|
| crystallized_knowledge 表 | 0.5 | P0 |
| Crystallization pipeline（主题聚类 + LLM 综合） | 3 | P2 |
| 结晶化审核 UI (approve/reject/edit) | 2 | crystallized |
| 检索优先返回 crystallized 条目 | 1 | crystallized |
| knowledge_audit_log 审计日志 | 1 | P0 |
| Ebbinghaus 遗忘曲线实现（access_count 衰减） | 1.5 | P0 |
| 知识库健康仪表盘（confidence 分布、过时率、结晶率） | 2 | 全部 |
| 批量操作 API（批量确认/批量 supersede/批量 review） | 1 | P1 |
| **小计** | **12 人天** | |

### 总计

| 阶段 | 人天 | 核心交付 |
|------|------|---------|
| P0 | 12 | Confidence + Frontmatter + Extract |
| P1 | 13.5 | 生命周期 + 多维重排 + Quality Gates |
| P2 | 15 | 知识图谱 + 组合生成 |
| P3 | 12 | 结晶化 + 闭环 |
| **总计** | **52.5 人天** | |

---

## 七、工程控制论视角的系统设计原则

用户的偏好是工程控制论视角（系统整体性、闭环反馈、层级拆解、可观测可调控）。以下是落地这些原则的具体措施：

### 7.1 闭环反馈（Closed-Loop Feedback）

```
上传 → 质量门禁 → 存储 → 检索 → 用户反馈 → 质量更新
  ↑                                              │
  └──────────── 定期 review cron ←───────────────┘

具体实现：
1. 查询命中 → access_count++ → 影响 confidence
2. 用户反馈"有用" → last_confirmed_at 更新
3. 矛盾检测 → 标记 review_required
4. 定期 cron → 重新计算 confidence + 检测 stale
5. stale 文档 → 触发人工 review → supersede/confirm/archive
```

### 7.2 可观测可调控（Observable & Tunable）

```
可观测：
- knowledge_audit_log 记录所有变更
- confidence 分布仪表盘
- stale 文档占比监控
- 检索质量指标（查询命中率、用户满意度）

可调控：
- confidence 计算公式参数可配置
- multidim_rerank 权重可调（前端 slider）
- stale 检测阈值可调
- quality gate 规则可开关
```

### 7.3 层级拆解（Hierarchical Decomposition）

```
Level 0: 原始文档 (Document)
  └─ Level 1: Chunks (heading-based, 带元数据)
       └─ Level 2: Knowledge Edges (关系)
            └─ Level 3: Crystallized Knowledge (精炼)

每层都有独立的 confidence 计算和生命周期管理。
```

### 7.4 系统整体性（Systemic Integrity）

```
数据一致性：
- superseded_by 字段形成版本链，可追溯
- confidence 由多个因素综合计算，不依赖单一信号
- knowledge_edges 连接独立文档，形成整体

向后兼容：
- 所有新增字段都有默认值，不影响现有功能
- OKF frontmatter 是可选的，纯文本文档仍正常处理
- 新 API 端点独立，不修改现有 /api/query 行为
```

---

## 八、风险与缓解措施

| 风险 | 影响 | 缓解 |
|------|------|------|
| confidence 计算不准确 | 错误过滤有用内容 | 提供手动 override 机制 |
| frontmatter 解析失败 | 上传中断 | 优雅降级：解析失败则跳过 frontmatter |
| 图谱构建质量低 | 检索引入噪音 | 先小范围验证，逐步扩展 |
| crystallization LLM 幻觉 | 生成错误知识 | 人工审核门禁，draft 状态不参与检索 |
| SQLite schema 变更 | 现有数据丢失 | Alembic migration，备份先行 |
| 性能下降 | 查询延迟增加 | 图谱扩展异步执行，缓存 confidence |

---

## 九、总结

LLM Wiki V2 的 9 个概念和 OKF 格式为 kb2-web 提供了一个完整的知识管理升级框架：

1. **Confidence + Last Confirmed** → 让知识有"可信度"，不再是等权的碎片集合
2. **Superseded + Stale** → 让知识有"生命周期"，过时内容自动降权
3. **Knowledge Graph** → 让知识有"关系"，检索不再孤立
4. **Hybrid Retrieval** → 多路融合 + 多维重排，检索更精准
5. **Quality Gates** → 自动质量门禁，从上传到查询全程把控
6. **Crystallization** → 多源知识自动沉淀，从碎片到体系
7. **YAML Frontmatter (OKF)** → 结构化元数据，让知识自描述

三步实现路径（Extract → Rerank → Synthesize）直接对应用户的三步需求（提取 → 重排 → 组合生成），52.5 人天的实施计划覆盖从基础到高级的完整升级路径。
