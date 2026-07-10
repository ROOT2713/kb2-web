# CC 审查报告：kb2-web Hindsight 替换可行性

## 审查范围
- 后端 92 文件（Python API、服务层、仓库层、工具模块）
- 重点文件：`vector_repo.py`、`retrieval.py`、`upload.py`、`documents.py`、`query.py`、`admin.py`、`banks.py`、`embeddings.py`
- 分析依据：`_hindsight_request` 调用 33 处、`HindsightStore` 引用 10 处、`tags` 依赖链路

---

## 1. VectorStore 接口完整性 — 🔴 严重

| 问题 | 级别 | 详情 |
|------|------|------|
| Protocol 与实现签名不符 | 🔴 | `VectorStore` Protocol 定义 `query(self, embedding: List[float], ...)`，但 `HindsightStore` 实现为 `query(self, query_text: str, ...)`。参数名和类型均不匹配。Protocol 不被任何代码用作类型注解，形同虚设。 |
| `query_by_embedding` 是空桩 | 🟡 | Hindsight REST API 不支持裸向量查询，该方法永远返回 `[]`。替代方案（pgvector）可直接支持裸向量。 |
| Protocol 未被任何代码引用 | 🔴 | 搜索 `from app.repositories.vector_repo import VectorStore` 结果为空。`upload.py` 直接 import `HindsightStore`，完全没有通过抽象层调用。 |

**修改建议**：修复 Protocol 签名使 `query` 同时接受 `query_text` 和 `embedding`；全仓替换 import；补充 `health()`、`search_by_metadata()` 等方法。

---

## 2. HindsightStore 耦合度 — 🔴 严重

### 21 处直接 `_hindsight_request()` 调用

| 文件 | 函数 | 调用数 | 用途 |
|------|------|--------|------|
| `retrieval.py` | `recall()` | 2 | 语义搜索 |
| `retrieval.py` | `_get_active_hindsight_banks()` | 1 | 发现活跃 bank 列表 |
| `retrieval.py` | `build_bm25_index()` (fallback) | 1 | 当 SQLite 无数据时的 fallback |
| `documents.py` | `list_documents()` | 1 | 补齐 chunk 数和字符数 |
| `documents.py` | `fetch_standard()` | 2 | 上传标准文档到 Hindsight |
| `documents.py` | `refetch_document()` | 2 | 重新上传到 Hindsight |
| `documents.py` | `delete_document()` | 3 | 列出文档 → 逐个删除 |
| `documents.py` | `get_document_content()` + v1 | 4 | 从 Hindsight 获取文档内容 |
| `documents.py` | `reparse_document()` | 2 | 重新索引到 Hindsight |
| `admin.py` | `get_stats()` | 1 | 统计（bank stats） |
| `admin.py` | `health_check()` | 1 | 健康检查 |
| `banks.py` | `delete_bank_api()` | 1 | 删除 Hindsight bank |

### Tag 格式耦合

`upload.py` L332 构建 tags 格式：
```
doc:filename, chunk:N/M, doc_id:xxx, title:xxx, bank:xxx, parent_idx:N, strategy:xxx, cat:xxx
```

下游消费：
- `retrieval.py:recall()` — 提取 `doc_id:` 去重
- `retrieval.py:keyword_rerank()` — 提取 `doc_id:` + `parent_idx:` 连续性检测
- `retrieval.py:apply_tiebreaker_sort()` — 提取 `doc_id:` 排序
- `documents.py:list_documents()` — 提取 `doc_id:` 统计
- `documents.py:delete_document()` — 提取 `doc_id:` 删除匹配

---

## 3. 检索链路字段依赖 — 🔴 严重

`recall()` 返回格式：
```python
{"text": str, "tags": [...], "score": float, ...}
```

下游消费：
```
text → BM25, RRF, keyword_rerank, LLM rerank, LLM 回答生成
tags → doc_id/title/parent_idx 提取（8 处）
score → RRF merge 权重, tiebreaker 排序
```

新 store 的 `query()` 返回必须 100% 兼容此三字段格式。

---

## 4. 数据迁移风险 — 🟡

| 数据源 | 位置 | 内容 | 数量 |
|--------|------|------|------|
| SQLite kb.db | `/home/ubuntu/kb-web/data/kb.db` | 150 个 searchable=1 文档的完整 chunk 文本 | ~150 文档 |
| PostgreSQL (Hindsight) | localhost:5432 hindsight | 3262 个文档（无有效 embedding） | 3262 文档 |

