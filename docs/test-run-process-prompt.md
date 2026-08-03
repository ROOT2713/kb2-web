# kb2-web RAG 测试集运行提示词

## 目标

你是 kb2-web 政务信息化知识库 RAG 系统的测试执行与分析 agent。本次任务不是只给出最终答案或通过率，而是要完整记录测试过程、判题依据、过程信号、失败归因和最终研判。

测试对象为 kb2-web API：

```text
POST /api/query
```

固定请求参数：

```json
{
  "q": "<question>",
  "bank": "all",
  "nocache": true
}
```

测试集路径：

```text
scripts/105_questions_v7.jsonl
```

该测试集共 105 题，由 `95_questions_v6` 加 `fee_v7` 新增题组成。背景中提到费用类新增题约 10-12 题，执行时必须以测试集实际题目分类为准，并在报告中说明实际识别到的 fee 类题目数量。

现有测试运行器：

```text
scripts/kb2_66test_v3.py
scripts/kb2-test-runner-v4.py
```

其中：

- `kb2_66test_v3.py` 使用 keyword 判题，并存在历史经验修正公式：真实能力约等于“脚本报出通过率 + 40pp”。
- `kb2-test-runner-v4.py` 使用 LLM-Judge 判题。
- 本次必须优先保证“过程可审计”，不能只��出脚本汇总结果。

---

## 准备

### 1. 确认服务状态

先确认 kb2-web API 服务已启动，并能访问 `/api/query`。

建议先用 1 个简单问题做 smoke test：

```bash
curl -sS -X POST "http://127.0.0.1:8000/api/query" \
  -H "Content-Type: application/json" \
  -d '{"q":"请介绍一下知识库支持哪些政务信息化问题查询","bank":"all","nocache":true}'
```

若端口不是 `8000`，先确认实际服务地址。后续所有测试必须记录实际 base URL。

### 2. 确认测试集

读取：

```text
scripts/105_questions_v7.jsonl
```

确认每题字段，包括但不限于：

- `id`
- `question`
- `expected`
- `keywords`
- `category`
- `type`
- `tags`

如果字段名与上述不完全一致，以文件实际字段为准，并在报告开头说明字段映射。

### 3. 确认运行策略

本次测试需要兼顾稳定性与可观察性。

默认执行参数：

```text
bank=all
nocache=true
并发数：3-5
单题请求超时：60 秒
整体重试：失败或超时题最多重试 1 次
重试间隔：2 秒
answer 截断阈值：默认 3000 字；若回答更长，保留前 3000 字并标注已截断
sources 完整保留，不截断
```

如果系统负载较高，优先降低并发到 2，而不是关闭 `nocache`。

---

## 执行方式

### 推荐执行流程

1. 读取 `scripts/105_questions_v7.jsonl`。
2. 对每题调用：

```http
POST /api/query
Content-Type: application/json
```

请求体：

```json
{
  "q": "<question>",
  "bank": "all",
  "nocache": true
}
```

3. 记录完整响应，包括：

```text
answer
sources
耗时
HTTP 状态码
错误信息
```

4. 对每题进行判题，至少包含两层：

```text
keyword 判题：expected/keywords 与 answer 的显式命中��况
semantic 判题：answer 是否实质覆盖 expected 的核心语义点
```

5. 若使用现有 runner：

```bash
python scripts/kb2_66test_v3.py
python scripts/kb2-test-runner-v4.py
```

则必须额外补充每题过程记录，不能只复用 runner 的汇总通过率。

### 并发与超时要求

执行建议：

```text
并发数：4
单题超时：60 秒
重试次数：1
请求参数：bank=all, nocache=true
```

如出现大量超时或 5xx：

```text
先降并发到 2 复测失败题
若仍失败，标记为 timeout/server_error
不要把服务不可用题直接判为内容失败
```

### 缓存要求

本次必须使用：

```text
nocache=true
```

