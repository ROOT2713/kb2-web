# 本地知识库底座技术栈方案 vs kb2-web 对比评估报告

> 编制日期：2026-07-07 14:30
> 数据采集时间：2026-07-07 14:00-14:20
> 评估对象：`本地知识库底座技术栈与原理说明(1)(1).md`（下文称"参考方案"）
> 对比基准：`kb2-web`（知识库V2）—— FastAPI + Hindsight + SQLite + 多Bank 知识库系统（:3027）

---

## 一、项目总览

### 参考方案定位

面向等保测评机构的本地知识库 POC/MVP 概念设计方案，工期估算 4-6 周。
核心设计原则：本地部署优先、数据治理先于模型能力、检索前权限过滤、回答必须带来源、轻量可控按量升级。

### kb2-web 当前运行状态

| 指标 | 当前值 |
|------|--------|
| **服务状态** | active（systemd kb-web，`/health` 返回 ok） |
| **服务端口** | :3027（uvicorn, PID 1560539） |
| **数据库** | SQLite 45MB（复用 v1 的 `kb.db`） |
| **Hindsight 向量引擎** | healthy，12 banks，~29,297 总 chunk |
| **最近提交** | 今日3个（cross-encoder reranker / StdBoost / D9） |
| **总后端代码** | 56 个 Python 文件 / 14,006 行 |
| **前端** | 33 个 Vue3+TS 文件，Vite 构建 |
| **测试** | 36 个测试文件 |
| **DB 迁移** | 4 次 Alembic 迁移 |

### 一句话结论

**参考方案是"规划图纸"，kb2-web 已是"建成的三层楼"——且今天又加了电梯（cross-encoder reranker）+ 装修了大厅（C1-StdBoost）+ 升级了空调（D9 历史锚点）。** kb2-web 在检索管线、缓存、知识组织（OKF）、评估验证、多Bank 体系上全面领先；参考方案有借鉴价值的是安全合规视角（脱敏、内容级权限、审批流程）。

---

## 二、项目差异对比

### 2.1 架构层级对比

| 维度 | 参考方案设计 | kb2-web 实际方案 | 差异分析 |
|------|-------------|-----------------|---------|
| **后端框架** | FastAPI / Spring Boot（通用建议） | FastAPI + SQLAlchemy async | 一致，kb2-web 有明确选型且在产线 |
| **数据库** | PostgreSQL（建议） | **SQLite** 45MB | 参考建议偏 PG 生态；kb2-web 用 SQLite 简化部署，数据量级匹配 |
| **向量存储** | pgvector（建议） | **Hindsight API**（独立引擎，约 29,297 chunk） | 最大架构差异。kb2-web 通过 Hindsight 12 个独立 bank 做语义检索 |
| **全文检索** | PostgreSQL FTS + 中文分词（建议） | **BM25Okapi**（rank_bm25 内存索引）+ SQLite LIKE | kb2-web 纯 Python BM25，免运维 |
| **文档解析** | 本地 PDF/Word/Excel（建议） | **MinerU API**（云端）+ 本地 fallback | kb2-web 解析质量更高 |
| **Embedding** | 本地中文 Embedding 模型（建议） | **智谱 embedding-2 API**（云端） | 参考方案偏本地部署，kb2-web 偏质量优先 |
| **Reranker** | 可选本地 Reranker（建议） | **4 种可切换**：default/confidence/freshness/multidim + **今日新增 cross_encoder**（SiliconFlow BGE-Reranker-v2-M3，~0.3s/query） | kb2-web 远超参考方案设计 |
| **大模型** | 本地/内网合规模型（建议） | **DeepSeek v4 flash**（云端 API） | 参考偏安全，kb2-web 偏效果 |
| **前端** | Vue / React（通用建议） | **Vue 3 + TypeScript + Vite** | 明确选型 |
| **缓存** | 未提及 | **query_cache 表** + 4 条 L2 缓存 + cache_fingerprint 去重 | kb2-web 实际已在运行 |
| **多租户/多库** | 权限过滤（概念） | **11 个 Bank + 12 个 Hindsight banks**，每 bank 独立 system prompt、独立 hindsight 存储 | kb2-web 实际落地 |

