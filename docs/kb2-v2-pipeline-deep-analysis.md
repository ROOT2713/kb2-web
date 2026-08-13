# kb2-web 知识库 v2 完整管线深度分析报告

> **版本**: v2（当前运行版本）
> **后端**: 17,265 行 Python（FastAPI + SQLAlchemy）
> **前端**: 5,780 行 Vue3（18 个组件/页面视图）
> **核心文件**: 60+ Python 文件，分布于 `api/`、`services/`、`models/`、`utils/`、`repositories/`
> **报告日期**: 2026-07-25

---

## 一、完整管线逐层拆解

### 1.1 上传与文档解析（Upload & Parsing）

#### 前端上传（UploadView.vue — 889行）

前端上传模块提供完整的拖拽上传 + 目录批量上传体验：

- **webkitdirectory 批量上传**：支持用户直接选择整个目录（文件夹），一次性扫描数千文件
- **SHA1 预检查去重**：每个文件在真正上传前，前端先计算 SHA1 哈希并与后端 `/documents/check-sha1` 接口比对，已存在则跳过
- **分 20 批上传**：当上传文件数超过 20 时，自动分批串行提交，避免服务端并发压力过大
- **删除线污染处理**：前端 `cleanSourceText()` 函数使用正则清除文本中的 `<del>...</del>` 标记

#### 后端上传（upload.py — 820行 + parsing.py — 500行）

后端解析管线采用 **优先级回退（graceful fallback）** 策略，按文档类型提供 4 种解析路径：

| 文档类型 | 主路径 | 回退路径 | 关键依赖 |
|---------|--------|---------|---------|
| **PDF** | MinerU API 解析（异步轮询 pending→running→done） | 超时 → PyPDF 回退 | `httpx` + MinerU API Key |
| **DOCX** | `python-docx` 提取 → `pypandoc` 转 Markdown | DOCX 先转 PDF（LibreOffice headless）→ MinerU 兜底 | `python-docx`, `pypandoc` |
| **Excel** | `openpyxl` 解析各 sheet | — | `openpyxl` |
| **扫描件** | `pdftoppm` + `tesseract` OCR | — | `tesseract` |

MinerU 解析流程为异步状态轮询：
1. PDF 上传 → 调用 MinerU API 创建任务（状态 `pending`）
2. 每 5 秒轮询一次，等待状态变为 `running` → `done`
3. 若总耗时超过 `MINERU_TIMEOUT`（默认 300 秒），放弃等待 → 执行 PyPDF 回退
4. 解析成功 → 清洗 HTML 残渣 → 入库

上传到解析完成全链路：
```
文件上传 → SHA1去重检查 → MinerU解析（异步轮询） → HTML残渣清洗
→ 文本质量评估(assess_quality) → 文档画像(profile_document) 
→ G1/G2/G3三级质量门禁 → 切片 → 入库 → searchable完整性验证
```

#### 完整性门禁（Searchable Integrity Gate）

解析完成后，系统执行 **searchable recall 验证**：查询刚入库文档的切片是否能被检索命中。通过验证后 `searchable=1`，否则标记为 `searchable=0`（自动修复脚本定期扫描并重试这些文档）。

---

### 1.2 切片（Chunking）

切片服务（`chunking.py` — 1019行）实现了 **标题感知的自适应父子分块** 策略，取代了传统固定窗口分块。

#### 核心参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `parent_size` | 6,000 字符 | 父块最大容量（树状结构上层） |
| `child_size` | 500 字符 | 子块最大容量（检索最小粒度） |
| `overlap` | 75 字符 | 相邻子块重叠字符数 |
| `min_child_size` | 200 字符 | 最小子块阈值（低于此值入合并缓冲区） |

#### 分块策略矩阵

