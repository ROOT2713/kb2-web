-- ============================================================================
-- P1' 待命迁移脚本 — embedding 模型迁移就绪 SQL（不自动执行）
-- ============================================================================
-- 目的：为未来换 embedding 模型（WeMM / Qwen3-VL / 其他）预留 schema 能力。
-- 触发条件（满足任一才执行）：
--   1. 任一平台（SiliconFlow/智谱/阿里云等）上架 WeMM-Embedding 或 Qwen3-VL-Embedding API
--   2. 出现扫描件/图纸/图片直搜需求（需多模态 embedding）
--   3. P2' 黄金基线证明新模型在中文政务检索域显著优于 BGE-M3（hit@10 提升 ≥10pp）
--
-- 原则：只在迁移发生时执行，不在当前生产库执行。当前零消费者，ALTER 是纯负债。
-- 对应决策记录：2026-08-28 评审（CC P1 建议修正为 P1' 待命脚本）。
-- ============================================================================

-- ── 1. 加列：chunk_type（预留多模态/混合 chunk 类型标记）──
-- 默认 'text'；未来扫描件入库时插 'image'，检索层可过滤或混合
ALTER TABLE vector_chunks ADD COLUMN IF NOT EXISTS chunk_type TEXT NOT NULL DEFAULT 'text';

-- ── 2. 加列：embedding_model_version（增量 re-embed 的前提）──
-- 记录每个 chunk 的向量由哪个模型生成；迁移时按版本过滤增量重建
ALTER TABLE vector_chunks ADD COLUMN IF NOT EXISTS embedding_model_version TEXT NOT NULL DEFAULT 'bge-m3';

-- ── 3. 索引（可选，chunk_type 过滤频繁时加）──
-- CREATE INDEX IF NOT EXISTS idx_vector_chunks_chunk_type ON vector_chunks(chunk_type);

-- ── 4. 回填当前存量（默认值已满足，无需 UPDATE；如已有数据带旧 NULL 才需）──
-- UPDATE vector_chunks SET chunk_type='text', embedding_model_version='bge-m3' WHERE chunk_type IS NULL OR embedding_model_version IS NULL;

-- ── 5. 迁移执行步骤（触发后按序执行，勿跳过）──
-- Step 1: 跑本脚本前 2 条 ALTER（schema 变更，ACCESS EXCLUSIVE 锁，选低峰期）
-- Step 2: 改 backend/.env: EMBEDDING_URL / EMBEDDING_MODEL → 新模型
-- Step 3: 增量 re-embed（只重算 embedding_model_version != 新值的 chunk）
--         psql -c "UPDATE vector_chunks SET embedding=NULL WHERE embedding_model_version != '<new>'"
-- Step 4: 重启 kb2-web 服务（systemctl restart kb2-web）
-- Step 5: 清 query_cache（旧向量空间缓存必须清）
--         psql -c "DELETE FROM query_cache;"
-- Step 6: 重校准三处阈值（BGE-M3 向量空间专属）：
--         - L2 缓存相似度 0.82
--         - 矛盾检测 0.40
--         - 知识结晶 0.20-0.50
--         重跑 scripts/recall_quality_baseline.py 对拍新旧基线
-- Step 7: 429/限流回归（新 API 配额可能不同）

-- ── 6. 回滚 ──
-- Step 1 回滚: ALTER TABLE vector_chunks DROP COLUMN IF EXISTS chunk_type;
--             ALTER TABLE vector_chunks DROP COLUMN IF EXISTS embedding_model_version;
-- Step 2 回滚: 改回原 .env 值 + 重启 + 清缓存
-- Step 3 回滚: 重新生成 bge-m3 向量（全量 re-embed）——迁移前建议备份 vector_chunks 表
--   CREATE TABLE vector_chunks_backup_<date> AS SELECT * FROM vector_chunks;
