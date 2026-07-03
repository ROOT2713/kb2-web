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
        <label class="option-label">
          <span>LLM 摘要</span>
          <input v-model="summarize" type="checkbox" class="checkbox-input" />
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
        <span v-if="result.pagination" class="result-page">
          第 {{ result.pagination.page }} 页，共 {{ result.pagination.total_pages }} 页
        </span>
      </div>

      <!-- LLM 摘要卡片（P2 Step 3d） -->
      <div v-if="result.summary" class="summary-card">
        <div class="summary-title">📋 LLM 摘要</div>
        <div class="summary-body">{{ result.summary }}</div>
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

      <!-- 分页器（P2 Step 3c） -->
      <div v-if="result.pagination && result.pagination.total_pages > 1" class="pagination-bar">
        <button
          class="page-btn"
          :disabled="currentPage <= 1"
          @click="goToPage(currentPage - 1)"
        >
          上一页
        </button>
        <span class="page-info">
          第 {{ currentPage }} 页，共 {{ result.pagination.total_pages }} 页
        </span>
        <button
          class="page-btn"
          :disabled="currentPage >= result.pagination.total_pages"
          @click="goToPage(currentPage + 1)"
        >
          下一页
        </button>
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
const summarize = ref(false)
const loading = ref(false)
const error = ref('')
const currentPage = ref(1)
const result = ref<{
  topic: string
  total_documents: number
  total_concepts: number
  results: ExtractResult[]
  summary: string
  pagination?: {
    page: number
    page_size: number
    total: number
    total_pages: number
  }
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
  currentPage.value = 1
  try {
    result.value = await extractByTopic(
      topic.value,
      selectedBank.value,
      minConfidence.value,
      50,
      currentPage.value,
      20,
      summarize.value,
    )
  } catch (e) {
    error.value = '提取失败: ' + (e instanceof Error ? e.message : '未知错误')
  } finally {
    loading.value = false
  }
}

async function goToPage(page: number) {
  if (!topic.value.trim()) return
  currentPage.value = page
  loading.value = true
  try {
    result.value = await extractByTopic(
      topic.value,
      selectedBank.value,
      minConfidence.value,
      50,
      page,
      20,
      summarize.value,
    )
  } catch (e) {
    error.value = '加载失败: ' + (e instanceof Error ? e.message : '未知错误')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.extract-page { max-width: 900px; margin: 0 auto; padding: 24px; }
.page-title { font-size: 1.5rem; font-weight: 600; margin-bottom: 8px; }
.page-desc { color: #666; margin-bottom: 24px; font-size: 0.9rem; }
.extract-form { margin-bottom: 24px; }
.extract-input-row { display: flex; gap: 8px; margin-bottom: 12px; }
.extract-input { flex: 1; padding: 10px 14px; border: 1px solid #ddd; border-radius: 6px; font-size: 1rem; }
.extract-input:focus { outline: none; border-color: #2563eb; box-shadow: 0 0 0 2px rgba(37,99,235,0.15); }
.extract-options { display: flex; gap: 16px; flex-wrap: wrap; }
.option-label { display: flex; align-items: center; gap: 6px; font-size: 0.85rem; color: #555; }
.bank-select { padding: 6px 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 0.85rem; }
.num-input { width: 70px; padding: 6px 8px; border: 1px solid #ddd; border-radius: 4px; font-size: 0.85rem; }
.checkbox-input { width: 18px; height: 18px; cursor: pointer; }
.error-msg { color: #dc2626; background: #fef2f2; padding: 10px 14px; border-radius: 6px; margin-bottom: 16px; }
.extract-result { margin-top: 16px; }
.result-header { margin-bottom: 16px; display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.result-header strong { font-size: 1.1rem; }
.result-meta { color: #888; font-size: 0.85rem; }
.result-page { color: #2563eb; font-size: 0.85rem; background: #eff6ff; padding: 2px 8px; border-radius: 4px; }

/* Summary card (P2 Step 3d) */
.summary-card { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 14px 18px; margin-bottom: 20px; }
.summary-title { font-weight: 600; font-size: 0.95rem; color: #166534; margin-bottom: 6px; }
.summary-body { font-size: 0.9rem; color: #333; line-height: 1.6; }

.doc-card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-bottom: 12px; background: #fff; }
.doc-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; flex-wrap: wrap; gap: 8px; }
.doc-title { font-weight: 600; color: #2563eb; text-decoration: none; font-size: 1rem; }
.doc-title:hover { text-decoration: underline; }
.doc-meta { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.badge { background: #f3f4f6; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; color: #555; }
.conf-badge { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 500; }
.conf-high { background: #dcfce7; color: #166534; }
.conf-mid { background: #fef9c3; color: #854d0e; }
.conf-low { background: #fee2e2; color: #991b1b; }
.stat { color: #888; font-size: 0.8rem; }
.concept-list { border-top: 1px solid #f3f4f6; padding-top: 10px; }
.concept-item { margin-bottom: 10px; }
.concept-title { font-weight: 500; font-size: 0.9rem; color: #333; }
.concept-summary { font-size: 0.82rem; color: #666; margin-top: 2px; }
.concept-conf { font-size: 0.75rem; color: #999; margin-top: 2px; }
.more-hint { font-size: 0.8rem; color: #888; font-style: italic; }

/* Pagination bar (P2 Step 3c) */
.pagination-bar { display: flex; align-items: center; justify-content: center; gap: 16px; margin-top: 24px; padding: 12px; }
.page-btn { padding: 8px 18px; border: 1px solid #d1d5db; border-radius: 6px; background: #fff; color: #374151; cursor: pointer; font-size: 0.9rem; }
.page-btn:hover:not(:disabled) { background: #f3f4f6; border-color: #9ca3af; }
.page-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.page-info { font-size: 0.9rem; color: #555; }
</style>
