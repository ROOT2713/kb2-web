<template>
  <div class="extract-page">
    <h1 class="page-title">知识提取</h1>
    <p class="page-desc">输入主题，提取知识库中所有相关内容</p>

    <form class="extract-form" @submit.prevent="handleExtract">
      <div class="extract-input-row">
        <input
          v-model="topic"
          type="text"
          class="extract-input"
          placeholder="输入主题（如：防雷接地、数据中心验收）"
          :disabled="loading"
        />
        <button type="submit" class="primary" :disabled="!topic.trim() || loading">
          {{ loading ? '提取中...' : '提取' }}
        </button>
      </div>
      <div class="extract-options">
        <label class="option-label">
          <span>知识库</span>
          <select v-model="selectedBank" class="bank-select">
            <option value="all">全部知识库</option>
            <option v-for="bank in banks" :key="bank.key" :value="bank.key">
              {{ bank.name }}
            </option>
          </select>
        </label>
        <label class="option-label">
          <span>最低置信度</span>
          <input v-model.number="minConfidence" type="number" min="0" max="1" step="0.1" class="num-input" />
        </label>
      </div>
    </form>

    <LoadingSpinner v-if="loading" label="正在提取知识..." />

    <div v-if="error" class="error-msg">{{ error }}</div>

    <div v-if="result" class="extract-result">
      <div class="result-header">
        <strong>{{ result.topic }}</strong>
        <span class="result-meta">
          共 {{ result.total_documents }} 篇文档，{{ result.total_concepts }} 个概念
        </span>
      </div>

      <div v-for="doc in result.results" :key="doc.doc_id" class="doc-card">
        <div class="doc-header">
          <RouterLink :to="'/documents/' + doc.doc_id" class="doc-title">
            {{ doc.title }}
          </RouterLink>
          <span class="doc-meta">
            <span class="badge">{{ doc.domain || 'unknown' }}</span>
            <span class="conf-badge" :class="confClass(doc.confidence)">
              置信度 {{ (doc.confidence * 100).toFixed(0) }}%
            </span>
            <span class="stat">{{ doc.concept_count }} 概念</span>
          </span>
        </div>
        <div class="concept-list">
          <div v-for="c in doc.concepts.slice(0, 5)" :key="c.concept_id" class="concept-item">
            <div class="concept-title">{{ c.title || c.concept_id }}</div>
            <div v-if="c.summary" class="concept-summary">{{ c.summary }}</div>
            <div class="concept-conf">置信度: {{ (c.confidence * 100).toFixed(0) }}%</div>
          </div>
          <div v-if="doc.concepts.length > 5" class="more-hint">
            ...还有 {{ doc.concepts.length - 5 }} 个概念
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { extractByTopic, type ExtractResult } from '@/services/articles'
import { listBanks } from '@/services/banks'
import LoadingSpinner from '@/components/LoadingSpinner.vue'

const topic = ref('')
const selectedBank = ref('all')
const minConfidence = ref(0.0)
const loading = ref(false)
const error = ref('')
const result = ref<{
  topic: string
  total_documents: number
  total_concepts: number
  results: ExtractResult[]
} | null>(null)
const banks = ref<Array<{ key: string; name: string }>>([])

onMounted(async () => {
  try {
    const data = await listBanks()
    banks.value = data.banks || []
  } catch {
    // silently fail — banks are optional
  }
})

function confClass(conf: number): string {
  if (conf >= 0.7) return 'conf-high'
  if (conf >= 0.3) return 'conf-mid'
  return 'conf-low'
}

async function handleExtract() {
  if (!topic.value.trim()) return
  loading.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await extractByTopic(
      topic.value.trim(),
      selectedBank.value,
      minConfidence.value,
    )
  } catch (e: unknown) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      || (e as Error)?.message
      || '提取失败'
    error.value = msg
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.extract-page {
  max-width: 800px;
}

.page-title {
  font-size: clamp(1.1rem, 2vw, 1.4rem);
  font-weight: 700;
  margin-bottom: 0.25rem;
  letter-spacing: -0.02em;
}

.page-desc {
  font-size: 0.85rem;
  color: var(--fg-muted, #888);
  margin-bottom: 1.25rem;
}

.extract-form {
  margin-bottom: 1.25rem;
}

.extract-input-row {
  display: flex;
  gap: 0.5rem;
}

.extract-input {
  flex: 1;
  font-size: 0.95rem;
  padding: 0.6rem 0.75rem;
}

.extract-options {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-top: 0.75rem;
}

.option-label {
  font-size: 0.8rem;
  color: var(--fg-muted, #666);
  display: flex;
  align-items: center;
  gap: 0.3rem;
}

.bank-select {
  font-size: 0.8rem;
  padding: 0.3rem 0.5rem;
}

.num-input {
  width: 60px;
  font-size: 0.8rem;
  padding: 0.3rem 0.4rem;
}

.error-msg {
  font-size: 0.85rem;
  color: #c0392b;
  padding: 0.5rem 0.75rem;
  border: 1px solid #e8c4c0;
  background: #fdf2f1;
  margin-bottom: 1rem;
}

.result-header {
  margin-bottom: 1rem;
  padding: 0.75rem;
  background: var(--card, #fafafa);
  border: 1px solid var(--border, #eee);
  font-size: 0.9rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.result-meta {
  font-size: 0.8rem;
  color: var(--fg-muted, #888);
}

.doc-card {
  margin-bottom: 1rem;
  padding: 0.75rem;
  border: 1px solid var(--border, #eee);
  background: var(--card, #fff);
}

.doc-header {
  margin-bottom: 0.5rem;
}

.doc-title {
  font-weight: 600;
  font-size: 0.95rem;
  color: var(--accent, #2980b9);
  text-decoration: none;
}

.doc-title:hover {
  text-decoration: underline;
}

.doc-meta {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  margin-top: 0.25rem;
  font-size: 0.78rem;
}

.badge {
  display: inline-block;
  padding: 0.1rem 0.4rem;
  font-size: 0.7rem;
  background: var(--bg, #f0f0f0);
  border: 1px solid var(--border, #ddd);
  color: var(--fg-muted, #666);
}

.conf-badge {
  padding: 0.1rem 0.4rem;
  font-size: 0.7rem;
}

.conf-high {
  background: #e8f5e9;
  color: #2e7d32;
}

.conf-mid {
  background: #fff8e1;
  color: #f57f17;
}

.conf-low {
  background: #fbe9e7;
  color: #c62828;
}

.stat {
  color: var(--fg-muted, #888);
}

.concept-list {
  border-top: 1px solid var(--border, #eee);
  padding-top: 0.5rem;
}

.concept-item {
  padding: 0.4rem 0;
  border-bottom: 1px solid var(--border, #f5f5f5);
}

.concept-item:last-child {
  border-bottom: none;
}

.concept-title {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--fg, #333);
}

.concept-summary {
  font-size: 0.8rem;
  color: var(--fg-muted, #666);
  margin-top: 0.1rem;
  line-height: 1.4;
}

.concept-conf {
  font-size: 0.72rem;
  color: var(--fg-muted, #888);
  margin-top: 0.1rem;
}

.more-hint {
  font-size: 0.78rem;
  color: var(--fg-muted, #888);
  font-style: italic;
  padding: 0.25rem 0;
}
</style>