### 2.2 数据模型对比

| 维度 | 参考方案概念 | kb2-web 真实 schema | 丰富度 |
|------|------------|-------------------|--------|
| **文档模型** | 元数据表（概念） | **documents 表**：doc_id, title, bank, searchable, status, source, published_date, geo_scope, profile_confidence, original_text_length, concept_id, domain, subdomain, version, supersedes/superseded_by, stale_at/reason, chunk_count, review_required — 30+ 字段 | 远超 |
| **切片模型** | 语义完整片段（概念） | **parent_chunks 表**：4,383 条，含 chunk_index, section_type, section_header, token_count | 结构化 |
| **知识组织** | 未提及 | **concepts 表** 3,809 条（3,560 条有 summary，93.5%），含 concept_id, summary, domain routing | 先进 |
| **版本管理** | 保留期限（概念） | 18 条 superseded 文档，version 字段（semver），stale_at/stale_reason | 完整 |
| **冲突检测** | 未提及 | **concept_contradictions 表**，2,029 条冲突记录 | 领先 |
| **知识图谱** | 后续阶段考虑 | **kg_triples 表** 45 条，graphrag_enabled=False（Phase 2 门控） | 有储备 |
| **缓 存** | 未提及 | **query_cache 表**：cache_id, query_text, query_embedding(BLOB), bank, answer, sources_json, hit_count, ttl_seconds, doc_ids_json | 完整 |
| **权 限** | SSO/RBAC（概念） | **users 表**：username, password_hash, salt, role（admin/viewer）。1 admin + 1 viewer | 基本可用 |
| **同义词** | 未提及 | **synonym_map 表** 158 条，支持查询扩展 | 有储备 |
| **质量门禁** | 未提及 | **quality_gate_log 表** 4 条 | 初始阶段 |

### 2.3 检索管线对比（核心差异）

| 维度 | 参考方案 | kb2-web 实际 |
|------|---------|-------------|
| **召回策略** | 全文检索 + 向量检索 | **三路召回**：① Hindsight 语义检索（12 bank 并行）② BM25 关键词检索 ③ 取费表专用 SQL 检索路径 |
| **融合策略** | 未提及 | **RRF 融合**（Reciprocal Rank Fusion, k=60） |
| **重排序** | 可选本地 Reranker | **5 种模式可切换**：default / multidim / confidence / freshness / **cross_encoder**（今日新增，SiliconFlow BGE-Reranker-v2-M3） |
| **查询优化** | 未提及 | **查询分解**（query_decomposer.py）+ **同义词扩展**（158 条 synonym_map）+ **金额层级展开**（expand_amount_tiers）+ **标准编号归一化** |
| **领域路由** | 未提及 | **OKF domain_routing**：按查询意图自动选 Bank + **domain 字段路由** |
| **标准增强** | 条款编号检索（概念） | **C1-StdBoost**（今日新增）：标准编号匹配 → doc_facts 前置 + published_date 排序（最新版优先） |
| **历史锚点** | 未提及 | **D9**（今日新增）：history anchor term injection into recall query |
| **空结果处理** | 未提及 | **交互式提示（suggestions）+ Web 搜索兜底** |
| **来源引用** | 回答必须带来源 | **来源卡片（SourceCard）** 完整实现 + Phase 1 evidence-level explainability |
| **缓存策略** | 未提及 | **query_cache 表** 4 条 + cache fingerprint + ttL 去重 |
| **过拒控制** | 未提及 | **RPO 信号检测** + 过拒率监控 + 修复评估（66 题 3 轮测试） |

### 2.4 文档与数据治理对比