| 文档类型 | 子块策略 | 父块策略 | 适用场景 |
|---------|---------|---------|---------|
| **GB 标准（gb_standard）** | 叶子标题层级（X.X.X）下内容 | 顶层标题（X）下所有子内容合并 | 技术标准（GB/T 22239 等） |
| **法规（regulation）** | 每条（第N条）为独立子块 | 3-5条为一组 | 管理办法、条例 |
| **通用（generic）** | `parent_child_chunk()` 滑动窗口 | — | 非结构化文档 |
| **Excel 表格** | 每行为一个子块 | 表格整体 | 费率表、取费表 |

#### 关键机制

1. **标题感知分块（`_heading_chunk_gb()`）**：
   - 从文档 frontmatter 中提取 `headings` 列表（包含层级、标题文本）
   - 按标题层级树遍历，叶子标题下的文本为 child，祖先标题下的文本组合为 parent
   - 支持 GB 标准的多级章节体系（"3 术语和定义" -> "3.1 信息系统"）

2. **短段落合并机制**：
   - 当 child 块字符数 < 200（`min_child_size`）时，暂入 `buf` 缓冲区
   - 与下一个 child 合并后再切片，避免微小碎片块
   - 体现为 `_heading_chunk_gb()` 中的 `short_paragraphs_buf` 逻辑

3. **句边界感知截断**：
   - 当 child 内容超出 `child_size` 时，不从句子中间截断
   - 回退到最近的中文句号（`。`）、问号、感叹号或换行符
   - 确保切片终点位于语义完整位置

4. **section_hint 链增强**：
   - 每个 chunk 附带分层标题链，如 `"3 术语和定义/3.1 信息系统"`
   - 在检索时作为结构化上下文注入，提升 LLM 对片段来源的理解

---

### 1.3 数据清洗（Cleaning）

清洗管线（`text_cleaning.py` — 311行）覆盖从 MinerU 解析残渣到最终文本的完整净化。

#### 清洗阶段

| 阶段 | 函数 | 处理内容 |
|------|------|---------|
| HTML 残渣 | `clean_html_residuals()` | 清除 MinerU 留下的 `<div>`、`<span>`、`<br/>`、`<style>`、`rowspan`/`colspan` 等标记 |
| HTML 表格转换 | `_html_table_to_pipe()` | 将 `<table>` 转换为管道符分隔的 Markdown 表格（\| 分隔符格式） |
| LaTeX 污染 | 前端 `katex` 渲染 + 后端保留 `$...$` | 公式标记 `$x^2$` 保留不变，前端 KaTeX 渲染为数学公式 |
| 删除线污染 | 前端 `cleanSourceText()` | 正则去除 `<del>...</del>` 标记 |
| 编码错误 | `clean_encoding_errors()` | 清除 U+FFFD 替换字符和控制字符 |
| 空白规范化 | `normalize_whitespace()` | 多重空格→单空格，全角/半角统一 |
| AI 味去污染 | `deai_postprocess()` | 移除 "综上所述""值得注意的是" 等 AI 味连接词（约 40+ 条规则） |
| 水印/页眉页脚 | `clean_watermarks()`, `clean_page_artifacts()` | 去除 "内部资料" "请勿外传" 等印章标记 |

#### 源文本清洗（`_clean_source_text()`）

在入库前对原始文本做一次彻底的清洗：移除空行、合并段落、修正首尾空白。

---

### 1.4 入库（Storage）

kb2-web 采用 **三层存储架构**，数据分别写入三种不同定位的数据库：

#### 三层存储对比

| 存储层 | 数据库 | 表 | 用途 | 写入时机 |
|--------|--------|-----|------|---------|
| **元数据层** | SQLite | `documents` | 文档元数据（title, bank, searchable, published_date, geo_scope, doc_type 等 12 字段） | v1 上传时填充，v2 不变 |
| **父块层** | SQLite | `parent_chunks` | 每个 parent chunk 的标题框文字，用于 BM25 全文搜索 | v1 上传时填充，v2 不填充 |
| **向量层** | pgvector | `vector_chunks` | 实际语义向量（embedding）+ 完整 chunk 文本 + metadata JSONB | v2 每次上传/切片 |

#### 数据库选型

