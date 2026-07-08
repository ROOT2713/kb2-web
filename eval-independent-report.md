# kb2-web 独立评估报告

**评估时间**: 2026-07-08  
**评估者**: Hermes Agent (独立评估)  
**目标分支**: `feature/improvements-wave1` (HEAD: 5498b03)  
**服务状态**: 运行中 (PID 1592, :3027), 上线~5.5h  

---

## 1. Wave 1 修复质量评分

### D系列（多轮对话）— 综合评分: 8.5/10

| 维度 | 评分 | 说明 |
|------|:----:|------|
| **D01 同域追问** | 9/10 | 首轮422字→第二轮187字，session链接正常。session_doc_ids 域锁定机制正确工作。唯一扣分：session 域锁定时 L2 coverage 检查被跳过(return None)，即使覆盖率很低也不拒答 — 设计意图合理但无兜底。 |
| **D02 同文档跨方面** | 9/10 | T1含2018年份，T2有内容。版本感知去重(T1-2)正确保留多版本。D9锚词注入从history提取标准号追加到recall query生效。 |
| **D09 跨域跳跃** | 8/10 | 功能点方法→GB/T 36964（methodology→standards），首轮999字→次轮1062字含"36964"。硬 session_doc_ids 过滤器(72c0d51)移除后跨域召回正常。扣分：session更新策略是"合并"新旧 doc_ids，跨域跳跃后白名单膨胀 → 后续追问域锁定效果稀释。 |
| **D04 三追问链** | 8/10 | 510万→费率表格→速算增加额，三跳均正常。T7金额档位扩展+费率表注入机制有效。扣分：_tier_extra 逻辑复杂、两处注入(D2-B + T7兜底)有重复风险。 |

**D系列关键问题**:
- ❗ session doc_ids 白名单**只增不减**（合并逻辑），长会话后白名单膨胀到全部知识库 → 域锁定形同虚设
- ❗ `_user_supplied_session` 被当作 `is_multi_turn` 传入 — 多轮跳过的其实是"用户提供了session_id"，不是真正检测"这是否是追问"。如果无状态客户端每次都传空session_id，每次都被视为单轮，位置检查不跳过

### B系列（边界拒答）— 综合评分: 6.5/10

| 维度 | 评分 | 说明 |
|------|:----:|------|
| **B01 北京政务** | 10/10 | 正确拒答(40字, 0源)。北京在location_pattern中，知识库无北京文档 → L2位置拒答触发。 |
| **B02 GB 50058** | 3/10 | ⚠️ 未拒答(482字, 12源)。系统给出"规范全称"但无法提供技术条款。这是当前最有杀伤力的缺陷。根因：知识库中有GB 50348-2018引用文档提到了GB 50058 → 召回匹配引用文档 → source_count=12 → L1通过 → 不涉及地点 → L2位置检查跳过 → 混合条件(source_count<2? NO, coverage<0.5? 12个doc覆盖高 → NO) → 生成。**问题是：置信度系统无法区分"文档包含引用"和"文档包含正文"。** |
| **B03 深圳造价** | 10/10 | 正确拒答。深圳在location_pattern中。 |
| **B04 浙江数字化** | 10/10 | 正确拒答。浙江在location_pattern中。 |
| **B05 GDPR** | 10/10 | 正确拒答。'gdpr'在_en_locations黑名单中 |

**B系列关键问题**:
- ❗ **B02是架构级缺陷**：当前置信度评估只检查"是否有文档匹配"，不检查"匹配的文档是否真的包含答案"。这是知识库+LLM系统的经典问题 — RAG的"引用文档含查询词但不含答案"模式
- ❗ location_pattern 只用 doc_name（文档标题）做匹配，不检查 chunk_text 正文。如果文档标题不包含地点名（如"政务信息化管理办法——北京市版"标题包含了而在正文中），可能会误拒
- ❗ `[^\\s]{1,5}[省市区域]` regex会匹配"文件省市"这种偶然出现的模式 → 假阳性拒答

---

## 2. 代码风险清单

### P0 (必须立即修复)

| # | 风险 | 位置 | 详情 |
|---|------|------|------|
| P0-1 | **SQL注入** | `query.py:1511-1513` | 元数据信息卡使用 `f"'{d}'"` 字符串格式化拼接SQL，未用参数化查询。虽然 `_doc_ids_meta` 来自搜索结果而非直接用户输入，但一旦Hindsight搜索结果被污染(可能通过文档上传时在doc_id中注入恶意字符串)，即可进行SQL注入。**直接使用parameterized query重写。** |
| P0-2 | **Admin API 无认证** | `admin.py` | 所有管理端点（缓存清除DETETE、质量门禁POST、置信度重算POST、摘要批量生成POST）没有任何JWT/auth保护。`Depends(get_db)`只提供DB session，不支持鉴权。任意网络可达者可以清空缓存、重算、调用LLM批量生成。 |

