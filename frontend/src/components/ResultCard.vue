<template>
  <div class="result-card card">
    <div class="result-header">
      <span class="result-label">{{ label }}</span>
      <span v-if="cacheHit" class="badge cache-badge">{{ cacheHit }}</span>
      <button
        v-if="cacheHit"
        type="button"
        class="refresh-btn"
        @click="emit('refresh')"
        title="强制刷新，绕过缓存重新查询"
      >
        🔄 强制刷新
      </button>
    </div>
    <div class="result-body" v-html="renderedHtml"></div>
    <div v-if="suggestions" class="suggestion-panel">
      <div class="suggestion-title">{{ suggestionTitle }}</div>
      <button
        v-if="suggestions.refined_query"
        type="button"
        class="suggestion-query"
        @click="emit('search-suggestion', suggestions.refined_query)"
      >
        {{ suggestions.refined_query }}
      </button>
      <div v-if="suggestions.term_hints?.length" class="suggestion-section">
        <span class="suggestion-label">术语提示：</span>
        <span v-for="(hint, i) in suggestions.term_hints" :key="i" class="suggestion-term">
          「{{ hint.user_term }}」→「{{ hint.kb_term }}」
        </span>
      </div>
      <div v-if="suggestions.standard_hints?.length" class="suggestion-standards">
        <span class="suggestion-label">规范提醒：</span>
        <div v-for="(hint, i) in suggestions.standard_hints" :key="i" class="suggestion-standard-item">
          <span class="suggestion-standard-text">
            建议带上「{{ hint.title }}」搜索，结果更准确
          </span>
          <button
            type="button"
            class="suggestion-standard-query"
            @click="emit('search-suggestion', hint.recommended_query)"
          >
            {{ hint.recommended_query }}
          </button>
        </div>
      </div>
      <div v-if="suggestions.related_docs?.length" class="suggestion-docs">
        <span class="suggestion-label">相关文档：</span>
        <span v-for="(doc, i) in suggestions.related_docs" :key="i" class="suggestion-doc-item">
          {{ doc.title }}
        </span>
      </div>
      <div v-if="suggestions.follow_up_questions?.length" class="suggestion-chips">
        <span class="suggestion-label">也可以试试：</span>
        <button
          v-for="(fq, i) in suggestions.follow_up_questions"
          :key="i"
          type="button"
          class="suggestion-chip"
          @click="emit('search-suggestion', fq)"
        >
          {{ fq }}
        </button>
      </div>
    </div>
    <div v-if="sources.length" class="result-sources">
      <h4 class="sources-title">来源 ({{ dedupedSources.length }})</h4>
      <div class="source-list">
        <div v-for="(src, i) in dedupedSources" :key="i" class="source-item">
          <span class="source-index">{{ i + 1 }}</span>
          <div class="source-content">
          <div class="source-header">
            <router-link
              v-if="src.doc_id"
              :to="'/documents/' + src.doc_id"
              class="source-doc-link"
            >
              {{ src.doc }}
            </router-link>
            <span v-else class="source-doc">{{ src.doc }}</span>
            <span class="source-badges">
              <span v-if="src.fee_tier" class="badge fee-badge">{{ src.fee_tier }}</span>
              <span v-if="src.keyword_matches && queryKeywords" class="badge kw-badge">{{ src.keyword_matches }}/{{ queryKeywords.length }}关键词</span>
              <span v-if="src.score" class="source-score">{{ src.score }}</span>
            </span>
          </div>
          <div v-if="src.text" class="source-text" v-html="highlightKeywords(cleanSourceText(src.text))"></div>
          <span v-else-if="src.chunk" class="source-chunk-info">{{ src.chunk }}</span>
          </div>
        </div>
      </div>
    </div>
    <div v-if="standardContents?.length" class="standard-contents">
      <h4 class="standard-title">📋 命中规范原文 ({{ standardContents.length }})</h4>
      <div v-for="std in standardContents" :key="std.doc_id" class="standard-item">
        <button
          type="button"
          class="standard-header"
          @click="toggleStandard(std.doc_id)"
        >
          <span class="standard-arrow">{{ expandedStds.has(std.doc_id) ? '▾' : '▸' }}</span>
          <span class="standard-name">{{ std.title }}</span>
          <span class="standard-meta">{{ formatSize(std.total_chars) }} · {{ std.sections_count }}章节</span>
        </button>
        <div v-if="expandedStds.has(std.doc_id)" class="standard-body">
          <div v-if="loadingStds.has(std.doc_id)" class="standard-loading">加载中...</div>
          <div v-else-if="stdTexts[std.doc_id]" class="standard-text" v-html="renderStdText(stdTexts[std.doc_id])"></div>
          <div v-else class="standard-empty">暂无内容</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { Source, QuerySuggestions } from '@/services/query'
