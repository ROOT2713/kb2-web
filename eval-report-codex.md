# kb2-web vs 参考方案对比评估报告 — Codex 版

**评估日期**：2026-07-07 15:00
**评估对象**：方案A（参考方案 等保POC概念设计）vs 方案B（kb2-web 知识库V2）
**评估工具**：Codex CLI（OpenAI），delegate_task 子代理模式
**数据采集**：实时 DB 快照 + Git 历史 + 服务状态 + 代码审计

---

## 一、项目总览

| 维度 | 参考方案 | kb2-web 实际 |
|------|---------|-------------|
| **定位** | 等保测评机构本地知识库 POC/MVP（4-6周） | 通用政务信息化知识库 V2 生产系统（约6个月迭代） |
| **技术栈** | PostgreSQL + pgvector + PgFTS + 本地模型 + FastAPI | SQLite + Hindsight 向量引擎 + DeepSeek + SiliconFlow |
| **状态** | 文档方案，未实现 | 系统运行中（uvicorn PID 1560539），45MB SQLite DB |
| **迭代阶段** | 规划中（POC→MVP→生产） | T0/T1/T2 三轮精度调优、OKF 生命周期、CI 每日回归 |
| **核心设计原则** | 本地部署优先、数据治理先于模型、检索前权限过滤、回答带来源 | 全部实现 + 检索管线完善 + 来源卡片 + JWT RBAC + 66题测试集 |

---

## 二、项目差异对比

### 2.1 架构层级对比

| 维度 | 参考方案 | kb2-web 实际 | 差距分析 |
|------|---------|-------------|---------|
| **后端框架** | FastAPI/Spring Boot（建议） | FastAPI（已实现） | kb2-web 已选定并运行 |
| **主数据库** | PostgreSQL（推荐） | SQLite 45MB | 参考方案更合理——SQLite 无并发写扩展能力 |
| **向量存储** | pgvector（与 PG 集成） | Hindsight 独立引擎(:8888) | 各有利弊 |
| **全文检索** | PostgreSQL FTS | BM25Okapi（内存索引，10min TTL） | kb2-web 更快但内存压力大 |
| **文档解析** | 本地 PDF/Word/Excel 工具 | MinerU API（云端） | 参考方案更符合"数据不出域" |
| **Embedding** | 本地中文 Embedding 模型 | text-embedding-3-small via API | 参考方案数据安全性更高 |
| **Reranker** | 可选本地 Reranker | BGE-Reranker-v2-M3 + 5种模式 | kb2-web 更丰富但依赖云端 |
| **大模型** | 本地/内网模型 | DeepSeek v4 flash via API | 参考方案更安全 |
| **缓存** | 未提及 | L1精确+L2语义+BM25内存缓存 | kb2-web 有完整双层缓存 |
| **多租户/多库** | 项目级权限隔离 | 11 Bank + 7活跃HS Bank | kb2-web 多领域知识组织成熟 |
| **前端** | Vue/React（建议） | Vue3+TypeScript（11视图页面） | kb2-web 完整 SPA |
| **审计日志** | PostgreSQL 审计表+日志文件 | 无权侧审计日志 | 参考方案规划更完整 |

### 2.2 数据模型对比

| 维度 | 参考方案 | kb2-web 实际 |
|------|---------|-------------|
| **文档模型** | 文档编号、版本、密级、项目、等级、适用范围、审批状态 | Document 表：doc_id/title/bank/searchable/OKF全字段 |
| **切片模型** | 语义完整小片段+来源上下文 | ParentChunk 分层切片（parent-child两级）+ chunk_count |
| **知识组织** | 标准条款、测评项、问题、整改建议结构化 | Concepts(3809) + SynonymMap(158) + KGTriple(45) + Contradictions(2029) |
| **版本管理** | 文档版本、审批状态 | version + supersedes/superseded_by双链 + stale检测 |
| **缓存** | 未提及 | query_cache表(4条) + L1/L2双重缓存 |
| **权限** | 用户/角色/项目/密级/使用范围 | User表 + admin/viewer两级 + JWT |
| **同义词** | 未明确提及 | synonym_map(158条) + expand_query_synonyms |