### P1 (高优先级)

| # | 风险 | 位置 | 详情 |
|---|------|------|------|
| P1-1 | **session内存无限增长** | `session_manager.py:13` | `_SESSION_STORE` 是进程内 dict，TTL过期依赖 `_lazy_cleanup()`（每次get时调用，但create/update不触发cleanup）。如果有大量session创建但从未读取 → 内存泄漏。生产环境应有cap + 独立清理线程。 |
| P1-2 | **B02: 引用存在但正文缺失** | `_assess_recall_confidence()` | 置信度系统无法区分"有文档匹配查询词（但只是引用/提及）"和"有文档包含完整答案"。建议：对source_count>0但所有doc_facts中关键词密度低于阈值的查询降级拒答。 |
| P1-3 | **位置检测仅检查标题** | `_assess_recall_confidence()` | 位置匹配只在 `doc_name`（文档标题）中搜索，不检查 `chunk_text` 正文。文档内容含北京信息但标题不含 → 误拒。 |
| P1-4 | **is_multi_turn 语义错误** | `query.py:2157, 2174` | `_user_supplied_session` (用户是否传了session_id) 被当作 `is_multi_turn` 参数传给 `_assess_recall_confidence`。实际含义不同：用户传了session → 跳过位置检查。但如果客户端每次都传空session（无状态），则每次走位置检查，即使实际上是多轮。 |
| P1-5 | **重复代码（DRY违规）** | `_assess_recall_confidence()` | 位置检测逻辑完整地写了两次（L1827-L1858 和 L1879-L1913）。长度约70行，完全相同的 regex、相同的英文地点列表、相同的匹配逻辑、相同的返回格式。违反DRY原则。其中第一个副本在 session_doc_ids 检查之前且受 is_multi_turn 保护，第二个在 session_doc_ids 检查之后不受保护。 |

### P2 (中等优先级)

| # | 风险 | 位置 | 详情 |
|---|------|------|------|
| P2-1 | **Session白名单只增不减** | `query.py:2118` | 多轮对话跨域跳跃后，新旧doc_ids合并(union)，白名单只增长不收缩。长会话后所有文档都在白名单中，域锁定完全失效。 |
| P2-2 | **Cache hit不写审计日志** | `query.py:2004-2023` | 缓存命中的早期返回(return)直接跳出，不走下方~L2246的审计日志写入。导致审计日志不完整。 |
| P2-3 | **Phase F无content fallback** | `code-review-findings.md F1` | Phase F只用title匹配高信号词，没有Phase H那种content回退。文档标题不含关键词但正文包含时，concept summary注入被跳过。 |
| P2-4 | **Cache TTL存疑** | `cache_service.py:45, 86` | TTL硬编码为86400秒(24h)或row[3]的cache_ttl_seconds。但大规模生产环境中24h缓存可能导致返回过时信息。考虑引入bank-level或变化驱动的TTL策略。 |
| P2-5 | **重连/超时处理不一致** | `query.py:553-608` | Rerank阶段有三种模式(freshness/ce/llm)，每种有不同超时(15s/30s)、不同fallback行为、不同错误日志格式。freshness失败后会fallback到llm_rerank，而ce失败后直接跳到RRF顺序。 |

---

## 3. 遗漏路径检查

### 提前返回(early return)路径分析

| 路径 | 触发条件 | 当前行为 | 评估 |
|------|----------|----------|:----:|
| 空输入检查 | `q.strip()` 为空 | HTTP 400 | ✅ |
| L1 Cache hit (精确) | cache_get_exact 命中 | 直接return，无审计日志 | ⚠️ P2-2 |
| L2 Cache hit (语义) | cache_get_semantic 命中 | 直接return，无审计日志 | ⚠️ P2-2 |
| L1 Confidence reject | source_count ≤ 0 | 返回答+建议 | ✅ |
| L2 Location reject | 位置不匹配(单轮) | 返回答+建议 | ✅ (代码重复) |
| session_doc_ids skip | 域锁定状态下 | return None跳过L2 | ✅ |
| L2 Coverage reject | 覆盖率<50%+无精确匹配 | 返回答+建议 | ✅ |
| L3 Validate reject | validation score < 40% | 替换answer但保留sources | ⚠️ 保留了来源可能混淆用户 |
| _generate_answer空doc_facts | doc_facts为空(但有_ tier_extra兜底) | 返回答+替代建议 | ✅ |
| _generate_answer完全空 | doc_facts为空且无兜底 | 返回答+替代建议 | ✅ |
| LLM生成失败 | chat()异常 | 返回"答案生成失败: {e}" | ⚠️ 暴露了错误信息给用户 |