目的：测试真实召回与生成链路，避免历史缓存掩盖问题。

### 结果保存要求

建议输出至少三类文件：

```text
完整逐题 JSONL：每题一个结构化对象，包含请求、响应、判题、过程信号
人类可读 Markdown 报告：完整过程摘要、失败分析、最终研判
原始响应快照：可选，保留 API 原样返回
```

建议命名：

```text
reports/kb2_105_v7_run_<YYYYMMDD_HHMMSS>.jsonl
reports/kb2_105_v7_report_<YYYYMMDD_HHMMSS>.md
```

---

## 每题记录模板

每一道题必须按以下固定字段记录。

```markdown
## ��目 <index>/<total>：<id>

### 1. 提问原文

```text
<question>
```

### 2. 请求信息

```json
{
  "url": "<base_url>/api/query",
  "method": "POST",
  "params": {
    "q": "<question>",
    "bank": "all",
    "nocache": true
  },
  "timeout_seconds": 60,
  "attempt": 1
}
```

### 3. 响应状态

```text
HTTP 状态码：<status_code>
耗时：<latency_ms> ms
是否重试：<yes/no>
错误信息：<error_message_or_empty>
```

### 4. 系统回答

```text
<answer_full_or_truncated>
```

回答截断状态：

```text
answer_length_chars: <number>
truncated: <true/false>
truncate_limit_chars: 3000
```

### 5. 召回来源 sources

```json
[
  {
    "rank": 1,
    "doc": "<doc_name_or_title>",
    "score": <score_or_null>,
    "keyword_matches": ["<keyword1>", "<keyword2>"],
    "source_type": "<fee_table/policy/guide/unknown>",
    "chunk_id": "<chunk_id_or_empty>",
    "snippet": "<source_snippet_if_available>"
  }
]
```

若 API 返回字段名不同，按实际字段映射，但必须保留：

```text
doc 名
score
keyword_matches
可识别的 source/chunk 信息
```

### 6. 期望答案与判题依据

期望信息：

```text
expected: <expected_text_or_summary>
expected_keywords: [<kw1>, <kw2>, ...]
expected_semantic_points:
- <point_1>
- <point_2>
- <point_3>
```

实际命中：

```text
keyword_hits:
- <keyword>: hit/miss，证据：<answer 中对应片段>

semantic_hits:
- <semantic_point>: hit/partial/miss，证据：<answer 中对应片段或说明>
```

判题结论：

```text
result: PASS / BORDERLINE / FAIL
confidence: high / medium / low
reason: <一句话说明为什么这样判>
```

判题规则：

```text
PASS：核心语义点完整回答，关键事实无明显错误；允许措辞不同。
BORDERLINE：回答部分正确，但缺少关键条件、来源不稳、表述含混、或只覆盖一部分 expected。
FAIL：拒答、空壳回答、答非所问、关键事实错误、混用政策/费用表、超时无结果、编码乱码导致不可读。
```

### 7. 过程信号

```json
{
  "refusal_detected": true,
  "refusal_markers": ["无法回答", "未找到相关信息"],
  "empty_shell_detected": false,
  "empty_shell_reason": "",
  "fee_query": true,
  "fee_source_count": 2,
  "fee_table_source_count": 1,
  "table_output_detected": true,
  "encoding_ok": true,
  "encoding_issue": "",
  "mixed_source_risk": false,
  "mixed_source_reason": "",
  "timeout": false,
  "server_error": false
}
```

过程信号定义：

```text
refusal_detected：
回答出现“无法回答”“知识库中未找到”“未检索到相关依据”等拒答或准拒答。

empty_shell_detected：
回答看似有结构，但没有具体政策、金额、条件、流程、材料或结论。

fee_query：
题目涉及收费、费用、价格、缴费、计费、标准、金额、减免、退费等。

fee_source_count：
sources 中与费用相关的来源数量。

fee_table_source_count：
sources 中明确来自费用表、收费标准表、价目表的来源数量。

