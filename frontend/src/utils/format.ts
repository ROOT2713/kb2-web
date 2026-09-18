/**
 * 格式化工具 —— 消除跨文件重复（批次 E / 审计 A2）
 *
 * 修复前的问题
 * ----------
 * `formatSize` 在 `ResultCard.vue` 与 `UploadView.vue` **各写一遍**，且已漂移：
 *   · ResultCard  → `${chars}B` / `${(chars/1024).toFixed(1)}KB`   （数字与单位无空格）
 *   · UploadView  → `${bytes} B` / `${(bytes/1024).toFixed(1)} KB` （有空格）
 * 同一概念两种显示。**更严重的是语义错标**：ResultCard 传入的是 `std.total_chars`
 * （标准原文**字符数**），却把单位写成 `B`（字节）—— 中文字符 1 字 ≈ 3 字节，
 * 数字与单位**双重不对**。据此拆成两个函数，各自语义明确、单位不混用。
 */

/**
 * 字节数 → 可读文件大小。显示格式固定为 `1.0 KB`（数字与单位间**有空格**）。
 * 仅用于真实字节量（`File.size`、上传总量）。
 */
export function formatFileSize(size: number): string {
  if (!Number.isFinite(size) || size < 0) return '—'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`
  return `${(size / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

/**
 * 字符数 → 可读字数。`10000` 以下给精确值（带千分位），以上换算「万字」。
 * 用于标准原文/文档正文字数（`total_chars`），**不要**与字节混用。
 */
export function formatCharCount(chars: number): string {
  if (!Number.isFinite(chars) || chars < 0) return '—'
  if (chars < 10000) return `${Math.round(chars).toLocaleString('zh-CN')} 字`
  return `${(chars / 10000).toFixed(1)} 万字`
}

/** 大数字 → `1.2K` / `3.4M`，用于计数概览（源数、章节数）。 */
export function formatCompactNumber(n: number): string {
  if (!Number.isFinite(n)) return '—'
  const abs = Math.abs(n)
  if (abs < 1000) return String(n)
  if (abs < 1_000_000) return `${(n / 1000).toFixed(1)}K`
  return `${(n / 1_000_000).toFixed(1)}M`
}

/**
 * ISO 时间串 → `YYYY-MM-DD`。后端返回的多为 `2026-09-05T12:00:00Z` 形式。
 * 空值给 `—`（原先各处裸写 `?.slice(0,10)`，空值会渲染出 `undefined`）。
 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso || typeof iso !== 'string') return '—'
  return iso.substring(0, 10)
}