| 数据库 | 用途 | 配置方式 |
|--------|------|---------|
| **SQLite** | 元数据 + BM25 搜索 + 审计日志 | 文件路径 `data/kb2.db`（`settings.DATABASE_URL`） |
| **pgvector** | 语义向量存储（主向量库） | 连接池配置于 `settings.PGVECTOR_URL` |
| **Hindsight** | 辅助向量搜索（第二向量库） | 独立 pgvector 连接，用于多路召回中的 hindsight 分支 |

#### Wiki 结构化知识层

额外独立的 SQLite 表 `wiki_entries` + `wiki_relations`，存储约 45 条 / 13 分类的结构化知识条目，包括：

| 分类 | 示例 | 用途 |
|------|------|------|
| `standard` | GB/T 22239 关键条款 | 标准知识 |
| `faq` | "等保三级需要哪些设备" | 常见问答 |
| `guide` | 立项咨询操作指南 | 操作指引 |
| `term` | "信息系统" 定义 | 术语解释 |

#### 缓存架构

缓存系统分为两层（`cache_service.py` — 223行）：

| 层级 | 类型 | 存储 | key 构成 | TTL |
|------|------|------|---------|-----|
| L1 | 精确匹配 | SQLite `query_cache` | `SHA256(归一化查询+bank)` | 86400s（1天） |
| L2 | 语义缓存 | SQLite + BM25 | `hash(query+bank+mode+category)` | 600s（10min，BM25索引） |

**BM25 索引管理**：
- 每个 bank 独立缓存（全量、行业、个人、项目 4 个独立 BM25 索引）
- TTL 600s，增量检测（文档数量变化时自动重建）
- 上传新文档后立即 `invalidate_bm25_cache()`

---

### 1.5 检索（Retrieval）

检索服务（`retrieval.py` — 1274行）实现了 **三路并行召回 + RRF 融合 + Rerank** 的复合检索策略。

#### 三路召回

| 召回路 | 实现方式 | 特点 |
|--------|---------|------|
| **BM25 全文搜索** | SQLite FTS5-like（使用 `rank_bm25` 库的 `BM25Okapi`） | 精确关键词匹配，对标准号、术语等精准查询有效 |
| **pgvector 语义搜索** | 异步 `async pgvector search()`，多 bank 并行 | 语义相似度搜索，参数 `symmetric=True` 或 `query_embedding` |
| **Hindsight 向量搜索** | 第二 pgvector 连接独立搜索 | 辅助向量库，用于覆盖主库遗漏的尾部命中 |

#### 多 Bank 并行召回

系统支持 4 个 Bank 配置（`_HARDCODED_BANKS`）：

| Bank | 对应 hindsight_banks | 领域描述 |
|------|---------------------|---------|
| `all` | 9 个库全搜 | 通用政务信息化知识库 |
| `industry` | 6 个标准/行业库 | 等保测评、密码应用、监理服务等 |
| `personal` | `kb_咨询`, `kb_xhs` | 互联网产品评测、AI 工具 |
| `project` | `kb_project` | 项目管理、验收管理 |

多 bank 并行调用时，各自搜索后结果合并。

#### RRF 融合（`rrf_merge()`）

Reciprocal Rank Fusion 算法，公式：
```
score(d) = Σ(1 / (k + rank_i(d)))
```
其中 `k=60`（默认参数），对各路召回结果做等权融合排序。

#### Rerank 模式

系统提供 **4 种 Rerank 模式**（`rerank.py` — 296行 + 逻辑分布于 retrieval.py）：

| 模式 | 权重配置 | 说明 |
|------|---------|------|
| `cross_encoder` | — | 交叉编码器重排（调用外部 reranker API） |
| `multidim` | keyword=0.43, dense=0.43, confidence=0.025, freshness=0.015, source_count=0.01, chunk_position=0.10 | 多维信号加权排序 |
| `confidence` | — | 基于文档置信度分排序 |
| `freshness` | 半衰期 365 天 | 时效性优先（新文档排名上升） |