### 2.3 检索管线对比（核心差异）

| 维度 | 参考方案 | kb2-web 实际 |
|------|---------|-------------|
| **召回策略** | 全文检索+向量检索（pgvector） | 三路召回：Hindsight语义+BM25关键词+取费表SQL+C1-StdBoost |
| **融合策略** | 未详细说明 | RRF融合(k=60) + tiebreaker sort |
| **重排序** | 未提及 | 5种rerank模式：LLM/multidim/confidence/freshness/cross-encoder |
| **查询优化** | 未提及 | 查询分解+同义词扩展+金额层级展开+标准编号归一化+D9 |
| **领域路由** | 按项目/密级过滤 | 11 Bank分流+domain_routing |
| **拒答机制** | 应拒答越权/无答案内容 | 未实现拒答机制 |

### 2.4 数据治理对比

| 维度 | 参考方案 | kb2-web 实际 |
|------|---------|-------------|
| **文档总量** | 未指定 | 303篇（285active+18superseded） |
| **切片总量** | 未指定 | 4,383 parent_chunks + ~29,297 Hindsight chunks |
| **质量门禁** | 质量复核概念 | G1/G2/G3三级质量门禁+quality_gate_log |
| **上传管线** | 语料登记→脱敏复核→解析→结构化→切片→索引→发布审核 | 上传API(upload_tasks表5条)+MinerU解析+chunking+concept_gen |
| **脱敏** | 识别客户/IP/账号/漏洞等敏感内容 | 无脱敏实现 |
| **知识过期管理** | 保留期限+销毁要求 | stale_detection服务+置信度衰减 |
| **文档来源** | 标准/模板/质控规则/问题/整改建议 | manual(192)/v1_migration(78)/xhs(30)/v1_backfill(3) |

### 2.5 安全与权限对比

| 维度 | 参考方案 | kb2-web 实际 |
|------|---------|-------------|
| **认证** | 机构现有SSO/RBAC或本地RBAC | JWT双通道+HTTPBearer |
| **角色** | 多级角色（用户/角色/项目） | admin/viewer两级 |
| **内容级权限** | 按密级、使用范围、项目过滤 | 未实现 |
| **审计日志** | PostgreSQL审计表+日志文件 | 无审计日志功能 |
| **拒答** | 越权检索/无答案时拒答 | 未实现拒答机制 |
| **API安全** | 未详细说明 | CORS全开放(allow_origins=["*"])+JWT+role-based router |

### 2.6 评估验证体系对比

| 维度 | 参考方案 | kb2-web 实际 |
|------|---------|-------------|
| **测试方法论** | 未提及 | 66题LLM-Judge测试集+CI每日回归+趋势检测 |
| **回归验证** | 未提及 | GitHub Actions自动回归+cron调度 |
| **过拒分析** | 未提及 | 3轮CC过拒审查+overrejection_test.py |
| **精度调优** | 未提及 | T0/T1/T2三轮调优+多维rerank权重调参 |
| **测试文件** | 未提及 | 32个测试文件 |
| **代码行数** | 设计文档 | 25,227行后端代码 |

---

## 三、实践参考 (kb2-web 可借鉴参考方案的要点)

### 3.1 安全合规方向 — P0

| 借鉴要点 | 价值 | 落地建议 |
|---------|------|----------|
| **内容级权限模型** | 高 | Document表增加security_level字段，检索时追加SQL过滤 |
| **审计日志** | 高 | 建立audit_log表，记录每次检索和回答生成 |
| **拒答机制** | 中高 | 增加confidence threshold检查，低于阈值返回拒答 |
| **脱敏管线** | 高 | upload流程中集成脱敏模块（IP/手机号/身份证正则替换） |

### 3.2 数据治理方向 — P1

| 借鉴要点 | 价值 | 落地建议 |
|---------|------|----------|
| **语料登记与审批** | 中 | upload_tasks表增加approval_status字段+审批API |
| **密级与保留期限** | 中 | Document表增加retention_date与现有stale_detection集成 |
| **数据补齐** | 中 | 为249个无摘要的概念批处理补齐摘要 |