import api from '@/services/api'

interface StandardContent {
  title: string
  doc_id: string
  total_chars: number
  sections_count: number
  preview: string
}

const emit = defineEmits<{ (e: 'search-suggestion', query: string): void; (e: 'refresh'): void }>()

const props = withDefaults(
  defineProps<{
    label?: string
    content: string
    sources?: Source[]
    cacheHit?: string
    suggestions?: QuerySuggestions | null
    standardContents?: StandardContent[]
    bank?: string
    queryKeywords?: string[]
  }>(),
  {
    label: '回答',
    sources: () => [],
    cacheHit: '',
    suggestions: null,
    standardContents: () => [],
    bank: 'all',
    queryKeywords: () => [],
  },
)

const expandedStds = ref<Set<string>>(new Set())
const loadingStds = ref<Set<string>>(new Set())
const stdTexts = ref<Record<string, string>>({})

const renderedHtml = computed(() => {
  if (!props.content) return ''
  try {
    const cleaned = props.content
      .replace(/~~([^~]+)~~/g, '$1')
      .replace(/(?<!\$)\$([^$\n]+?)\$(?!\$)/g, '$1')
      .replace(/\$\$([\s\S]*?)\$\$/g, '$1')
    return DOMPurify.sanitize(marked.parse(cleaned) as string)
  } catch {
    return DOMPurify.sanitize(props.content)
  }
})

const suggestionTitle = computed(() => {
  const s = props.suggestions
  if (s?.refined_query || s?.term_hints?.length || s?.related_docs?.length) {
    return '💡 没有直接命中，试试这样问'
  }
  return '💡 相关规范与追问'
})

/** 来源去重（防御性，后端已按 doc_id 去重） */
const dedupedSources = computed(() => {
  const seen = new Set<string>()
  return props.sources.filter(src => {
    const key = (src.doc_id || src.doc) + (src.text || '').slice(0, 50)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
})

/** 清洗来源文本：剥离 [文档:xxx][章节:xxx] 前缀、HTML 实体、strikethrough 和 LaTeX */
function cleanSourceText(raw: string): string {
  return raw
    .replace(/^\[文档:[^\]]+\](?:\[章节:[^\]]+\])?\s*/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&lt;/g, '<')
    .replace(/&amp;/g, '&')
    .replace(/<[^>]*>/g, '')
    .replace(/~~([^~]+)~~/g, '$1')   /* MinerU strikethrough → plain text */
    .replace(/(?<!\$)\$([^$\n]+?)\$(?!\$)/g, '$1')  /* inline $...$ → plain */
    .replace(/\$\$([\s\S]*?)\$\$/g, '$1')             /* display $$...$$ → plain */
    .replace(/~([^~]+)~/g, '$1')        /* single tilde strikethrough variant */
    .trim()
    .substring(0, 500)
}

/** 高亮来源文本中的关键词 — SourceCard 证据级可解释性 */
function highlightKeywords(text: string): string {
  const kws = props.queryKeywords
  if (!kws || !kws.length) return text
  const escaped = kws.filter(k => k.length > 1).map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  if (!escaped.length) return text
  const pattern = new RegExp(`(${escaped.join('|')})`, 'gi')
  return text.replace(pattern, '<mark class="kw-highlight">$1</mark>')
}

function formatSize(chars: number): string {
  if (chars < 1024) return `${chars}B`
  if (chars < 1024 * 1024) return `${(chars / 1024).toFixed(1)}KB`
  return `${(chars / (1024 * 1024)).toFixed(1)}MB`
}

function toggleStandard(docId: string) {
  if (expandedStds.value.has(docId)) {
    expandedStds.value.delete(docId)
  } else {
    expandedStds.value.add(docId)
    loadStandardText(docId)
  }
}

async function loadStandardText(docId: string) {
  if (stdTexts.value[docId] || loadingStds.value.has(docId)) return

  loadingStds.value.add(docId)
  try {
    const { data } = await api.get(`/query/standard-full/${docId}`, {
      params: { bank: props.bank || 'all' },
    })
    stdTexts.value[docId] = data.full_text || ''
  } catch (e) {
    console.error('Failed to load standard text:', e)
    stdTexts.value[docId] = '加载失败，请重试'
  } finally {
    loadingStds.value.delete(docId)
  }
}

