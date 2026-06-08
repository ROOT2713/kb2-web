<template>
  <div class="result-card card">
    <div class="result-header">
      <span class="result-label">{{ label }}</span>
      <span v-if="cacheHit" class="badge cache-badge">{{ cacheHit }}</span>
    </div>
    <div class="result-body" v-html="renderedHtml"></div>
    <div v-if="sources.length" class="result-sources">
      <h4 class="sources-title">来源</h4>
      <div class="source-list">
        <div v-for="(src, i) in sources" :key="i" class="source-item">
          <span class="source-doc">{{ src.doc }}</span>
          <span v-if="src.score" class="source-score">{{ src.score }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import type { Source } from '@/services/query'

const props = withDefaults(
  defineProps<{
    label?: string
    content: string
    sources?: Source[]
    cacheHit?: string
  }>(),
  {
    label: '回答',
    sources: () => [],
    cacheHit: '',
  },
)

const renderedHtml = computed(() => {
  if (!props.content) return ''
  try {
    return marked.parse(props.content) as string
  } catch {
    return props.content
  }
})
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
</style>
