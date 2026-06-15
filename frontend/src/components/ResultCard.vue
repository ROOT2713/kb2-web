<template>
  <div class="result-card card">
    <div class="result-header">
      <span class="result-label">{{ label }}</span>
      <span v-if="cacheHit" class="badge cache-badge">{{ cacheHit }}</span>
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
      <h4 class="sources-title">来源</h4>
      <div class="source-list">
        <div v-for="(src, i) in sources" :key="i" class="source-item">
          <span class="source-doc">{{ src.doc }}</span>
          <span v-if="src.score" class="source-score">{{ src.score }}</span>
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
import type { Source, QuerySuggestions } from '@/services/query'
import api from '@/services/api'

interface StandardContent {
  title: string
  doc_id: string
  total_chars: number
  sections_count: number
  preview: string
}

const emit = defineEmits<{ (e: 'search-suggestion', query: string): void }>()

const props = withDefaults(
  defineProps<{
    label?: string
    content: string
    sources?: Source[]
    cacheHit?: string
    suggestions?: QuerySuggestions | null
    standardContents?: StandardContent[]
  }>(),
  {
    label: '回答',
    sources: () => [],
    cacheHit: '',
    suggestions: null,
    standardContents: () => [],
  },
)

const expandedStds = ref<Set<string>>(new Set())
const loadingStds = ref<Set<string>>(new Set())
const stdTexts = ref<Record<string, string>>({})

const renderedHtml = computed(() => {
  if (!props.content) return ''
  try {
    return marked.parse(props.content) as string
  } catch {
    return props.content
  }
})

const suggestionTitle = computed(() => {
  const s = props.suggestions
  if (s?.refined_query || s?.term_hints?.length || s?.related_docs?.length) {
    return '💡 没有直接命中，试试这样问'
  }
  return '💡 相关规范与追问'
})

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
    const { data } = await api.get(`/query/standard-full/${docId}`)
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
    return marked.parse(text) as string
  } catch {
    return text.replace(/\n/g, '<br>')
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

.result-body {
  font-size: 0.9rem;
  line-height: 1.7;
  color: var(--fg);
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
  background: var(--bg-alt);
  padding: 0.1em 0.3em;
  border: 1px solid var(--border);
}

.result-body :deep(pre) {
  background: var(--bg-alt);
  border: 1px solid var(--border);
  padding: 0.75rem;
  overflow-x: auto;
  margin-bottom: 0.75rem;
}

.result-body :deep(ul),
.result-body :deep(ol) {
  padding-left: 1.5rem;
  margin-bottom: 0.5rem;
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
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
  padding: 0.2rem 0.5rem;
  border: 1px solid var(--border);
  background: var(--bg-alt);
  border-radius: var(--radius);
}

.source-doc {
  color: var(--fg-muted);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-score {
  font-size: 0.65rem;
  color: var(--accent);
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
  border-radius: 3px;
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
</style>