| 维度 | 参考方案 | kb2-web 实际 |
|------|---------|-------------|
| **文档总量** | 概念阶段 | **303 文档**（285 active + 18 superseded） |
| **切片总量** | 概念阶段 | **4,383 parent_chunks** |
| **Bank 分布** | 未细分 | standards(174), general(72), business(21), industry_docs(15), xhs(10), project_docs(6), methodology(2), tech_guides(2), checklist(1) |
| **出版日期** | 未提及 | 149/303（49.2%）有 published_date |
| **地理范围** | 未提及 | 220/303（72.6%）有 geo_scope |
| **置信度** | 未提及 | 141/303（46.5%）有 profile_confidence |
| **脱敏处理** | 识别敏感内容（概念） | **未实现** |
| **文档质量门禁** | 未提及 | **quality_gate_log 表** 4 条记录 + 上传管线预检 |
| **入库审批** | 知识管理员确认（概念） | **未实现**（upload_tasks 表 5 条记录，无审批字段） |
| **上传管线** | 简单文件存储（概念） | **precheck → SHA1 去重 → MinerU 解析 → 分块 → Hindsight 写入 → metadata 入库** 完整管线 + MinerU 多 Key 轮询 |

### 2.5 安全与权限对比

| 维度 | 参考方案 | kb2-web 实际 |
|------|---------|-------------|
| **认证** | SSO/RBAC（概念） | **JWT 双通道**（HTTP Basic 登录 → Bearer Token） |
| **角色** | 未细分 | **admin/viewer 两级**（role_rank: admin=2, viewer=1） |
| **内容级权限** | 检索前权限过滤（核心原则） | ❌ **未实现**——仅 API 认证，未在 SQL 层做内容级过滤 |
| **前端权限** | 未涉及 | **Vue 路由守卫 + authStore.isAdmin** 前端 role 感知 |
| **审计日志** | PostgreSQL 审计表（概念） | **admin audit API** + 前端管理面板可视化 |
| **脱敏** | 核心设计原则 | ❌ **未实现** |
| **拒答机制** | 不越权不泄露（核心原则） | ⚠️ 有 overrejection 检测但无主动内容级拒答 |

### 2.6 评估验证体系对比

| 维度 | 参考方案 | kb2-web 实际 |
|------|---------|-------------|
| **测试方法论** | 未提及 | **66 题测试集**（三层：easy/medium/hard）+ **LLM-Judge 评估** + 3 轮迭代 |
| **回归验证** | 未提及 | **CI 评估器** + Hermes Cron 每日 8 点自动回归 |
| **过拒分析** | 未提及 | **CC 过拒审查** + 17 标记分类 + precision vs recall 分解 |
| **检索精度** | 未提及 | **T0/T1/T2 精度调优**：RRF cap, version dedup, summary detect, chunk_position, section, continuity |
| **RAG 评估** | 未提及 | **rag_eval API** + 前端管理可视化 |

---

## 三、今日（2026-07-07）新增变化

报告编制当天（14:00-14:20 数据采集）发现的 3 个新提交：

| 提交 | 功能 | 对对比评估的影响 |
|------|------|-----------------|
| **da49d17** cross-encoder reranker | SiliconFlow BGE-Reranker-v2-M3，~2s→~0.3s/query，纯新增不替换 LLM rerank | ✅ **对比表 2.3 更新**——kb2-web rerank 模式从 4 种增至 5 种 |
| **f2f2b5e** C1-StdBoost | doc_facts 按 published_date 排序，最新版优先，修复 T02 回归 | ✅ **对比表 2.3 更新**——标准增强增加了日期感知 |
| **3fc6e11** D9 history anchor | 历史锚点术语注入到 Hindsight recall query 中 | ✅ **对比表 2.3 更新**——新增历史锚点维度 |

这些提交说明 kb2-web 仍在快速迭代——**每天都有新的检索优化**，远非"设计完成"状态。

---

## 四、实践参考（kb2-web 可借鉴的参考方案要点）

参考方案在 **安全合规、工程治理、架构设计** 三个维度的设计思考仍有借鉴价值：

### 4.1 安全合规方向（P0 建议）

| 参考方案设计 | 借鉴价值 | kb2-web 当前状态 | 落地建议 |
|-------------|---------|----------------|---------|
| **数据脱敏**：识别客户名称、IP、漏洞细节 | **高** | ❌ 完全空白 | 上传管线末端增加 `sanitizer.py`，产出脱敏副本后再写入 Hindsight |
| **内容级权限过滤**：检索前按密级/范围过滤 | **高** | ❌ 仅 API 级认证 | retrieval.py 的 SQL 查询中加 `classification_level <= user.max_level` 条件 |
| **入库审批流程**：知识管理员确认后才发布 | 中 | ❌ 无审批字段 | upload_tasks 表加 `approval_status` + 前端审批面板 |
| **拒答机制**：不越权、不泄露、不编造 | 中 | ⚠️ 有来源引用但无内容级拒答 | 结合 geo_scope/classification_level 做内容级吐回控制 |