function renderStdText(text: string): string {
  if (!text) return ''
  try {
    return DOMPurify.sanitize(marked.parse(text) as string)
  } catch {
    return DOMPurify.sanitize(text.replace(/\n/g, '<br>'))
  }
}
</script>

<style scoped>
.result-card {
  border: 1px solid var(--border);
  background: white;
  padding: 1.25rem;
  border-radius: var(--radius);
}

.result-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.result-label {
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--fg);
}

.cache-badge {
  font-size: 0.65rem;
  color: var(--success);
  border-color: var(--success);
}

.refresh-btn {
  font-size: 0.7rem;
  padding: 0.15rem 0.5rem;
  margin-left: 0.5rem;
  border: 1px solid var(--accent);
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  border-radius: var(--radius-sm);
  vertical-align: middle;
}

.refresh-btn:hover {
  background: var(--accent);
  color: var(--fg-on-accent);
}

.result-body {
  font-size: 0.9rem;
  line-height: 1.7;
  color: var(--fg);
  overflow-x: auto;
  max-width: 100%;
}

.result-body :deep(h1),
.result-body :deep(h2),
.result-body :deep(h3) {
  margin-top: 1rem;
  margin-bottom: 0.5rem;
  font-weight: 600;
}

.result-body :deep(p) {
  margin-bottom: 0.5rem;
}

.result-body :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.85em;
  background: var(--code-bg);
  padding: 0.1em 0.3em;
  border: 1px solid var(--code-border);
  border-radius: 3px;
}

.result-body :deep(pre) {
  background: var(--code-bg);
  border: 1px solid var(--code-border);
  padding: 0.75rem;
  overflow-x: auto;
  margin-bottom: 0.75rem;
  max-width: 100%;
}

.result-body :deep(ul),
.result-body :deep(ol) {
  padding-left: 1.5rem;
  margin-bottom: 0.5rem;
}

/* ── 表格样式（Markdown 表格展示优化） ── */
.result-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 0.75rem;
  font-size: 0.825rem;
  display: block;
  overflow-x: auto;
  max-width: 100%;
  -webkit-overflow-scrolling: touch;
  /* 移除 table 级 nowrap：长单元格内容自动换行，避免宽表在微信端被截断 */
}

.result-body :deep(th),
.result-body :deep(td) {
  border: 1px solid var(--border);
  padding: 0.45rem 0.7rem;
  text-align: left;
  min-width: 80px;
}

.result-body :deep(th) {
  background: var(--bg-alt);
  font-weight: 600;
  color: var(--fg);
  white-space: nowrap;
}

.result-body :deep(td) {
  color: var(--fg-secondary);
  /* 数据单元格内容过长时允许换行（长费率表数字/描述不截断） */
  word-break: break-word;
  overflow-wrap: anywhere;
}

.result-body :deep(tbody tr:hover) {
  background: var(--accent-light);
}

/* ── 引用块 ── */
.result-body :deep(blockquote) {
  border-left: 3px solid var(--accent);
  padding: 0.4rem 0.8rem;
  margin: 0.5rem 0;
  color: var(--fg-muted);
  background: var(--bg-alt);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}

/* ── 图片 ── */
.result-body :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: var(--radius);
  margin: 0.5rem 0;
}

.result-sources {
  margin-top: 1rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border);
}

.sources-title {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--fg-muted);
  margin-bottom: 0.5rem;
}

.source-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.source-item {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  gap: 0.5rem;
  font-size: 0.75rem;
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--border);
  background: var(--bg-alt);
  border-radius: var(--radius);
  min-width: 0;
  flex: 1 1 240px;
}

/* 来源编号圆形徽章 */
.source-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  font-size: 0.65rem;
  font-weight: 700;
  background: var(--accent);
  color: var(--fg-on-accent);
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 2px;
}

/* 来源内容容器（编号右侧） */
.source-content {
  flex: 1;
  min-width: 0;
}

.source-header {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.source-doc {
  color: var(--fg-muted);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-doc-link {
  color: var(--accent);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-decoration: none;
}

.source-doc-link:hover {
  text-decoration: underline;
}

.source-score {
  font-size: 0.65rem;
  color: var(--accent);
}

.source-text {
  font-size: 0.7rem;
  color: var(--fg-muted);
  line-height: 1.5;
  max-height: 6rem;
  overflow-y: auto;
  word-break: break-word;
}

.source-chunk-info {
  font-size: 0.7rem;
  color: var(--fg-muted);
  font-style: italic;
}

.suggestion-panel {
  margin-top: 1rem;
  padding: 0.75rem;
  border: 1px solid var(--border);
  background: var(--bg-alt);
  border-radius: var(--radius);
}

.suggestion-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--fg);
  margin-bottom: 0.5rem;
}

