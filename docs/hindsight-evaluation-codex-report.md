# Codex 方案评估报告：kb2-web Hindsight 替换

## 当前架构扫描摘要

| 维度 | 现状 |
|------|------|
| **Hindsight 状态** | systemd 进程，占用 ~400MB RSS，监听 :8888，使用 PostgreSQL (pgvector) 后端 |
| **现有数据** | 3,262 文档 / 27,297 chunks，embeddings 全部有效（Zhipu embedding-2, 1024维），分布在 9 个 bank |
| **嵌入 API** | 可用 → open.bigmodel.cn embedding-2，已在 embeddings.py 中封装 |
| **LLM API** | 可用 → DeepSeek chat，已在 retrieval.py 中使用 |
| **与 Hindsight 耦合点** | 3 处：vector_repo.py(HindsightStore)、upload.py(直接调用 HindsightStore + recall)、retrieval.py(直接调用 _hindsight_request()) |
| **Metadata DB** | SQLite (./data/kb.db)，非 PostgreSQL |
| **PostgreSQL** | 已运行（localhost:5432），pgvector 0.6.0 已安装 |

## 方案对比表

| 维度 | A: Hindsight 保留 | B: pgvector ★推荐 | C: ChromaDB | D: FAISS | E: Qdrant |
|------|:----------------:|:-----------------:|:-----------:|:--------:|:---------:|
| **架构可维护性** | ❌ 差 — 两套HTTP客户端 + LLM pipeline 硬依赖 | ✅ **优秀** — Protocol→pgvector直连 | ⚠️ 中 — 进程内库API简洁 | ❌ 差 — 无metadata过滤/增删改 | ✅ 好 — 功能完备 |
| **运维简易性** | ❌ 差 — systemd+400MB+venv | ✅ **最佳** — 零额外服务 | ✅ 好 — pip install | ⚠️ 中 — 需手动管理索引 | ❌ 差 — 需Docker |
| **部署便携性** | ⚠️ 中 — 需打包整套环境 | ✅ **好** — PostgreSQL是标准组件 | ⚠️ 中 — ~70MB依赖+数据目录 | ✅ 好 — 轻量 | ❌ 差 — 需Docker |
| **检索/上传功能** | ⚠️ 中 — 有代理延迟+60s等待 | ✅ **优** — 纯SQL<10ms+立即可查 | ✅ 好 — 功能完整 | ⚠️ 中 — 不支持tags过滤 | ✅ 好 — 功能丰富 |
| **数据兼容性** | ✅ 好 | ✅ **好** — 现有27K向量直接迁移 | ❌ 需重新ingest | ❌ 需重建索引 | ❌ 需导出导入 |

## 推荐方案及理由

### 强烈推荐：方案 B — pgvector 直接实现

1. **pgvector 已安装、已运行、已有数据** — 不是"新增基础设施"，而是"利用已有"
2. **消除一个完整服务** — 系统从 3 个服务降为 2 个，内存节省 ~400MB
3. **消除两套 HTTP 客户端** — 统一为单个 SQLAlchemy 查询类
4. **消除 60s 等待** — 写入立即可查，延迟从分钟级降为秒级
5. **嵌入 API 已就绪** — embeddings.py 已有 get_embedding() 调用
6. **部署简化** — 打包 = PostgreSQL dump + 代码，无需额外虚拟环境

### 数据结构设计

```sql
CREATE TABLE IF NOT EXISTS vector_chunks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id      TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    bank        TEXT NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(1024),
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_vc_bank ON vector_chunks (bank);
CREATE INDEX idx_vc_doc_id ON vector_chunks (doc_id);
CREATE INDEX idx_vc_embedding ON vector_chunks 
    USING hnsw (embedding vector_cosine_ops) WITH (m = 24, ef_construction = 200);
```

## 迁移方案

### 代码改动量估算

| 文件 | 新增 | 修改 | 删除 | 说明 |
|------|:----:|:----:|:----:|:----:|
| vector_repo.py | ~200行 (PGVectorStore) | ~10行 | ~120行 (HindsightStore) | 主要替换 |
| models/vector.py (新建) | ~50行 | - | - | SQLAlchemy ORM模型 |
| config.py | ~10行 | ~5行 | ~5行 | pgvector连接配置 |
| api/upload.py | ~20行 | ~50行 | ~20行 | 嵌入+写入+验证 |
| services/retrieval.py | ~10行 | ~100行 | ~100行 | recall→pgvector |
| 迁移脚本 (新建) | ~150行 | - | - | 从memory_units迁移 |
| **合计** | **~440行** | **~165行** | **~245行** | **~850行净改动** |

### 增量迁移顺序

1. 在 hindsight 数据库中建 `vector_chunks` 表
2. 从 `memory_units` 迁移现有数据（27k rows）
3. 部署 `PGVectorStore`，配置开关 `VECTOR_BACKEND=pgvector`
4. 切换检索走 pgvector（前端无感知）
5. 切换上传走 pgvector
6. 确认 zero regression 后停用 hindsight-api

## 迁移后数据流对比

### 上传流程
| 步骤 | 之前 | 之后 |
|:----|:----|:-----|
| 解析 → chunk | ✅ 一致 | ✅ 一致 |
| 构建 tags | ✅ memory_items | ✅ memory_items |
| 写向量 | POST /memories (300ms + 60s consolidation) | INSERT INTO vector_chunks (<5ms) |
| 验证 | await recall (60s) | 即时 SELECT |
| **总延迟** | **~90s** | **~5s** |

### 检索流程
| 步骤 | 之前 | 之后 |
|:----|:-----|:-----|
| 嵌入查询 | Hindsight 内部（~500ms-2s） | get_embedding (缓存命中=0ms) |
| 向量搜索 | recall HTTP POST (~1s) | pgvector HNSW < 10ms |
| BM25 | SQLite | SQLite（不变） |
| RRF + rerank | 一致 | 一致 |
| **向量搜索** | **~1s** | **<10ms** |

## 风险与应对

| 风险 | 级别 | 应对 |
|:----|:----:|:-----|
| pgvector 性能不足（27k chunks 量级） | 低 | HNSW 索引 <10ms，够用 |
| 12,674 orphan chunks 无 document_id | 中 | 按 text hash 聚类，无法归类作 standalone |
| 上传时 embedding 计算耗时 | 中 | 20-per-batch 批量并行，Zhipu 响应 <1s/次 |
| 目标服务器无 pgvector | 中 | 迁移脚本含 CREATE EXTENSION IF NOT EXISTS vector |
| 回滚 | 低 | VECTOR_BACKEND 配置开关保持 Hindsight 在线 |
