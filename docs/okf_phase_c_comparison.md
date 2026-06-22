# OKF Phase C 新旧对比

## 一、架构对比

### 改造前 (pre-OKF, commit f683f66)

```
用户查询 → Hindsight Dense recall (8 bank 分散)
         → BM25 keyword search
         → RRF merge
         → keyword_rerank (轻量)
         → [无 LLM rerank, 默认关闭]
         → doc_facts (按 RRF 顺序)
         → LLM 生成答案 (只看原文 chunks)
```

**问题**:
- Dense 多 bank 分散查询，每 bank 只分 3 条，通用主题文档排不到 top3
- 无结构化核心事实注入，LLM 只看原文 chunks
- contradiction 检测用 BGE-M3 embedding，伪阳性 ~90%
- review_required 基于伪阳性 flag，10 个文档被误标
- 新文档上传后无自动 concept/summary 回填

### 改造后 (OKF Full, commit 8e7b8f3)

```
用户查询 → Hindsight Dense recall (8 bank 分散)
         → BM25 keyword search
         → RRF merge
         → keyword_rerank (轻量)
         → [Phase H] doc_facts 相关度重排 (高信号词匹配 doc_name)
         → [Phase C1] 标准号精确匹配 boost (DB 直查，强制注入)
         → [Phase F] 速查卡相关度过滤 (跳过不相关 doc)
         → [Phase C2] Core Claims 速查卡注入 (concept.summary)
         → LLM 生成答案 (速查卡 + 原文 chunks)
         
定时任务 (每6h):
         → [Phase C4] G2: 无 concept 的文档自动生成
         → [Phase C4] G2b: 无 summary 的 concept 自动回填
         → [Phase C4] G3: 增量结晶 (新 pairs LLM 精判)
         
知识结晶:
         → [Phase C5] BGE-M3 grey-zone pairs → DeepSeek 5 分类精判
         → [Phase C5] review_required 只在 LLM 确认真矛盾时置 1
```

---

## 二、代码变更对比

### 新增文件

| 文件 | 行数 | 功能 |
|---|---|---|
| `backend/app/services/standard_boost.py` | 195 | C1 标准号提取 + DB 精确匹配 + doc_facts 注入 |
| `backend/app/services/crystallization_light.py` | 393 | C5 LLM 5 分类精判 + concept_contradictions 表 |
| `backend/scripts/rebuild_concepts.py` | 91 | C3 reparse 后 concept 重建脚本 |
| `backend/scripts/cron_incremental_maintenance.py` | 292 | C4 三阶段增量维护 cron |
| `backend/tests/unit/test_standard_boost.py` | 17 tests | C1 单元测试 |

### 修改文件

| 文件 | 改动 | 功能 |
|---|---|---|
| `backend/app/api/query.py` | +130 行 | C2 速查卡注入 + F 相关度过滤 + H doc_facts 重排 + 公共函数抽取 |
| `backend/app/services/confidence.py` | +40 行 | C5 review_required 逻辑改造 (需 LLM 确认真矛盾) |
| `backend/app/services/concept_summary.py` | 0 | C2a/C3 复用已有 LLM 摘要服务 |

### 新增 DB 表

```sql
CREATE TABLE concept_contradictions (
    concept_a_id TEXT NOT NULL,
    concept_b_id TEXT NOT NULL,
    embedding_similarity REAL,
    llm_verdict TEXT,          -- TRUE_CONTRADICTION / TERM_DIFFERENCE / UNRELATED / METADATA_NOISE / SAME_DOC_SECTION
    llm_reason TEXT,
    judged_at TIMESTAMP,
    PRIMARY KEY (concept_a_id, concept_b_id)
);
```

---

## 三、指标对比

### 3.1 检索质量（60 题 CC 出题）

| 指标 | 改造前 | 改造后 | Δ |
|---|---|---|---|
| Recall | 61.7% | 63.3% | +1.7pp |
| Answer Quality | 59.2% | 75.0% | **+15.8pp** |
| B Wins | — | 21/60 | — |
| B Losses | — | 0 | — |

### 3.2 检索质量（35 题前期题库）

| 指标 | 改造前 | 改造后 | Δ |
|---|---|---|---|
| Recall | 85.7% | 94.3% | +8.6pp |
| Answer Quality | 67.1% | 82.9% | +15.7pp |
| B Wins | 5 | 17 | — |

### 3.3 知识库健康度

| 指标 | 改造前 | 改造后 |
|---|---|---|
| concept summary 覆盖率 | 0% | 99.4% |
| review_required 伪阳性 | 10 | 1 |
| Crystallization 覆盖 | 0 pairs | 2364 pairs (全量) |
| 增量维护 | 手动 | 每 6h cron 自动 |
| 测试基线 | 374 passed | 374 passed (无回归) |

### 3.4 性能影响

| 指标 | 改造前 | 改造后 | 影响 |
|---|---|---|---|
| 查询延迟 | ~15s | ~15s | C1 <5ms, C2 ~10-20ms (可忽略) |
| LLM 调用 (查询时) | 1 次 | 1 次 | 无增加 |
| LLM 调用 (维护时) | 0 | cron 每 6h | 不影响在线查询 |
| Embedding 调用 (结晶) | 0 | 一次性 2364 | 已完成，增量时极少 |

---

## 四、Commit 历史

```
8e7b8f3 fix(okf): CC HIGH#1-3 — API Key dotenv + 高信号词抽取 + asyncio 安全
002322e feat(okf): Phase C4 — cron 增量维护自动化
d776f2f fix(okf): Phase H — doc_facts query-doc 相关度重排
a038daf fix(okf): Phase F — 速查卡 query-doc 相关度过滤
06ad803 fix(okf): C5 SQL 修正 — has_true_contradiction UNION 子 LIMIT 不兼容
0062985 feat(okf): Phase C5 — Crystallization Light LLM 精判
487850c feat(okf): Phase C3 — 薄文档 MinerU 重解析 + concept 重建
15db581 feat(okf): Phase C2 — Core Claims 速查卡注入
288395a feat(okf): Phase C1 — 标准号精确匹配 boost
```

**总计**: 9 commits, ~1500 行新增代码, 374 测试全过