.suggestion-query {
  display: block;
  width: 100%;
  text-align: left;
  padding: 0.4rem 0.6rem;
  margin-bottom: 0.4rem;
  font-size: 0.8rem;
  color: var(--accent);
  background: white;
  border: 1px solid var(--accent);
  border-radius: var(--radius);
  cursor: pointer;
}

.suggestion-query:hover {
  background: var(--accent);
  color: white;
}

.suggestion-section {
  font-size: 0.75rem;
  color: var(--fg-muted);
  margin-bottom: 0.35rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 0.5rem;
}

.suggestion-label {
  font-weight: 600;
  color: var(--fg);
}

.suggestion-term {
  color: var(--accent);
}

.suggestion-standards {
  font-size: 0.75rem;
  color: var(--fg-muted);
  margin-bottom: 0.45rem;
}

.suggestion-standard-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  margin-top: 0.25rem;
  padding: 0.45rem 0.55rem;
  background: white;
  border: 1px dashed var(--accent);
  border-radius: var(--radius);
}

.suggestion-standard-text {
  color: var(--fg-muted);
}

.suggestion-standard-query {
  align-self: flex-start;
  font-size: 0.72rem;
  padding: 0.2rem 0.5rem;
  color: var(--accent);
  background: var(--bg-alt);
  border: 1px solid var(--accent);
  border-radius: 1rem;
  cursor: pointer;
}

.suggestion-standard-query:hover {
  background: var(--accent);
  color: white;
}

.suggestion-docs {
  font-size: 0.75rem;
  color: var(--fg-muted);
  margin-bottom: 0.35rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 0.5rem;
}

.suggestion-doc-item {
  color: var(--fg-muted);
  padding: 0.1rem 0.35rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 0.7rem;
}

.suggestion-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  align-items: center;
}

.suggestion-chip {
  font-size: 0.72rem;
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--border);
  background: white;
  border-radius: 1rem;
  cursor: pointer;
  color: var(--fg-muted);
}

.suggestion-chip:hover {
  border-color: var(--accent);
  color: var(--accent);
}

/* ── 规范原文折叠面板 ── */
.standard-contents {
  margin-top: 1rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border);
}

.standard-title {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--fg-muted);
  margin-bottom: 0.5rem;
}

.standard-item {
  margin-bottom: 0.5rem;
}

.standard-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.5rem 0.75rem;
  background: var(--bg-alt);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  cursor: pointer;
  text-align: left;
  font-size: 0.8rem;
}

.standard-header:hover {
  border-color: var(--accent);
}

.standard-arrow {
  color: var(--fg-muted);
  font-size: 0.7rem;
}

.standard-name {
  flex: 1;
  color: var(--fg);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.standard-meta {
  font-size: 0.7rem;
  color: var(--fg-muted);
}

.standard-body {
  margin-top: 0.25rem;
  padding: 0.75rem;
  background: white;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  max-height: 500px;
  overflow-y: auto;
}

.standard-loading {
  text-align: center;
  color: var(--fg-muted);
  font-size: 0.8rem;
  padding: 1rem;
}

.standard-text {
  font-size: 0.85rem;
  line-height: 1.6;
  color: var(--fg);
}

.standard-text :deep(p) {
  margin-bottom: 0.5rem;
}

.standard-text :deep(h1),
.standard-text :deep(h2),
.standard-text :deep(h3) {
  margin-top: 0.75rem;
  margin-bottom: 0.4rem;
  font-weight: 600;
}

.standard-empty {
  text-align: center;
  color: var(--fg-muted);
  font-size: 0.8rem;
  padding: 1rem;
}

/* ── SourceCard 证据级可解释性 ── */
.source-badges {
  display: inline-flex;
  gap: 0.35rem;
  align-items: center;
}
.badge {
  font-size: 0.6rem;
  padding: 0.1rem 0.35rem;
  border-radius: var(--radius-sm);
  font-weight: 600;
  white-space: nowrap;
}
.fee-badge {
  background: var(--warning-bg);
  color: var(--warning);
  border: 1px solid var(--warning);
}
.kw-badge {
  background: var(--info-bg);
  color: var(--accent);
  border: 1px solid var(--accent);
}
.source-text :deep(mark.kw-highlight) {
  background: var(--warning);
  color: white;
  padding: 0 1px;
  border-radius: 2px;
}
.source-text :deep(mark.kw-highlight)::before,
.source-text :deep(mark.kw-highlight)::after {
  content: none;
}
</style>