### 4.2 数据治理方向（P1 建议）

| 参考方案设计 | kb2-web 当前状态 | 受益 | 工时估计 |
|-------------|----------------|------|---------|
| **出版日期补齐**：49.2%→100% | 已有 backfill 脚本可扩展 | 标准版本排序准确 | 0.5 天 |
| **置信度补齐**：46.5%→100% | 已有 OKF confidence 框架，部分文档未填 | 检索质量可量化 | 0.5 天 |
| **文档分级**：添加 classification_level 字段 | 无此字段 | 安全合规 | 1 天 |
| **语料登记元数据**：上传时增加负责人/来源/保留期限 | 仅有 basic source 字段 | 合规追溯 | 1 天 |

### 4.3 架构扩展方向（P2 建议）

| 参考方案建议 | 当前状态 | 评估 |
|-------------|---------|------|
| **PostgreSQL 迁移路径** | 纯 SQLite | 当前 45MB SQLite + ~29K Hindsight chunk 短期够用，但 PG 事务能力和中文 FTS 是长期价值点 |
| **内网模型部署评估** | 纯云端 API（DeepSeek + 智谱 + SiliconFlow） | 等保密级场景需要，建议输出一份评估文档 |
| **SLA/高可用架构** | 单机单实例 | 机构推广才需要 |
| **数据湖/全量分析** | 无 | 阶段四才需要，当前无需投入 |

---

## 五、关键发现

### 5.1 kb2-web 已显著领先的领域（参考方案仅概念）

1. **检索管线深度**：三路召回 + 5 种 Rerank 模式（含今日新增 cross-encoder）+ RRF 融合 + 查询分解 + C1-StdBoost + D9 历史锚点
2. **缓存体系**：query_cache 表 + fingerprint 去重，经 66 题验证
3. **知识组织（OKF）**：3,809 concepts（93.5% 有 summary），2,029 条冲突检测，版本链 18 条 superseded
4. **评估验证**：66 题 LLM-Judge + CI 每日回归 + 3 轮 CC 过拒审查 + Retrieval Precision Tuning 3 轮（T0/T1/T2）
5. **多 Bank 体系**：11 个 Bank + 12 个 Hindsight bank（~29,297 chunk），每 bank 独立 prompt
6. **上传管线**：MinerU 解析 + 分块 + precheck/SHA1 去重 + 多 Key 轮询 + 自适应分块
7. **推理优化**：cross-encoder reranker 2s→0.3s 加速，5 种 rerank 模式可切换

### 5.2 参考方案有借鉴价值的领域

1. **数据脱敏**：kb2-web 完全空白，参考方案提出了完整的脱敏分类
2. **内容级权限过滤**：kb2-web 有 JWT 认证但无内容级过滤
3. **入库审批环节**：kb2-web 有 upload_tasks 但无审批字段
4. **拒答机制**：kb2-web 有 overrejection 检测但无主动内容级拒答
5. **本地部署方案**：kb2-web 依赖云端 API，参考方案可做等保密级场景的备选路线

### 5.3 参考方案明显不足的领域（纸上谈兵）

1. **无检索管线深度**：只提了"全文检索+向量检索"，没有 RRF 融合、缓存策略、查询分解、重排序策略
2. **无数据库 schema**：没有字段定义、索引设计、关系模型
3. **无 API 设计**：没有路由定义、请求/响应格式
4. **无评估方法**：没有测试集设计、评估指标、验收标准
5. **无操作细节**：没有具体命令、配置文件、部署脚本
6. **无代码示例**：没有伪代码或关键实现片段

---

## 六、结论与建议

### 阶段判定