#### 标准号 Boost（standard_boost.py — 267行）

当用户查询中包含精确标准号（如 `GB/T 22239`、`JJF 1059.1`）时，触发 **Phase C1 增强**：

1. 用 `_STD_PATTERN` 正则从查询中提取标准号
2. 在 DB 中以 `title LIKE '%GB/T 22239%'` 精确匹配文档
3. 将匹配文档的 parent_chunks 直接注入 `doc_facts`，确保在 top-5 上下文中
4. 有效解决语义检索将标准号文档排在尾部导致的 recall=0 问题

支持的标准号模式：GB/T、ISO/IEC、YD/T、SJ/T、GA/T、JJF、JJG、T/EGAG、GDZW、DB 系列、国函/国令等。

#### 同义词扩展（`expand_query_synonyms()`）

对费用类查询，使用预定义 `_FEE_SYNONYMS` 词表扩展查询词。如 "监理费" 扩展为 `[监理费, 监理费用, 监理收费]`，实质上是多路 OR 查询。

---

### 1.6 召回增强（Recall Enhancement）

#### D2-B 费用类专用管道（fee_utils.py — 372行）

费用取费表是政务信息化领域的特有需求，普通 RAG 检索难以命中。kb2-web 为此实现 **D2-B 费用专线**：

```
用户查询（含费用关键词）
  → title LIKE '%费用%' 精确匹配文档
  → 关键词打分（32个费用关键词，如"费率""计费额""收费基价"）
  → 两阶段公平分发（每文档至少 1 个 chunk，其余按 relevance 分配）
  → 费用类型互斥（等保 ≠ 验收测评，互斥类型不混合）
  → Hindsight recall fallback 补充不足的 chunks
```

**公平分发两阶段**：
1. 第一阶段：每个匹配文档至少分到 1 个 chunk（保证覆盖度）
2. 第二阶段：剩余 budget 按 chunk relevance 评分梯度分配（`_distribute_by_relevance()`）

**费用类型互斥**：如果查询是"等保测评费用"，系统排除"验收测评"相关文档，避免 LLM 混淆费率表。

#### Wiki 结构化知识层注入（v3.1）

Wiki 条目在 **置信度门控之前** 注入 prompt（而非混入 doc_facts），作为独立的结构化块：

```
[Wiki 知识参考]
- GB/T 22239: 等级保护三级需要部署日志审计、堡垒机、数据库审计...
- 定义: "信息系统是指由计算机及其相关和配套设备..."
```

- 通过 `wiki_service.search_entries()` 按关键词 / 分类检索
- 置信度评分排序，注入前 3-5 条
- 独立于 doc_facts 块，prompt 中标记信息来源

#### 速查卡注入（Concept Summary）

`concept_summary.py` 生成文档级概念摘要（约 50-100 字），作为速查卡注入检索上下文。置信度评分排序，高置信度概念摘要优先注入。

#### 孤儿 Chunk 过滤

**关键质量门禁**：如果 chunk 的 `doc_id` 不在 `title_map` 中（即父文档已删除或不存在），该 chunk 会被主动丢弃，不出现在检索结果中。实现在 retrieval.py 的 `recall()` 函数中：
```python
if isinstance(chunk, dict) and chunk.get("doc_id") not in title_map:
    continue  # orphant chunk filter
```

---

### 1.7 检索后处理（Post-Retrieval / Confidence Gates）

#### 三级置信度门控（quality_gates.py — 395行 + confidence.py — 305行）

门控系统分为 4 个层级，逐级检查是否应正常回答：

| 门控层级 | 触发条件 | 处理结果 |
|----------|---------|---------|
| **L1** | `source_count <= 0`（检索结果为空） | 直接拒答，返回 "未找到相关信息" |
| **L1.5** | 纯引用模式（`only_ref_mode`）无实质条款 | 拒答（费用类查询跳过此检查） |
| **L2** | `coverage < 0.5` 且无精确匹配 + 无标准号 boost 命中 | 拒答，返回 "没有足够的信息回答此问题" |
| **L3（后生成）** | 生成回答后校验 score < 25% | 替代 answer，返回 "无法提供准确信息" |

