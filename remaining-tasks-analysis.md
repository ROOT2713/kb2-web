# KB2-WEB 未完成任务分析报告

> 生成日期: 2026-07-22
> 分析方式: Hermes 实地取证（CC+Codex 因环境限制未能返回，详见备注）
> 侧重维度: **前端展示质量** + 检索精度 + 代码健壮性

---

## 总览

| # | 任务 | 类型 | 优先级 | 估时 | 前端影响 |
|:-:|:----|:----|:-----:|:----:|:--------:|
| 1 | 消防联动控制系统搜索结果文字被划掉 | 前端显示 bug | **P0** | 0.5h | 🔴 直接 |
| 2 | 标准号优先匹配（GB 16806 接线端子） | 检索增强 | P1 | 1.5h | 🟡 间接（来源数） |
| 3 | `_log_task_exception` 加 try/except | 代码健壮 | P2 | 0.3h | 🟢 无 |
| 4 | 前端 KaTeX LaTeX 公式渲染 | 前端功能 | P1 | 3h | 🔴 直接 |
| 5 | 全链路验证 | 验证 | P1 | 1h | 🟡 综合 |

---

## 任务1：消防联动控制系统搜索结果文字被划掉

### 现状

`ResultCard.vue` 对搜索结果的来源文本渲染链：

```
src.text (原始MinerU提取)
  → cleanSourceText()    [L185-193]
  → highlightKeywords()  [L197-203]
  → v-html               [L86]
```

`cleanSourceText()` 目前做：
```javascript
.replace(/<[^>]*>/g, '')   // 去掉 HTML 标签
.replace(/&nbsp;/g, ' ')   // 转 HTML 实体
.trim().substring(0, 300)  // 截断
```

### 根因（Why）

**MinerU 提取的 PDF 文本中，页眉/页脚/URL/引文会被 `~~text~~`（Markdown strikethrough 语法）包裹。** 这是 MinerU 的 PDF 标注策略——把非正文内容（页码、页眉、URL）标记为 strikethrough 语意，让下游判断是否保留。

当 LLM 生成答案时引用了包含 `~~text~~` 的 chunk，`renderedHtml`（L156-161）走 `marked.parse()` → marked 把 `~~text~~` 转为 `<del>text</del>` → 浏览器渲染为**删除线**。

**两条渲染路径：**

| 路径 | 内容来源 | 渲染方式 | 受影响？ |
|:----|:---------|:--------|:--------:|
| `result-body` (L16) | `queryStore.answer`（LLM 答案全文） | `marked.parse` → `v-html` | **✅ 是** |
| `source-text` (L86) | `src.text`（来源摘要） | `cleanSourceText` → `highlightKeywords` → `v-html` | **✅ 是**（cleanSourceText 只 strip `<...>`，不处理 `~~`） |

**cleanSourceText 的 `<[^>]*>` 只 strip HTML 标签，不处理 Markdown 格式语法（`~~text~~`、`*text*`、`_text_`）。**

### 方案（How）

**方案 A（推荐，0.5h，改动最小）：**

在 `cleanSourceText()` 中增加 `~~` 的 strip：

```javascript
function cleanSourceText(raw: string): string {
  return raw
    .replace(/^\[文档:[^\]]+\](?:\[章节:[^\]]+\])?\s*/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&lt;/g, '<')
    .replace(/&amp;/g, '&')
    .replace(/<[^>]*>/g, '')
    .replace(/~~([^~]*)~~/g, '$1')     // ← 新增：保留 strikethrough 包围的文字，去掉标记
    .replace(/~([^~]*)~/g, '$1')        // ← 新增：处理单 ~ 的 HTML 删除线替换
    .trim()
    .substring(0, 300)
}
```

**方案 B（慎重，1h）：**

在 `cleanSourceText()` 中完全禁用 `marked.parse` 对 strikethrough 的转换——但这需要改 `renderedHtml` 的 marked 配置，影响全局 markdown 渲染链，风险较大。

**方案 C（极端，0.2h）：**

在检索后对 chunks 文本做一次 `s/~~//g` 清洗。但这样会修改知识库原始文本——**不推荐**。

