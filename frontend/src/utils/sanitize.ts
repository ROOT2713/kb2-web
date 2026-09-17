import DOMPurify from 'dompurify'

/**
 * 全局唯一的 HTML 消毒入口。
 *
 * 【为什么必须集中在这里】kb2-web 有 3 条 v-html 链（回答正文 / 来源文本 / 规范原文）。
 * 2026-09-17 之前「来源文本」那条链漏了消毒，靠 cleanSourceText 的黑名单正则兜底 ——
 * 实测可被「未闭合标签 + 后续插入的 <mark> 提供闭合 >」绕过执行 onerror。
 * 统一走本函数后，任何链路都不可能再绕过消毒。
 *
 * 【为什么用 FORBID 而非收紧 ALLOWED_TAGS】回答正文要渲染 Markdown（表格/标题/链接），
 * 用默认白名单才能保住既有渲染效果；危险面集中在「事件处理器 + 可执行/可嵌入容器」，
 * 用 FORBID_TAGS/FORBID_ATTR 精确切除。事件处理器（onerror/onload/...）由
 * DOMPurify 默认剥离，无需另行声明。
 */
const PURIFY_CONFIG = {
  FORBID_TAGS: [
    'script',
    'style',
    'iframe',
    'object',
    'embed',
    'form',
    'input',
    'button',
    'textarea',
    'link',
    'meta',
    'base',
  ],
  FORBID_ATTR: ['style'],
  ALLOW_DATA_ATTR: false,
}

/**
 * 消毒 HTML 字符串。空输入返回空串。
 *
 * 用点：必须作为渲染链的**最后一步**（先拼装/高亮，再消毒）。
 * 反例：`highlightKeywords(sanitizeHtml(text))` 是错的 —— 高亮会再次注入 HTML。
 *
 * 注：`String(...)` 是显式归一化 —— DOMPurify 的类型定义在「显式传 Config」
 * 的重载下可能标注返回 TrustedHTML，实际未开 RETURN_TRUSTED_TYPE 时返回 string。
 */
export function sanitizeHtml(html: string): string {
  if (!html) return ''
  return String(DOMPurify.sanitize(html, PURIFY_CONFIG))
}