**Coverage 计算**：
```
coverage = len(matched_docs) / min(10, len(all_relevant_docs))
```

**特殊规则**：
- 当查询指定了 `category` 参数时，跳过 L2 coverage 检查（有分类约束时覆盖度自然偏低）
- 费用类查询跳过 L1.5 纯引用检查
- 标准号 boost 命中的查询，即使 coverage < 0.5 也放行 L2

#### Doc Facts Query-Doc 相关度重排（H 阶段）

在 RRF 融合后，对结果进行 **Query-Document 相关度再排序**：
1. 计算每个 doc 的 chunk 命中率（该文档中有多少 chunk 被召回）
2. 按 chunk 命中率排序，优先保证高相关度文档的上下文完整
3. 每个 doc 最多截取前 3 个最高分 chunk

#### B03：库外主题领域检测

系统内置 **8 领域 56 个关键词** 的检测表，在回答前检查查询是否属于知识库覆盖范围之外的领域。命中后直接拒答，避免 LLM 幻觉。

---

### 1.8 问答生成（Q&A Generation）

#### LLM 调用链

```
query_engine.py → query.py → API 调用（DeepSeek v4 / 智谱 API）
```

#### Prompt 构建流程

1. **doc_facts 块**：检索命中的 chunk 文本 + 相关性约束指令（"仅基于以下内容回答"）
2. **wiki_context 独立块**（v3.1 新增）：结构化知识注入，不混入 doc_facts
3. **fee_rules 条件注入**：当检测到费用类查询时，追加费率表解析规则
4. **Confidence Gate 结果**：将 L1/L2/L3 门控结果作为系统消息注入
5. **历史对话**：多轮对话场景下，拼接 `session_manager.py` 维护的对话历史

#### 关键 Prompt 指令

- **相关性约束**："如果你不确定，请回答'未找到相关信息'"
- **AI 味禁止**："不要使用'综上所述''值得注意的是'等连接词"
- **引用格式**："请在答案末尾标注来源文档编号"

#### 缓存命中

查询先经过 L2 语义缓存检测：语义相似度高于阈值的已有回答直接返回，跳过 LLM 调用。`nocache` 参数可强制跳过缓存。

#### 多轮对话域锁定（session_manager.py）

- 同一个 session_id 的对话历史记录查询/回答对
- 域锁定：首次查询的 bank/领域作为后续对话的固定域，不改动

---

### 1.9 前端显示（Frontend Display）

前端共 8 个核心页面视图 + 5 个通用组件。

#### 页面视图

| 视图 | 文件 | 行数 | 功能 |
|------|------|------|------|
| QueryView | 475 | 搜索输入框 + 历史记录 + 对话模式 + Markdown 结果渲染 |
| UploadView | 889 | 拖拽上传 + 目录批量 + SHA1 去重 + 进度条 |
| DocumentsView | 494 | 文档列表 + 搜索过滤 + 翻页 |
| DocumentDetail | 345 | 文档详情 + chunk 列表 + 质量门禁状态 |
| BanksView | 207 | Bank 管理 + 切换 |
| LoginView | 152 | JWT 登录 |
| AdminView | 473 | 统计面板 + 健康检查 + 缓存管理 + 审计日志 |
| WikiView / WikiEntryView | 241 + 361 | Wiki 条目浏览 / 编辑 / 创建 |

#### 核心组件

| 组件 | 文件 | 行数 | 功能 |
|------|------|------|------|
| ResultCard | 762 | 来源卡片显示 + Markdown 渲染 + 来源编号 |
| AppHeader / AppSidebar | 78 + 115 | 导航栏 + 侧边栏 |

#### 渲染特点