table_output_detected：
answer 是否使用表格、项目符号表、字段化结构表达费用或流程。

encoding_ok：
中文是否可读，是否存在 `��`、乱码、异常转义、字段破碎。

mixed_source_risk：
是否疑似把不同事项、不同地区、不同表格、不同政策口径混在一起回答。
```

### 8. 失败归因

仅当 `result=FAIL` 或 `BORDERLINE` 时填写。

```text
failure_category: refusal / empty_shell / mixed_source / timeout / encoding / wrong_fact / incomplete / retrieval_miss / judge_uncertain / other
failure_detail: <具体说明>
suspected_stage: retrieval / rerank / generation / formatting / api / judge / unknown
recommended_fix: <针对该题的修复建议>
```
```

---

## 判题要求

### 1. Keyword 判题

对每题的 expected、keywords 或标准答案字段做显式匹配。

记录：

```text
应命中关键词数量
实际命中关键词数量
命中的关键词列表
未命中的关键词列表
```

注意：keyword 判题只能作为证据之一，不能机械等同于最终通过。

### 2. Semantic 判题

必须判断 answer 是否覆盖 expected 的核心语义点。

重点看：

```text
是否回答了问题本身
是否给出关键条件
是否给出关键金额/标准/比例
是否说明适用范围
是否存在事实错误
是否引用了正确来源
```

### 3. 费用类专项判题

费用类题目必须额外检查：

```text
是否召回费用表或收费标准表
是否给出明确金额/标准/计费口径
是否说明适用条件
是否把多个费用项目混在一起
是否缺少单位，如 元/次、元/件、%、工作日
是否只说“以实际为准”但没有知识库答案
```

费用类题目判定：

```text
PASS：
金额/标准/条件/来源均��本正确。

BORDERLINE：
金额或条件部分正确，但来源不足、单位缺失、适用范围含混。

FAIL：
拒答、没有金额、费用表未召回、混用费用项目、金额错误。
```

---

## 分析层要求

完成全部题目后，必须输出分类汇总。

### 1. 三分类统计

```text
总题数：105
PASS：<n>，<rate>%
BORDERLINE：<n>，<rate>%
FAIL：<n>，<rate>%
```

同时输出：

```text
严格通过率 = PASS / 总题数
宽松通过率 = (PASS + BORDERLINE) / 总题数
```

### 2. 按题型/类别统计

如果测试集有 category/type/tags 字段，按实际字段统计：

```text
category/type/tag
总数
PASS
BORDERLINE
FAIL
严格通过率
主要失败原因
```

必须单列：

```text
fee 类题目
非 fee 类题目
```

### 3. 失败题逐题归类

失败和边界题必须列成表格：

```markdown
| id | question 摘要 | result | failure_category | suspected_stage | 关键证据 | 建议 |
|---|---|---|---|---|---|---|
```

归类枚举：

```text
refusal：拒答或准拒答
empty_shell：空壳回答
mixed_source：来源混用或口径混用
timeout：请求超时
encoding：乱码或编码异常
wrong_fact：关键事实错误
incomplete：回答不��整
retrieval_miss：召回缺失
judge_uncertain：判题不确定
other：其他
```

### 4. 过程信号汇总

必须汇总：

```text
拒答题数量
空壳回答数量
费用类题数量
费用类召回费用表数量
表格输出数量
编码异常数量
混用风险数量
超时数量
服务错误数量
```

### 5. 与历史基线对比

必须单独一节对比 v6 95 题时期表现。

如果有历史报告或 runner 输出，使用实际数值。

如果没有可用历史数据，必须明确写：

```text
未找到可核验的 v6 95 题历史报告，本次仅能做方法论对比，不能声称提升或下降。
```

如使用 `kb2_66test_v3.py` 的 keyword 判题结果，必须注明：

```text
v3 keyword 判题存在历史经验修正：真实能力约等于脚本报出通过率 + 40pp。该修正只能作为经验估计，不能替代逐题人工/语义研判。
```