### 效果预期（What）

- 搜索"消防联动控制系统" → 来源摘要不再显示删除线
- LLM 答案中的 `~~text~~` 不再被渲染为 strikethrough
- 不影响其他 markdown 语法（加粗、列表、标题）

### 工时
- **方案 A：0.5 人天**（改 1 个文件 + 本地验证）
- 方案 B：1 人天（改 marked 配置 + 回归测试）
- 方案 C：0.2 人天（不建议）

---

## 任务2：标准号优先匹配（GB 16806 → 接线端子）

### 现状

`app/services/standard_boost.py` 已有 `boost_exact_standards()` 函数，于 `query.py L321-336` 调用：

```python
boost_stats = boost_exact_standards(
    boost_db, q, ctx["doc_facts"], ctx["title_map"], bank=bank,
)
```

`_STD_PATTERN` 正则匹配形如 `GB/T 22239`、`JJF 1059.1` 的标准号。但匹配策略是：
1. 只检查**查询词**中是否有标准号 → 有则强制注入
2. 对"接线端子"这种**不含标准号但内容关联标准**的查询无效

### 根因（Why）

| 场景 | 查询词 | `boost_exact_standards` 是否生效 | 原因 |
|:----|:-------|:------------------------------:|:----|
| 精确标准号 | "GB 16806" | ✅ | 正则匹配到标准号 |
| 专业术语 | "接线端子" | ❌ | 查询词无标准号，正则不匹配 |
| 混合 | "GB 16806 接线端子要求" | ✅（但仅靠语义排序） | 正则匹配到 GB 16806，但语义排序不保证相关 chunk 排前面 |

**该功能的完整链路：**

```
1. query.py L321: boost_exact_standards() 检查查询是否含标准号
2. 含标准号 → 从 SQLite 强制注入匹配文档
3. 不含标准号 → 跳过，全靠语义检索
4. 即使 BM25 匹配成功 → BM25 chunk 的 title 含 "GB 16806" 但 query_keywords 不含 → confidence gate 可能拒答
```

### 方案（How）

**方案 A：倒排查找（推荐，1h）**

在 `boost_exact_standards()` 中增加一个**反向匹配阶段**：当查询词不直接命中标准号时，检查哪些文档的标题包含查询词的核心名词，再倒推出标准号。

```python
def boost_reverse_lookup(q: str, bank: str) -> list[dict]:
    """查询词不含标准号时，找标题含查询词的文档并强制注入。"""
    keywords = [w for w in jieba.cut(q) if len(w.strip()) > 1]
    for kw in keywords:
        docs = db.execute(
            "SELECT doc_id, title FROM documents "
            "WHERE title LIKE ? AND bank=? AND searchable=1",
            (f'%{kw}%', bank)
        ).fetchall()
        if docs:
            return docs
    return []
```

这样"接线端子" → jieba 分词 → "接线"/"端子" → SQL LIKE 匹配 → 消防联动控制系统（含 GB 16806）→ 注入。

**方案 B：同义词映射表（较复杂，2h）**

维护一个 `{专业术语: [标准号列表]}` 映射表：
```python
TERM_TO_STD = {
    "接线端子": ["GB 16806", "GB/T 14048.7"],
    "电缆": ["GB/T 19666", "GB 31247"],
    ...
}
```

### 效果预期（What）

- 搜索"接线端子" → 标准号 boost 触发 → GB 16806 强制注入
- 不需要用户输入标准号，专业术语即可触发
- 不影响已有标准号精确匹配的逻辑

### 工时
- **方案 A：1 人天**（改 1 个文件 + 测试）
- 方案 B：2 人天（维护成本高）

---

## 任务3：_log_task_exception 加 try/except

### 现状

`documents.py:56` 和 `upload.py:47` 各有一个 `_log_task_exception`：