- **Markdown 渲染**：使用 `markdown-it` 渲染库，支持表格、代码块、公式
- **KaTeX 渲染**：后端保留的 `$...$` LaTeX 公式在前端用 KaTeX 渲染为数学符号
- **删除线**：`<del>...</del>` 在 `cleanSourceText()` 中被去除，不展示
- **响应式**：支持桌面端 + 移动端自适应

---

### 1.10 报告与监控（Reporting & Monitoring）

#### 审计日志（query_logger.py）

- 非阻塞写入 SQLite `audit` 表
- 记录字段：query_hash, query_text, timestamp, source_type, response_time, cache_hit, answer_text
- 用于后续分析和问题追溯

#### 质量门禁（quality.py + quality_gates.py — 395行）

文档入库时执行 G1/G2/G3 三级质量检查：

| 级别 | 检查项 | 惩罚措施 |
|------|--------|---------|
| **G1（格式）** | 文件大小 > 0, 文本 > 100 字符, 编码正确 | 失败则拒绝入库 |
| **G2（完整性）** | 有标题, 有 bank, 有 doc_type, chunk > 0, concept 已生成 | 标记为低质量 |
| **G3（一致性）** | 无重复标题（同 bank 下）, 标准号格式正确, 引用关系完整 | 标记为需审查 |

#### CI 评估器（kb2_66test_v3.py）

- 66 题回归测试集，覆盖各类查询（标准查询、费用查询、拒答查询等）
- 基线准确率：66%（2026-07 数据）
- 自动化 `pytest` 运行，每次代码变更后检查准确率是否有回退

#### 健康监控

- `/admin/health` 端点：返回各服务状态（SQLite 连接、pgvector 连接、MinerU API 状态）
- `journalctl` 系统日志：systemd 管理的 uvicorn 4 workers 的日志统一采集
- 上传监控：定期扫描 `searchable=0` 的文档，自动执行修复脚本尝试重解析

#### 缓存管理

- `admin/cache/invalidate`：管理员可手动清除某 bank 或全局缓存
- 上传新文档后自动 `invalidate_bm25_cache()`
- BM25 索引 TTL 600s，过期后重建

---

## 二、与主流 RAG 方案对比

### 对比维度表

| 维度 | kb2-web | 主流方案（LangChain/LlamaIndex/Haystack） | 优劣分析 |
|------|---------|-------------------------------------------|---------|
| **框架** | 自研 FastAPI（零框架依赖） | LangChain/LlamaIndex 生态链 | ✅ 零框架锁定，极致定制自由；❌ 无生态支持，社区组件需自建 |
| **存储** | SQLite + pgvector + Hindsight 三层隔离 | 单一向量库（Chroma/Pinecone/Qdrant） | ✅ 元数据/向量/搜索分离，灵活交叉验证；❌ 运维复杂度 3x |
| **分块** | 自适应父子分块（标题感知 + 句边界 + 短段落合并） | 固定 size 分块（256/512 token） | ✅ 保留文档语义结构，减少碎片；❌ 参数多（5+），调试曲线陡峭 |
| **检索** | BM25 + 语义 + Hindsight 三路 RRF 融合 | 单一语义检索（或简单混合） | ✅ 多路召回 recall 更高（~20-30%）；❌ 延迟增加约 200ms |
| **质量门控** | 三级 L1/L1.5/L2/L3 置信度 + B03 + orphan 过滤 | 简单 score 阈值或无 | ✅ 显著降低幻觉率 / 拒答误判；❌ 4 个阈值需要精细调优 |
| **结构化知识** | Wiki 独立层（v3.1） + 速查卡注入 | Agent/GraphRAG/Neo4j | ✅ 轻量级（45 条 SQLite），运维成本极低；❌ 需手动维护条目，非自动抽取 |
| **费用类处理** | D2-B 专线管道（公平分发 + 类型互斥） | 不支持 | ✅ 政务信息化领域独有优势，竞品无法替代 |
| **文档解析** | MinerU API + 4 种 fallback + OCR 回退 | pypdf / unstructured / pdfplumber | ✅ 表格保留率 > 90%；❌ 依赖外部 API，延迟可达 60-300s |
| **缓存** | L1 精确 + L2 语义 + BM25 索引三层 | 简单 KV 缓存 | ✅ 语义命中率更高（~35%）；❌ 内存/存储占用较大 |
| **多 Bank** | 4 大类 9 子库隔离 + 并行召回 | 无此概念 | ✅ 政务多项目/多领域场景优势；❌ 增加查询复杂度 |
| **前端** | Vue3 SPA 自研（18 组件/视图） | Streamlit / Gradio / 简单嵌入 | ✅ 交互丰富，可定制性强；❌ 开发维护成本高 |
| **部署** | systemd + uvicorn 4 workers | Docker / K8s / Serverless | ✅ 中小项目运维简单；❌ 扩展性有限，百万 QPS 场景不可行 |
| **评估** | CI 66 题自动化回归（基线 66%） | RAGAS / 人工评估 | ✅ 代码变更安全网，防止回退；❌ 66 题维护成本逐步上升 |