对比格式：

```markdown
| 版本/测试集 | 题数 | 判题方式 | 报出通过率 | 修正估计 | 主要问题 |
|---|---:|---|---:|---:|---|
| v6 | 95 | keyword/LLM-Judge/人工 | <value_or_unknown> | <value_or_unknown> | <summary> |
| v7 | 105 | keyword + semantic + process signals | <value> | <value_if_applicable> | <summary> |
```

---

## 最终研判要求

最终报告必须包含以下结论。

### 1. 整体结论

输出：

```text
本次测试总题数
严格通过率
宽松通过率
主要问题域
是否达到可上线/可回归/需阻塞修复
```

研判口径：

```text
可上线：
核心政务问答稳定，费用类无 P0 错误，失败多为边缘表达或少量召回不足。

可回归：
存在明显失败，但集中在少数类别，修复路径清晰。

需阻塞修复：
出现大量拒答、费用金额错误、政策混用、编码异常、API 不稳定或核心问题大面积失败。
```

### 2. 费用类查询专项研判

必须说明：

```text
本次实际识别 fee 类题目数量
fee 类 PASS/BORDERLINE/FAIL 数量
费用表召回情况
金额/单位/条件准确性
是否存在费用项目混用
是否存在“只引用政策不引用费用表”的问题
费用类是否可接受
```

费用类专项结论必须明确：

```text
fee 类通过 / fee 类边界可接受 / fee 类需阻塞修复
```

### 3. 修复建议优先级

必须按 P0/P1/P2 输出。

```text
P0：会导致严重错误或上线阻塞的问题
- 费用金额错误
- 费用项目混用
- 核心政务事项拒答
- 编码乱码导致不可读
- API 大量超时/5xx

P1：影响用户体验或准确率，但有替代路径的问题
- 召回来源不足
- 回答缺少关键条件
- 表格结构不稳定
- 答案过泛
- 边界题集中在某类文档

P2：优化项
- 答案格式统一
- sources 字段补充 doc/chunk/snippet
- keyword_matches 可解释性增强
- runner 报告自动化
```

每条建议必须包括：

```text
问题
影响范围
建议动作
预期收益
验证方式
```

### 4. 下次迭代建议

必须给出下一轮测试建议：

```text
是否需要扩展 fee 类测试
是否需要增加混淆题/反例题
是否需要拆分 keyword 判题与语义判题
是否需要增加固定 golden set
是否需要保留历史趋势图
是否需要加入延迟、超时、召回深度等稳定性指标
```

---

## 最终报告模板

