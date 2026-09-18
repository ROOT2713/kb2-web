/**
 * Markdown 渲染 —— 消除重复 + **锁定消毒顺序**（批次 E / 审计 A2）
 *
 * 修复前的问题
 * ----------
 * ① **LaTeX/删除线残留清理规则重复**：同一组规则写在 `ResultCard.vue` 的
 *    `renderedHtml`（回答正文链）与 `cleanSourceText`（来源文本链）两处，
 *    任何一处改规则、另一处不会跟着改。
 * ② **`sanitizeHtml(marked.parse(x))` 这个组合被手写了两遍**（回答正文、规范原文）。
 *    消毒必须**固定在最后一步**——一旦有人新写一处 Markdown 渲染忘了套消毒，
 *    就是新的 XSS 面。收归此处后，「marked + 消毒」的先后顺序由本模块保证。
 */

import { marked } from 'marked'
import { sanitizeHtml } from '@/utils/sanitize'

/**
 * 剥离 MinerU / LLM 输出里残留的 Markdown 片段：
 * `~~删除线~~`、行内 `$公式$`、块级 `$$公式$$`。
 *
 * ⚠️ 本函数**不含**单波浪号规则 `~([^~]+)~` —— 中文规范里 `3~5米，7~9米`
 * 会被它误当成删除线而**腐蚀数值**。调用方若确实需要，请自行显式追加。
 */
export function stripMarkdownArtifacts(text: string): string {
  return text
    .replace(/~~([^~]+)~~/g, '$1')
    .replace(/(?<!\$)\$([^$\n]+?)\$(?!\$)/g, '$1')
    .replace(/\$\$([\s\S]*?)\$\$/g, '$1')
}

/**
 * Markdown → 安全 HTML。
 *
 * 【顺序不可调换】`marked.parse` 的输出必须先经过 `sanitizeHtml` 才能进 `v-html`；
 * 顺序由本函数内部固定，调用方拿到的**已是消毒后**的 HTML。
 *
 * 降级：解析抛错时退回纯文本并把换行转 `<br>`（保证内容不丢）。
 */
export function renderMarkdown(text: string | null | undefined): string {
  if (!text) return ''
  try {
    return sanitizeHtml(marked.parse(text) as string)
  } catch {
    return sanitizeHtml(text.replace(/\n/g, '<br>'))
  }
}