### 架构对比示意图

```
┌─────────────────────────────────────────────────────────────┐
│                  kb2-web 完整管线（自研）                      │
├─────────┬─────────┬──────────┬─────────┬───────────────────┤
│ 上传管线 │ 切片管线 │ 检索管线  │ 生成管线 │   监控/质量管线     │
│ MinerU  │ 标题感知 │ 三路召回  │ DeepSeek│ 三级门禁           │
│ 4种回退  │ 父子分块 │ RRF融合  │ Prompt  │ CI 66题回归        │
│质量门禁  │ 句边界   │ 标准号   │ wiki注入│ 审计日志            │
│         │ section  │ boost    │ fee规则  │ 健康检查            │
│         │ hint链   │ D2-B管线  │ 缓存命中│ 缓存管理            │
└─────────┴─────────┴──────────┴─────────┴───────────────────┘

vs.

┌─────────────────────────────────────────────────────────────┐
│              主流 RAG 方案（LangChain/LlamaIndex）            │
├─────────┬─────────┬──────────┬─────────┬───────────────────┤
│ 文档加载 │ 固定窗口  │ 语义检索  │ LLM调用  │ 简单 score 过滤    │
│ Loader   │分块器    │ Vector   │ Chain   │ (或无)            │
│ (第三方) │(default) │Store     │(prompt) │                   │
│         │         │ (单一)   │ 模板化   │                   │
└─────────┴─────────┴──────────┴─────────┴───────────────────┘
```

### kb2-web 优势总结

1. **政务信息化领域深度定制**
   - 费用取费表专用检索管道（D2-B），支持公平分发和类型互斥
   - 标准号体系完整匹配（GB/T、JJF、YD/T 等 10+ 类型）
   - 等保测评 / 密码应用 / 监理服务等垂直领域专用分块策略

2. **多路召回 + 多层门控，检索质量高于通用方案**
   - 三路召回（BM25 + 语义 + Hindsight）RRF 融合，Recall 比单一语义高 ~20-30%
   - 三级置信度门控（L1/L1.5/L2/L3）显著降低幻觉率
   - B03 库外主题检测防止领域外幻觉回答

3. **血缘追踪与交叉验证**
   - SQLite + pgvector 双写入库，可交叉验证数据完整性
   - 每个 chunk 记录 parent chunk 索引，支持溯源到源文档的标题

4. **零框架锁定**
   - 管线中 60+ 个模块均可独立替换（如替换 MinerU → 其他解析器）
   - 不依赖任何 RAG 框架，可自由调整任意环节

5. **Wiki 结构化知识层是轻量级 GraphRAG 替代品**
   - 45 条/13 分类的结构化条目，替代需要知识图谱的复杂 GraphRAG
   - 运维成本低（SQLite 无外部依赖），效果接近 KG 增强

### kb2-web 劣势总结

1. **维护成本高**
   - 60+ 个 Python 文件，逻辑分散在 `api/`、`services/`、`models/`、`utils/`、`repositories/` 五个目录
   - 配置散落（`config.py` + `.env` + `settings.yaml`），无集中配置中心
   - 无统一错误处理方案，各模块异常处理风格不一致