```markdown
# kb2-web 105 题 v7 测试运行报告

## 1. 测试概况

- 测试时间：<YYYY-MM-DD HH:mm:ss>
- 执行 agent：<agent_name>
- API base URL：<base_url>
- 测试集：scripts/105_questions_v7.jsonl
- 总题数：105
- 请求参数：bank=all, nocache=true
- 并发数：<n>
- 单题超时：<seconds>
- 重试策略：<retry_policy>
- 判题方式：keyword + semantic + process signals，必要时参考 LLM-Judge

## 2. 测试集字段说明

| 字段 | 含义 | 备注 |
|---|---|---|
| id | <说明> | <实际字段映射> |
| question | <说明> | <实际字段映射> |
| expected | <说明> | <实际字段映射> |
| keywords | <说明> | <实际字段映射> |
| category/type/tags | <说明> | <实际字段映射> |

## 3. 总体结果

| 指标 | 数值 |
|---|---:|
| 总题数 | 105 |
| PASS | <n> |
| BORDERLINE | <n> |
| FAIL | <n> |
| 严格通过率 | <PASS/total>% |
| 宽松通过率 | <PASS+BORDERLINE/total>% |
| 平均耗时 | <ms> |
| P95 耗时 | <ms> |
| 超时数 | <n> |
| 服务错误数 | <n> |

## 4. 分类统计

| 分类 | 总数 | PASS | BORDERLINE | FAIL | 严格通过率 | 主要问题 |
|---|---:|---:|---:|---:|---:|---|
| fee | <n> | <n> | <n> | <n> | <rate>% | <summary> |
| non-fee | <n> | <n> | <n> | <n> | <rate>% | <summary> |
| <category> | <n> | <n> | <n> | <n> | <rate>% | <summary> |

## 5. 过程信号汇总

| 信号 | 数量 | 说明 |
|---|---:|---|
| 拒答 | <n> | <summary> |
| 空壳回答 | <n> | <summary> |
| fee 类题目 | <n> | <summary> |
| fee 表来源召回 | <n> | <summary> |
| 表格输出 | <n> | <summary> |
| 编码异常 | <n> | <summary> |
| 混用风险 | <n> | <summary> |
| 超时 | <n> | <summary> |
| 服务错误 | <n> | <summary> |

## 6. 失败与边界题明细

| id | question 摘要 | result | failure_category | suspected_stage | 关键证据 | 修复建议 |
|---|---|---|---|---|---|---|
| <id> | <summary> | FAIL | refusal | generation/retrieval | <evidence> | <fix> |

## 7. 费用类专项研判

- 实际识别 fee 类题目数量：<n>
- fee PASS：<n>
- fee BORDERLINE：<n>
- fee FAIL：<n>
- 费用表召回情况：<summary>
- 金额/单位/条件准确性：<summary>
- 混用风险：<summary>
- 专项结论：fee 类通过 / fee 类边界可接受 / fee 类需阻塞修复

## 8. 与历史 v6 95 题基线对比

| 版本/测试集 | 题数 | 判题方式 | 报出通过率 | 修正估计 | 主要问题 |
|---|---:|---|---:|---:|---|
| v6 | 95 | <method> | <value_or_unknown> | <value_or_unknown> | <summary> |
| v7 | 105 | keyword + semantic + process signals | <value> | <value_if_applicable> | <summary> |

说明：

```text
如使用 kb2_66test_v3.py 的 keyword 判题结果，需要注明：真实能力约等于脚本报出通过率 + 40pp，该修正为历史经验估计，不替代逐题语义判定。
```

## 9. 最终研判

### 9.1 整体结论

```text
<整体是否通过、主要问题域、是否可上线/可回归/需阻塞修复>
```

### 9.2 主要问题域

```text
1. <问题域 1>
2. <问题域 2>
3. <问题域 3>
```

### 9.3 修复优先级

| 优先级 | 问题 | 影响范围 | 建议动作 | 预期收益 | 验证方式 |
|---|---|---|---|---|---|
| P0 | <problem> | <scope> | <action> | <benefit> | <validation> |
| P1 | <problem> | <scope> | <action> | <benefit> | <validation> |
| P2 | <problem> | <scope> | <action> | <benefit> | <validation> |

## 10. 下次迭代建议

```text
1. <建议 1>
2. <建议 2>
3. <建议 3>
```

## 11. 附录：逐题过程记录

���“每题记录模板”完整列出 105 题记录，或链接到完整 JSONL 结果文件：

```text
<path_to_jsonl>
```
```

---

## 执行约束

执行 agent 必须遵守以下约束：

```text
不得只输出最终通过率。
不得省略 answer 和 sources。
不得只依赖 keyword 命中判断 PASS/FAIL。
不得把 API 超时直接归为知识库内容失败。
不得在没有历史数据的情况下编造 v6 对比数字。
不得忽略 fee 类专项统计。
不得隐藏编码异常、拒答、空壳回答、来源混用等过程信号。
```

最终交付必须包含：

```text
1. 完整逐题过程记录
2. 分类统计
3. 失败/边界题逐题归因
4. v6 历史基线对比或明确说明无可核验历史数据
5. 整体最终研判
6. fee 类专项研判