### Cache Hit 路径 (重点分析)

```
query()
  → nocache=False → cache_get_exact() → hit → return(answer, sources, suggestions)
  → nocache=False → cache_get_semantic() → hit → return(answer, sources, suggestions)
  → 未命中 → 继续完整流程
```

**问题**:
1. Cache hit 不写 audit_log（缺失查询记录）
2. Cache hit 不更新 session（每次cache hit会导致session_id被重置为新值——除非客户端每次传相同的session_id）
3. Cache hit 返回的 session_id 是新生成的（如果没有传session_id），导致客户端拿到全新的session_id，与cache miss时的行为不一致

### Error处理路径

| 异常场景 | 处理方式 | 评估 |
|----------|----------|:----:|
| DB查询异常(build_search_context初始) | `except Exception: pass` | ⚠️ 静默吞掉异常，bank_map/title_map为空字典，后续所有过滤失效 |
| Hindsight recall失败 | `except Exception: pass` (循环内) | ⚠️ 静默吞掉，特定bank返回空 |
| BM25构建失败 | `logger.warning` + 跳过BM25 | ✅ 可接受降级 |
| Rerank超时 | 各自fallback到RRF顺序 | ✅ |
| Rerank异常 | logger.warning + fallback | ✅ |
| Tiebreaker异常 | logger.warning + 跳过 | ✅ |
| parent_chunks查询异常 | logger.warning | ✅ |
| KG traversal异常 | logger.warning | ✅ |
| Confidence gate异常 | 不适用(纯逻辑) | ✅ |
| LLM生成异常 | 返回"答案生成失败: {e}" | ⚠️ 暴露异常信息 |
| 审计日志写入异常 | `except Exception: pass` | ✅ 可接受(不阻塞用户) |
| 缓存写入异常 | logger.info + 跳过 | ✅ |
| 缓存语义搜索异常 | logger.info + 跳过 | ✅ |

---

## 4. Wave 2 优先级排序

按 ROI = 预期收益 / 工时 排序：

| 优先级 | 改进项 | 预期+pp | 工时 | ROI | 理由 |
|:------:|--------|:-------:|:----:|:---:|------|
| **P0** | **B02类「库内引用但缺正文」拒答** | +2pp | 2h | **1.0** | 架构级缺陷。不是微调而是必须有的能力：检测"doc_facts中所有chunk都只提到标准号但没有条款内容"。方案：在_assess_recall_confidence增加"内容层检测"——检查top-k chunk的文本内容是否包含实质性条款（而非仅标准引用行）。可简单用_KW_IN_BODY_RATIO检测。 |
| **P1** | **D9历史锚词扩展调优** | +3pp | 2h | **1.5** | 已有实现，只需调整注入阈值和关键词来源。当前在短query(<30字)注入全部标准号。建议：增加关键词重要性权重过滤，避免注入弱相关标准号造成召回偏移。 |
| **P2** | **测试集清理（已知缺口题移除）** | +3pp | 3h | **1.0** | 评估数据质量直接影响回归测试可信度。已知缺口题（知识库确实不包含的知识）应从测试集中移除或标记为expected_fail。 |
| **P3** | **Session白名单收缩策略** | +1pp | 1h | **1.0** | 简单改进：session更新时改为limited merge（合并后只保留top-K最新文档，如top-20），防止白名单无限膨胀。 |
| **P4** | **引用关系图谱离线构建** | +5pp | 8h | **0.625** | 高收益但高成本。需要离线构建+维护、增量更新、存储扩展。B02的长期解决方案的一部分。 |
| **P5** | **缓存审计日志补充** | +0.5pp | 0.5h | **1.0** | 小改动：cache hit早期返回前先写审计日志。 |

**最终建议的Wave 2顺序**:
1. **B02拒答增强** (2h) — 最关键的感知质量改进
2. **D9锚词调优** (2h) — 低投入、已验证的机制优化
3. **测试集清理** (3h) — 提高后续改进的评估可靠性
4. **Session白名单收缩** (1h) — 防止域锁定随session退化
5. **引用关系图谱离线构建** (8h) — 长期高收益，但不应该在前4项未完成时启动

---

## 5. 整体成熟度评分