### 3.3 架构扩展方向 — P1/P2

| 借鉴要点 | 价值 | 落地建议 |
|---------|------|----------|
| **PostgreSQL迁移** | 中高 | 迁移至PG+pgvector替代Hindsight |
| **本地模型部署** | 中 | 部署本地vLLM/Ollama+bge-m3 |
| **内网部署文档** | 中 | Docker Compose+无外网配置+模型镜像 |


## 四、优化提升建议

### P0 — 紧急（安全合规）

| 编号 | 建议 | 工时 |
|------|------|:----:|
| P0-1 | 实现拒答机制（置信度阈值检查） | 4h |
| P0-2 | 实现检索审计日志（audit_log表+查询API） | 8h |
| P0-3 | 加固CORS配置（明确前端地址） | 1h |
| P0-4 | JWT Secret生产环境轮换 | 0.5h |

### P1 — 重要（功能完善）

| 编号 | 建议 | 工时 |
|------|------|:----:|
| P1-1 | 内容级权限过滤（security_level字段+检索过滤） | 12h |
| P1-2 | 补齐概念摘要（249条无摘要概念） | 2h |
| P1-3 | PostgreSQL迁移评估报告 | 8h |
| P1-4 | 上传审批流程（G2门禁后approval_status） | 8h |
| P1-5 | 同义词管理前端UI | 6h |

### P2 — 长期（架构优化）

| 编号 | 建议 | 工时 |
|------|------|:----:|
| P2-1 | 脱敏管线（IP/身份证/手机号正则替换） | 16h |
| P2-2 | 本地模型部署 (vLLM/Ollama+bge-m3) | 24h |
| P2-3 | 多假设生成策略增强（5种视角） | 4h |
| P2-4 | GraphRAG探索（利用45条kg_triples+2029条contradiction） | 16h |
| P2-5 | 性能基准测试 | 4h |
| P2-6 | SSO集成（OAuth2/OIDC） | 16h |


## 附录A：数据快照

**服务状态**：kb-web v2.0.0, :3027, uvicorn PID 1560539, Hindsight :8888 healthy

**数据库（45MB SQLite）**：
- documents: 303 (285 active + 18 superseded)
- parent_chunks: 4,383
- concepts: 3,809 (3,560有摘要, 93.5%)
- concept_contradictions: 2,029
- synonym_map: 158
- kg_triples: 45
- query_cache: 4
- users: 2 (1 admin + 1 viewer)

**文档分布**：standards(174)/general(72)/business(21)/industry_docs(15)/xhs(10)/project_docs(6)/methodology(2)/tech_guides(2)/checklist(1)

**检索参数**：top_k=20, RRF k=60, rerank后返回15, chunk_size=800, overlap=120, BM10 TTL=10min, L1 cache=2000条, L2 cache阈值0.82, cache TTL=24h

**最近提交（当日3个）**：
- cross-encoder reranker (BGE-Reranker-v2-M3, ~0.3s/query)
- C1-StdBoost (doc_facts按published_date排序)
- D9 history anchor (历史锚点术语注入)

**后端代码**：123 Python文件, 25,227行, 12个端点模块, 25个服务模块, 32个测试文件

## 附录B：术语对照表

| 术语 | 说明 |
|------|------|
| Hindsight | 独立向量检索引擎，基于Bank隔离存储 |
| Bank | 知识库领域分区，独立HS Bank和BM25索引 |
| OKF | 知识组织框架（concept_id/domain/status/version链） |
| RRF | 倒数排序融合（Reciprocal Rank Fusion） |
| C1-StdBoost | 标准编号精确匹配增强 |
| SourceCard | 来源卡片组件 |
| LLM-Judge | LLM作为评估者评分 |
| Quality Gates | G1格式/G2完整性/G3一致性 |
| MinerU | 云端PDF解析服务 |
| SiliconFlow | API服务商（Embedding+Reranker） |
