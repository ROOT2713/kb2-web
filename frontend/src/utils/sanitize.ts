import DOMPurify from 'dompurify'

/**
 * 全局唯一的 HTML 消毒入口。
 *
 * 【为什么必须集中在这里】kb2-web 有 3 条 v-html 链（回答正文 / 来源文本 / 规范原文）。
 * 2026-09-17 之前「来源文本」那条链漏了消毒，靠 cleanSourceText 的黑名单正则兜底 ——
 * 实测可被「未闭合标签 + 后续插入的 <mark> 提供闭合 >」绕过执行 onerror。
 * 统一走本函数后，任何链路都不可能再绕过消毒。
 *
 * 【为什么用 FORBID 而非收紧 ALLOWED_TAGS】回答正文要渲染 Markdown（表格/标题/链接）、
 * 需要保留 <img>；用默认白名单才能保住既有渲染效果。危险面集中在
 * 「事件处理器 + 可执行/可嵌入容器 + 表单家族 + SVG/MathML」，用 FORBID_TAGS/FORBID_ATTR
 * 精确切除。事件处理器（onerror/onload/...）与 javascript: 协议由 DOMPurify 默认剥离，
 * 无需另行声明（已有回归锁覆盖）。
 */

/**
 * 基础禁列表 —— 三条渲染链共用。
 *
 * 三类：
 *   ① 可执行 / 可嵌入容器：script style iframe object embed link meta base
 *   ② 表单家族（口径统一）：form input button textarea select optgroup option
 *      datalist fieldset legend output
 *      —— 回答正文由 Markdown 生成、来源文本是纯文本，永远不需要表单元素，
 *      全家族禁掉可消除「钓鱼表单 / 输入劫持」面，且无功能损失。
 *   ③ SVG / MathML：svg math
 *      —— 二者是 mXSS（mutation XSS）历史重灾区（DOMPurify 自身多个 CVE 源于
 *      命名空间切换导致的「消毒后又被浏览器重新解析成可执行结构」）。Markdown
 *      不产出这两个命名空间，实测禁掉后既有渲染零变化。
 */
const BASE_FORBID_TAGS = [
  // ① 可执行 / 可嵌入容器
  'script',
  'style',
  'iframe',
  'object',
  'embed',
  'link',
  'meta',
  'base',
  // ② 表单家族（口径统一：不再只禁 form/input/button/textarea 四个）
  'form',
  'input',
  'button',
  'textarea',
  'select',
  'optgroup',
  'option',
  'datalist',
  'fieldset',
  'legend',
  'output',
  // ③ SVG / MathML（mXSS 面）
  'svg',
  'math',
]

/**
 * 来源文本链额外禁的媒体标签。
 *
 * 【为什么在这里可以禁、在回答正文链不能禁】
 *   来源文本链是「加工 + 消毒」链：cleanSourceText 会用黑名单 `<[^>]*>` 删除一切
 *   **含字面 `>`** 的标签 —— 也就是**所有正常闭合的标签都会被删掉**，只有未闭合的
 *   残片能存活。因此来源链里正常 `<img src="/static/fig1.png">` 本来就不显示，
 *   额外禁媒体标签**零功能损失**（实测复核）。
 *   而回答正文链来自 Markdown，`![alt](url)` 必须正常显示图片 ⇒ 该链不能禁。
 *
 * 禁掉的意义：消除「未闭合媒体标签 + 关键词」组合下的远程资源加载面
 * （tracking pixel / 探测请求）。
 */
const SOURCE_EXTRA_FORBID_TAGS = ['img', 'video', 'audio', 'source', 'track']

export interface SanitizeOptions {
  /**
   * 仅供来源文本链使用：额外禁止媒体标签（img/video/audio/source/track）。
   * 实测该链的正常闭合媒体标签本就被 cleanSourceText 删除 ⇒ 无功能损失。
   */
  forbidMedia?: boolean
}

/**
 * 每次都构造全新 config 对象。
 *
 * 【为什么不复用模块级常量】DOMPurify 的 `_parseConfig` 会**向传入的 config 对象
 * 写回**内部派生字段（ALLOWED_TAGS / ALLOWED_ATTR 等）。复用同一个对象会让上一次
 * 调用的派生结果污染下一次；且 ESM 是严格模式，对冻结对象写入会直接抛 TypeError。
 * 每次新建的代价只是几个对象字面量，与渲染开销相比可忽略。
 */
function makeConfig(opts?: SanitizeOptions) {
  return {
    FORBID_TAGS: opts?.forbidMedia
      ? [...BASE_FORBID_TAGS, ...SOURCE_EXTRA_FORBID_TAGS]
      : BASE_FORBID_TAGS,
    FORBID_ATTR: ['style'],
    ALLOW_DATA_ATTR: false,
  }
}

/**
 * 消毒 HTML 字符串。空输入返回空串。
 *
 * 用点：必须作为渲染链的**最后一步**（先拼装/高亮，再消毒）。
 * 反例：`highlightKeywords(sanitizeHtml(text))` 是错的 —— 高亮会再次注入 HTML。
 *
 * 注：`String(...)` 是显式归一化 —— DOMPurify 的类型定义在「显式传 Config」
 * 的重载下可能标注返回 TrustedHTML，实际未开 RETURN_TRUSTED_TYPE 时返回 string。
 *
 * 【关于 a[target=_blank] 的 tabnabbing（勿再加 hook）】
 * 2026-09-17 加固时评估过「给 target=_blank 强制加 rel=noopener noreferrer」。
 * 实测（jsdom + DOMPurify 3.x）：`<a href="x" target="_blank">` 消毒后输出
 * `<a href="x">` —— **`target` 属性本身就被 DOMPurify 默认剥离**（该项目为防
 * tabnabbing 特意未把 target 放进默认 ALLOWED_ATTR）。既然 target 不存在，
 * 就没有 window.opener 暴露面，加 afterSanitizeAttributes hook 是**永不触发的
 * 死代码**（本仓回归锁 `target 被默认剥离` 守护该结论）。若将来有人把 target
 * 加进 ALLOWED_ATTR，该回归锁会变红提醒。
 */
export function sanitizeHtml(html: string, opts?: SanitizeOptions): string {
  if (!html) return ''
  return String(DOMPurify.sanitize(html, makeConfig(opts)))
}