| 参考方案定义 | kb2-web 实际阶段 |
|-------------|-----------------|
| POC（4-6 周） | — |
| 内网 MVP | ✅ 已超越 |
| **生产增强** | ⚠️ 部分达到（检索强 + 安全弱） |

### 建议优先级

| 优先级 | 方向 | 参考方案输入 | 工时估计 |
|--------|------|------------|---------|
| **P0** | 脱敏处理模块（sanitizer.py） | 完整的脱敏分类建议 | 1-2 天 |
| **P0** | 内容级权限过滤（retrieval.py SQL 加条件） | "检索前权限过滤"设计原则 | 0.5-1 天 |
| **P1** | 入库审批流程（approval_status 字段 + 前端面板） | "入库审批"设计流程 | 2-3 天 |
| **P1** | 数据治理补齐（published_date/confidence 到 100%） | 数据治理先于模型 | 1 天 |
| **P1** | 拒答机制（geo_scope + classification_level 内容级控制） | "不越权不泄露"原则 | 2 天 |
| **P2** | PostgreSQL 迁移可行性评估文档 | 推荐架构参考 | 0.5 天 |
| **P2** | 内网模型部署方案评估 | 本地部署原则 | 2 天调研 |

---

## 附录 A：数据库快照（2026-07-07 14:00）

```
documents:      303  (285 active, 18 superseded)
parent_chunks:  4,383
concepts:       3,809  (3,560 with summary)
synonym_map:    158
query_cache:    4
kg_triples:     45
concept_contradictions: 2,029
users:          2  (1 admin, 1 viewer)
quality_gate_log: 4
upload_tasks:   5

Hindsight facts (12 banks):
  kb_standard:   10,346
  kb_general:     6,710
  kb_checklist:   4,434
  kb:             2,838
  kb_industry:    1,812
  kb_project:       699
  kb_tech:          407
  general:           50
  kb_xhs:             1
  others:              0
  ───────────────────────
  Total:         ~29,297
```

## 附录 B：最近 15 次提交

```
da49d17 cross-encoder reranker: SiliconFlow BGE-Reranker-v2-M3  (今日)
f2f2b5e C1-StdBoost: sort injected doc_facts by published_date (今日)
3fc6e11 D9: history anchor term injection into recall query    (今日)
28ba5ab P1: metadata info card block (not inline) + test set cleanup
f44c50b Phase 1: SourceCard evidence-level explainability + CI
edfa2d3 Revert P1: metadata injection caused 45% regression
4834a65 P1: LLM prompt enhancement using doc metadata + A10 fix
4b94144 T2: retrieval precision tuning (chunk_position, section, RRF k)
f1b2ed8 T1: retrieval precision fixes (RRF cap, version dedup, summary detect)
6a23cdf T0: retrieval precision fixes (P1,P4,P5,P6)
98c997f Fix: D2-B scoring (mismatch penalty, density cap, size norm)
b24cad2 Fix: remove duplicate require_admin from admin.py
00fb35b Fix: Chunk dict pipeline mapping + Quality Gates API + upload
cbe752e P2: frontmatter hindsight tags + upload cleanup + extractview
9219018 Phase 0+1: OKF lifecycle + document lifecycle + multidim rerank
```

## 附录 C：API 端点清单

服务状态：**active**（:3027）
认证方式：JWT（admin/viewer 两级角色）

> 注意：OpenAPI `/openapi.json` 返回为空，建议检查 FastAPI 路由注册方式。

## 附录 D：关键术语对照

| 参考方案术语 | kb2-web 等价物 |
|------------|---------------|
| 全文检索 | BM25Okapi + SQLite LIKE |
| 向量检索 | Hindsight recall endpoint |
| 重排序 | 5 种 rerank 模式（含 cross-encoder） |
| 权限过滤 | JWT require_role（API 级） |
| 审计日志 | admin API audit |
| 文档元数据 | documents 表（30+ 字段） |
| 文本切片 | parent_chunks 表 |
| 知识单元 | concepts 表 + OKF 框架 |

---

*本报告基于对 kb2-web 运行中服务、SQLite 数据库、Git 提交历史的实时数据采集编制。数据采集时间 2026-07-07 14:00-14:20。*