2. **文档解析依赖外部 API**
   - MinerU API Key 依赖，一旦服务不可用或限流，上传管线退化为低质量的 PyPDF 回退
   - 大 PDF（>100 页）解析延迟可达 300 秒，用户体验差

3. **缓存逻辑复杂**
   - L1 精确缓存 + L2 语义缓存 + BM25 索引 + Rerank 缓存四层耦合
   - 缓存失效策略不统一（部分 TTL，部分手动清除）
   - 语义缓存与 BM25 索引之间存在数据一致性问题（文档更新后 BM25 可能滞后）

4. **泛化能力受限**
   - 仅支持政务中文领域，未见英文/多语言场景验证
   - 分块策略、同义词表、B03 关键词表均硬编码中文政务领域
   - 标准号 boost 的正则表达式仅覆盖中国标准体系

5. **无标准化 API 文档/SDK**
   - FastAPI 自动生成 OpenAPI 文档，但缺乏面向集成的 API 文档
   - 无 Python SDK / REST 客户端库

### 主流 RAG 方案不具备的 kb2-web 独有功能

1. **费用取费表专用检索管道（D2-B）**
2. **三级置信度门控（L1/L1.5/L2/L3 + L3 后生成校验）**
3. **孤儿 chunk 主动过滤**（doc_id 不在 title_map → 丢弃）
4. **标准号 boost**（standard_boost.py，正则匹配 + DB 精确查询）
5. **同义词扩展白名单**（费用类 30+ 同义词对）
6. **多 bank 隔离 + 并行召回**（4 大类 9 子库）
7. **Wiki 结构化知识层**（替代简易 GraphRAG）
8. **速查卡 / concept summary 注入**
9. **审计日志 + 质量门禁 G1/G2/G3 管线**
10. **CI 评估器**（66 题自动回归测试，基线 66%）

---

## 三、数据统计

| 指标 | 值 |
|------|-----|
| 后端 Python 代码行数 | 17,265 行 |
| 前端 Vue3 代码行数 | 5,780 行 |
| 核心 Python 文件数 | 60+ |
| Vue 组件/视图数 | 18 |
| CI 回归测试题数 | 66 |
| CI 基线准确率 | 66% |
| Wiki 条目数 | ~45 |
| Wiki 分类数 | 13 |
| 支持解析文档格式 | PDF / DOCX / XLSX / 扫描件（OCR） |
| 解析回退策略数 | 4（MinerU → PyPDF → OCR → 失败） |
| Bank 大类数 | 4（全部 / 行业 / 个人 / 项目） |
| Hindsight 子库数 | 9 |
| Rerank 模式数 | 4（cross_encoder / multidim / confidence / freshness） |
| 置信度门控层级数 | 4（L1 / L1.5 / L2 / L3） |
| 质量门禁级数 | 3（G1 / G2 / G3） |
| 缓存层级 | 2（L1 精确 + L2 语义）+ BM25 索引 |
| 部署形态 | systemd + uvicorn 4 workers |

---

## 四、结论

kb2-web v2 是一条 **深度定制于政务信息化领域的完整 RAG 管线**，在通用 RAG 框架基础上增加了大量独有功能（费用类取费表检索、标准号 boost、三级门控、Wiki 结构化知识层等）。与 LangChain/LlamaIndex 等主流方案相比，kb2-web 在检索质量、领域适配性、幻觉控制方面具备显著优势，但代价是维护复杂度高、外部 API 依赖不稳定、泛化能力受限。

**核心改进建议**（按优先级排序）：
1. 配置集中管理（统一 config schema）
2. 缓存策略简化（L1/L2 合一 + BM25 自动失效）
3. 标准化 API 文档 + SDK
4. MinerU API 本地化部署（消除外部依赖）
5. CI 测试集扩展至 200+ 题（覆盖更多 edge case）