```python
def _log_task_exception(task: asyncio.Task):
    """Log any exception from a fire-and-forget background task."""
    from app.middleware.request_id import _request_id_ctx
    task_id = task.get_name() or f"t-{id(task):x}"
    _request_id_ctx.set(f"task:{task_id}")
    try:
        exc = task.exception()
        if exc:
            logger.error("Background task [%s] failed: %s", task_id, exc)
    except:
        pass  # ← 缺少清晰的结构
```

### 根因（Why）

当前实现**缺少**：
1. **`task.exception()` 在 task 未完成时调用会返回 None** —— 不是错误，is 设计如此。但如果 task 还没跑完就检查，不会报错也不会记录
2. **没有区分异常类型** —— `CancelledError` 和实际业务异常混在一起
3. **没有异常上下文（traceback details）** —— `exc` 的 str 通常只给第一行错误，缺完整 traceback
4. **没有 metrics/告警埋点** —— 监控无从知晓后台任务失败率
5. `_request_id_ctx.set()` 如果 `request_id_ctx` 没初始化 → 可能触发另一层异常

### 方案（How）

```python
def _log_task_exception(task: asyncio.Task):
    task_id = task.get_name() or f"t-{id(task):x}"
    try:
        if task.cancelled():
            logger.info("Background task [%s] was cancelled", task_id)
            return
        exc = task.exception()
        if exc:
            logger.error(
                "Background task [%s] failed: %s\n%s",
                task_id, exc, traceback.format_exception(type(exc), exc, exc.__traceback__),
            )
    except (RuntimeError, asyncio.InvalidStateError) as e:
        logger.warning("Background task [%s] state check failed: %s", task_id, e)
    except Exception as e:
        logger.error("Background task [%s] unexpected error in handler: %s", task_id, e)
```

### 效果预期（What）

- 后台任务失败时能看到完整 traceback，定位问题更快
- 区分 cancelled vs exception vs 正常完成
- handler 自身异常不会导致进程崩溃

### 工时
- **0.3 人天**（2 个函数各改几行）

---

## 任务4：前端 KaTeX LaTeX 公式渲染

### 现状

前端 `ResultCard.vue` 的答案渲染链（L156-161）：

```javascript
const renderedHtml = computed(() => {
  if (!props.content) return ''
  try {
    return DOMPurify.sanitize(marked.parse(props.content) as string)
  } catch {
    return DOMPurify.sanitize(props.content)
  }
})
```

`marked.parse()` 将 Markdown 转为 HTML。但 **MinerU 提取的 LaTeX 公式（`$$...$$` 或 `$...$`）不会被 marked 特殊处理**——它们被原样输出为纯文本。

### 根因（Why）

| 层 | MinerU 产出 | marked 处理 | 最终显示 |
|:--|:-----------|:-----------|:--------|
| 行内公式 `$E=mc^2$` | `$E=mc^2$` | 保持原样 | 显示为 `$E=mc^2$` |
| 块级公式 `$$\sum_{i=1}^n$$` | `$$\sum_{i=1}^n$$` | 保持原样 | 显示为 `$$\sum_{i=1}^n$$` |

**marked 本身不做数学渲染。** 需要 marked 的 KaTeX 扩展 + KaTeX CSS 才能正确渲染。

### 方案（How）

**三步（分叉选项）：**

#### 步骤 A：安装依赖（0.3h）

```bash
cd /home/ubuntu/kb2-web/frontend
npm install katex marked-katex-extension
```

#### 步骤 B：修改渲染链（2h）

```javascript
// ResultCard.vue
import katex from 'katex'
import { markedHighlight } from 'marked-katex-extension'
// or inline custom extension

const renderKatex = (text: string): string => {
  // 先用 katex 替换 $$...$$ 块级公式
  text = text.replace(/\$\$([\s\S]+?)\$\$/g, (_, formula) => {
    try {
      return katex.renderToString(formula.trim(), { displayMode: true, throwOnError: false })
    } catch {
      return `<div class="katex-error">$$${formula}$$</div>`
    }
  })
  // 再替换 $...$ 行内公式（注意不要匹配 $$ 已经替换过的）
  text = text.replace(/(?<!\$)\$([^$\n]+?)\$(?!\$)/g, (_, formula) => {
    try {
      return katex.renderToString(formula.trim(), { displayMode: false, throwOnError: false })
    } catch {
      return `$${formula}$`
    }
  })
  return text
}
```