**风险**：PG 中 3262 文档无有效 embedding（LLM Key 过期导致 fact_extraction 跳过），需要全量重新嵌入。建议先迁移 SQLite 中 150 个活跃文档，再后台批量处理旧文档。

---

## 5. Embedding 调用独立性 — 🔴 严重

**`embeddings.py:get_embedding()` 在现有代码中完全未被使用！**

| 流程 | 当前做法 | 替换后需要 |
|------|---------|-----------|
| 上传 | `HindsightStore().upsert()` 传入纯文本，Hindsight 内部调 embedding | upload 前手动调 `get_embedding()` 生成 chunk 向量 |
| 检索 | `recall()` 传入 query 文本，Hindsight 内做 embedding + 搜索 | recall 前手动调 `get_embedding(query)`，传入 `query_by_embedding()` |
| BM25 | 不依赖 embedding | 不变 |

✅ `embeddings.py` 代码本身是干净的独立模块，可直接复用。需要添加批量 API 调用 + 重试逻辑。

---

## 6. 上传链路重构点 — 🟡

`upload.py` L325-335 的 memory_items 构建逻辑改动小，主要改动点在 L430-465 写入段：

1. 在 `upsert()` 之前插入 `get_embedding()` 批量调用
2. 传入 `store.upsert(embeddings=..., metadata=tags, ...)`
3. 完整性验证用新 store 的 `query_by_embedding` + metadata filter

---

## 7. 配置耦合 — 🟡

| 配置点 | 文件:行 | 耦合度 |
|--------|---------|--------|
| `hindsight_url` | `config.py:47` | 低 — 可兼容为 `vector_store_url` |
| `bank.hindsight` 字段 | `retrieval.py:33-45` | 🟡 中等 — 9 个 bank 全用 `hindsight` 键 |
| `_get_active_hindsight_banks()` | `retrieval.py:137-156` | 🔴 严重 — 调用 Hindsight API 发现 bank |
| `_normalize_bank_config()` | `retrieval.py:59-60` | 🟡 中等 — 自动生成 `kb_{key}` bank 名 |

---

## 迁移工作量

| 步骤 | 任务 | 预估 |
|------|------|------|
| S1 | 实现 pgvector 存储后端 (`PgVectorStore` 类) | 1 天 |
| S2 | 重写 Protocol，统一 query 签名 | 0.5 天 |
| S3 | 上传链路适配：添加 embedding 调用 | 1 天 |
| S4 | 检索链路适配：query_by_embedding → recall | 1 天 |
| S5 | 文档管理适配：list/delete/reparse 改用新 store | 1.5 天 |
| S6 | Admin/stats 适配 | 0.5 天 |
| S7 | BM25 索引 fallback 清理 | 0.5 天 |
| S8 | 数据迁移脚本：SQLite → pgvector 全量 | 1.5 天 |
| S9 | 环境配置新旧共存 | 0.5 天 |
| S10 | 测试 + 回归验证 | 1.5 天 |
| **总计** | | **~9.5 人天** |

---

## 风险 TOP5

| 风险 | 级别 | 描述 | 缓解 |
|------|------|------|------|
| R1: 21 处直接 HTTP 调用 | 🔴 极高 | `_hindsight_request()` 在 6 个文件中被直接调用 21 次 | 先重构抽象层提供全部方法，再逐文件替换 |
| R2: tag 格式软依赖 | 🔴 高 | `doc_id:xxx`、`parent_idx:N`、`title:xxx` 格式被 8 处解析 | 新 store 必须 100% 兼容此格式，存入 metadata |
| R3: embedding 移到应用层 | 🟡 中 | 替换后需在 upload 前和 recall 前手动调 API，批量有速率限制 | 添加批量调用 + 重试 + 降级 |
| R4: 3262 旧文档需重新嵌入 | 🟡 高 | 需 ~32620 次 API 调用（每文档 ~10 chunk） | 分批迁移，先迁 150 活跃文档 |
| R5: 配置向下兼容 | 🟢 中 | `banks.json` 等配置文件可能被运维修改 | 新旧字段名同时兼容 2 个版本 |

---

## 总结

✅ **可替换，但风险中等偏高**

**推荐分两阶段**：
- **Phase 1（3 天）**：重构 vector_repo 抽象层 → 添加 pgvector 实现 → 迁移 150 个活跃文档 → 端到端验证
- **Phase 2（6.5 天）**：清退所有 `_hindsight_request` → 迁移 3262 旧文档 → 删除 Hindsight 服务 → 系统清理