| 维度 | 评分 | 说明 |
|------|:----:|------|
| **召回精度 (Recall Precision)** | 7/10 | Hindsight + BM25 + RRF混合召回成熟。RRF k=60经验值ok。版本感知去重(T1-2)、标准号精确匹配(C1-StdBoost)、D9锚词注入均工作。扣分：inter-bank RRF在bank="all"时只是简单拼接，无权重调节。 |
| **拒答质量 (Rejection Quality)** | 5.5/10 | 三级门控制度框架好(L1空结果/L2低覆盖率+L3校验分)，但B02暴露了"引用存在但内容缺失"模式完全未被覆盖。位置检测的regex硬编码+标题仅匹配方式粗糙。L3 validation阈值(0.4)偏低，几乎从不触发。 |
| **多轮对话 (Multi-turn)** | 7.5/10 | session框架完整(创建/更新/过期/TTL)。跨域跳跃修复(72c0d51)是关键改进。扣分：白名单只增不减、is_multi_turn语义混淆、session内存无上限。 |
| **代码质量 (Code Quality)** | 6/10 | 有明确的架构分层(api/services/utils/models)。但有严重代码问题：SQL注入风险、重复70行代码、无认证admin API、多处空except:pass静默吞异常。 |
| **可观测性 (Observability)** | 7/10 | 审计日志系统(44bb639)已接入。logger.info覆盖主要节点。扣分：审计日志在cache hit路径缺失、无metrics(请求数/延迟/拒答率分布)、无结构化日志。 |
| **安全性 (Security)** | 4/10 | 最低分。Admin API无认证(P0)、SQL注入点(P0)、JWT secret为"CHANGE_ME_IN_PRODUCTION"硬编码默认值。 |
| **缓存系统 (Cache)** | 7/10 | L1+L2双级缓存设计合理，L2语义缓存阈值0.82经验证有效。LRU淘汰(200/entry)和bank隔离正确。扣分：TTL固定24h不灵活、BM25 TTL 10min可能不够(频繁重建)。 |
| **性能 (Performance)** | 7/10 | async/await贯穿全链路。rerank timeout合理(15-30s)。扣分：KG traversal是同步(subprocess)调用的、parent_chunks批量查询可优化为单次IN查询而非循环查询。 |

**综合成熟度: 6.4/10**

系统已达到"可用但需要加固"阶段。核心流程(RAG pipeline)正确且完整，拒答框架有了好的骨架但B02暴露了关键缺失。代码质量需要立即修复P0安全问题。

---

## 6. 最有价值的单项改进建议

> **如果只能改一件事：在 `_assess_recall_confidence` 中增加「内容实质性检测」（Content Substance Gate）。**

### 问题
当前置信度系统的隐含假设是："如果有文档匹配查询词，那么它包含答案"。B02证明了这个假设不成立。GB 50058 在知识库中没有正文内容，只有其他文档的引用行（如"按GB 50058的规定"）。系统检测到"GB 50058"出现在文档标题/内容中 → source_count > 0 → L1通过 → 不涉及地点 → L2通过 → 生成 → 用户得到"规范全称"但无技术条款。

### 建议实现方案（~2h工作量）

在 `_assess_recall_confidence` 的 L1 和 L2 之间新增一个 `Level 1.5: Content Substance Gate`：

```python
# ── Level 1.5: 内容实质性检测 ──
# 检测：top-k文档的chunk内容是否真正包含答案级别的信息，而非仅引用/提及
if source_count > 0 and source_count <= 3:  # 文档数很少时容易是引用命中
    _combined_text = " ".join([
        fact[0] for doc_facts_list in doc_facts.values() 
        for fact in doc_facts_list[:2]
    ][:5])  # 取前5个chunk
    # 检测标准引用模式（形如"GB/T XXXXX的规定"、"按XX标准执行"）
    _ref_pattern = re.compile(
        r'(?:按|根据|按照|依照|遵循|符合|执行|参照|引用)'
        r'(?:.*?)(?:标准|规范|规定|要求|规程|导则|指南)'
    )
    if _ref_pattern.search(_combined_text) and not _has_clause_content(_combined_text):
        # 有引用句式但无条款内容（无数字条款、无具体参数）
        return low_coverage reject
```

### 预期效果
- **B02**: 检测到引用GB 50058的文档只包含"按GB 50058的规定"这种引用句式，无具体条款（如"第X.X条"、"爆炸危险区域"等实质内容）→ 拒答 ✅
- **B01/B03/B04/B05**: 这些查询的doc_facts为空 → L1拒答，不受影响 ✅
- **正常查询**: 有完整条款/参数内容的文档 → 没有引用句式或不匹配条件 → L1.5通过 ✅

这个改动直接针对B02的根因，不影响其他case，代码量小（~30行），ROI极高。

---

## 附录: 代码库关键统计

| 指标 | 数值 |
|------|:----:|
| 文档总数 | 308 (active: 290, superseded: 18) |
| 文档bank分布 | standards:157, general:72, business:21, industry_docs:15, xhs:14, project_docs:6, tech_guides:2, methodology:2, checklist:1 |
| Parent chunks | 4,408 |
| 查询缓存 | 4条 (全是 bank='all') |
| 审计日志 | 325条 |
| query.py 行数 | 2,421行 |
| 服务PID | 1592 |
| 运行时长 | ~5.5h |

---

*报告结束*