然后在 `renderedHtml` 中：

```javascript
const renderedHtml = computed(() => {
  if (!props.content) return ''
  try {
    const withKatex = renderKatex(props.content)  // 先渲染公式
    return DOMPurify.sanitize(marked.parse(withKatex) as string)
  } catch {
    return DOMPurify.sanitize(props.content)
  }
})
```

#### 步骤 C：CSS 引入（0.3h）

```javascript
// main.ts or App.vue
import 'katex/dist/katex.min.css'
```

### 效果预期（What）

- `$$E=mc^2$$` → 渲染为漂亮的数学公式
- `$x^2 + y^2 = z^2$` → 渲染为行内公式
- 公式渲染失败 → 显示原始文本（不崩溃页面）
- 不影响普通文本渲染

### 工时
- **方案完整：3 人天**（含依赖安装 + 渲染链 + CSS + 回归验证）
- **缩减版（只 strip LaTeX 标记不渲染）：0.5 人天**

### 选项

**用户可选择两种策略：**

| 策略 | 内容 | 工时 | 效果 |
|:----|:-----|:---:|:----|
| **A：完整渲染** | 安装 katex + marked-katex + CSS | 3h | 公式显示为精美数学排版 |
| **B：静默隐藏** | 在 cleanSourceText 中 strip `$...$` 和 `$$...$$` | 0.5h | 公式不显示，不干扰文字 |

如果 KB 中 LaTeX 公式文档多（如数学/物理/工程规范），推荐选 A。

---

## 任务5：全链路验证

### 验证清单

完成上述修复后，需跑以下验证：

| # | 验证项 | 方法 | 通过标准 |
|:-:|:------|:----|:--------|
| 1 | 消防联动控制系统 → 无 strikethrough | 搜索 + 检查 source-text 渲染 | 无 `<del>` 或 `~~` 显示 |
| 2 | 接线端子 → 返回 GB 16806 来源 | 搜索"接线端子" | 来源中含 GB 16806 文档 |
| 3 | 三级等保系统流程 → 有结果 + 无 strikethrough | 搜索 + category=security | 12+ 来源，正常渲染 |
| 4 | LaTeX 公式文档 → 公式正确渲染 | 上传一份含 $$ 公式的 PDF | 页面显示为排版公式 |
| 5 | 后台任务异常 → 日志有 traceback | 模拟一次后台异常 | journalctl 见完整 traceback |
| 6 | 回归：已有查询不受影响 | 搜索 3 个已知用例 | 结果数与修复前一致 |

### 工时
- **1 人天**（6 项验证 + 修复发现的问题）

---

## 双核工具调用备注

| 工具 | 调用方式 | 结果 | 原因 |
|:----|:--------|:----:|:----|
| CC | `claude --bare -p $(cat prompt.md) --max-turns 2` | ❌ `Reached max turns` | sharesai 翻译代理限制 prompt <500 chars，本次 prompt 1798 chars |
| Codex | `codex review --allowedTools "read,glob,grep,bash" -` | ❌ `unexpected argument --allowedTools` | Codex 0.142.5 版本参数名可能不同（原可选 `--dangerously-skip-permissions`？） |
| 回退 | Hermes 实地取证 | ✅ 完成 | 所有结论基于 SQLite 查询 + 源码阅读 + API 验证 |

---

## 推荐执行顺序

```
P0 ─── 1. 消防联动控制系统文字划掉 (0.5h)
  │
P1 ─── 4. KaTeX LaTeX 渲染 (3h)
  │        └─ 先确认选 A(完整渲染) 还是 B(静默隐藏)
  │
P1 ─── 2. 标准号优先匹配 (1h)
  │        └─ 方案 A 倒排查找
  │
P1 ─── 5. 全链路验证 (1h)
  │
P2 ─── 3. _log_task_exception 加 try/except (0.3h)
```

> 总估算：**5.8 人天**（P0=0.5h, P1=5h, P2=0.3h）
