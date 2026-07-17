<template>
  <div class="query-page">
    <h1 class="page-title">知识库查询</h1>

    <form class="query-form" @submit.prevent="handleQuery">
      <div class="query-input-row">
        <input
          v-model="queryText"
          type="text"
          class="query-input"
          placeholder="输入问题..."
          :disabled="queryStore.loading"
        />
        <button type="submit" class="primary" :disabled="!queryText.trim() || queryStore.loading">
          搜索
        </button>
        <button
          type="button"
          :disabled="!queryText.trim() || queryStore.webSearching"
          @click="handleWebSearch"
        >
          联网搜索
        </button>
      </div>
      <div class="query-options">
        <label class="option-label">
          <select v-model="selectedBank" class="bank-select">
            <option value="all">全部知识库</option>
            <option v-for="bank in banksStore.banks" :key="bank.key" :value="bank.key">
              {{ bank.name }}
            </option>
          </select>
        </label>
        <label class="option-label">
          <select v-model="categoryFilter" class="cat-filter" @change="handleQuery">
            <option value="">排除日常/资讯</option>
            <option value="all">全部（含日常/资讯）</option>
            <option value="daily,news">仅日常+资讯</option>
            <option v-for="c in categories" :key="c.key" :value="c.key">
              {{ c.label }}
            </option>
          </select>
        </label>
        <label class="option-label">
          <input v-model="useRerank" type="checkbox" />
          精排
        </label>
        <label class="option-label" v-if="useRerank">
          <span>重排模式</span>
          <select v-model="rerankMode" class="bank-select">
            <option value="default">默认 (LLM)</option>
            <option value="multidim">多维重排</option>
            <option value="confidence">置信度优先</option>
            <option value="freshness">最新优先</option>
          </select>
        </label>
        <label class="option-label">
          <input v-model="useMultiHypothesis" type="checkbox" />
          多假设对比
        </label>
        <label class="option-label nocache-label">
          <input v-model="forceRefresh" type="checkbox" />
          <span class="nocache-text">强制刷新</span>
        </label>
      </div>
    </form>

    <div class="action-bar" v-if="!queryStore.loading">
      <button
        type="button"
        class="btn-clear-cache"
        :disabled="queryStore.clearingCache"
        @click="handleClearCache"
      >
        {{ queryStore.clearingCache ? '清除中...' : '🗑️ 清除缓存' }}
      </button>
    </div>

    <div v-if="queryStore.loading || queryStore.webSearching" class="query-loading-overlay">
      <LoadingSpinner
        v-if="queryStore.loading"
        label="正在查询..."
        :elapsed="queryElapsed"
      />
      <LoadingSpinner
        v-if="queryStore.webSearching"
        label="联网搜索中..."
        :elapsed="queryElapsed"
      />
      <button class="btn-abort" @click="abortQuery">取消查询</button>
    </div>

    <Toast
      v-if="queryStore.error"
      :message="queryStore.error"
      type="error"
      @close="queryStore.clear()"
    />

    <!-- 查询历史 -->
    <div v-if="queryStore.queryHistory.length > 0 && !queryStore.loading && !queryStore.answer" class="query-history">
      <div class="history-header">
        <span class="history-title">查询历史</span>
        <button class="btn-clear-history" @click="queryStore.clearHistory()">清空</button>
      </div>
      <div
        v-for="(item, idx) in queryStore.queryHistory"
        :key="item.timestamp"
        class="history-item"
        @click="rerunHistory(item)"
      >
        <span class="history-q">{{ item.q }}</span>
        <span class="history-time">{{ formatTime(item.timestamp) }}</span>
        <button class="history-delete" @click.stop="queryStore.removeFromHistory(idx)">×</button>
      </div>
    </div>

    <div class="result-wrapper" v-if="queryStore.answer">
      <ResultCard
        :content="queryStore.answer"
        :sources="queryStore.sources"
        :cache-hit="queryStore.cacheHit"
        :suggestions="queryStore.suggestions"
        :standard-contents="queryStore.standardContents"
        :bank="selectedBank"
        :query-keywords="searchKeywords"
        @search-suggestion="handleSuggestionSearch"
        @refresh="handleRefreshFromCache"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useQueryStore } from '@/stores/query'
import { useBanksStore } from '@/stores/banks'
import api from '@/services/api'
import ResultCard from '@/components/ResultCard.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import Toast from '@/components/Toast.vue'

const queryStore = useQueryStore()
const banksStore = useBanksStore()

const queryText = ref('')
const selectedBank = ref('all')
const categoryFilter = ref('')
const categories = ref<{key: string, label: string, isolated: boolean}[]>([])

/** SourceCard: 从当前查询文本提取关键词用于高亮 */
const searchKeywords = computed(() => {
  const raw = queryText.value
  if (!raw) return []
  // 中文按分词或取2+字词
  const tokens = raw.split(/[\s,，、；;。.？?！!]+/).filter(t => t.length >= 2)
  // 去重取前8个
  return [...new Set(tokens)].slice(0, 8)
})
const useRerank = ref(false)
const rerankMode = ref('default')
const useMultiHypothesis = ref(false)
const forceRefresh = ref(false)

const queryElapsed = ref(0)
let queryTimer: ReturnType<typeof setInterval> | null = null

function startQueryTimer() {
  queryElapsed.value = 0
  queryTimer = setInterval(() => { queryElapsed.value++ }, 1000)
}

function stopQueryTimer() {
  if (queryTimer) { clearInterval(queryTimer); queryTimer = null }
}

// Watch loading state change to stop timer
watch(() => queryStore.loading, (loading) => {
  if (!loading) stopQueryTimer()
})

async function loadCategories() {
  try {
    const { data } = await api.get('/admin/categories')
    categories.value = data
  } catch { /* ignore */ }
}

onMounted(() => {
  banksStore.fetchBanks()
  loadCategories()
})

function handleQuery() {
  if (!queryText.value.trim()) return
  startQueryTimer()
  queryStore.submitQuery({
    q: queryText.value.trim(),
    bank: selectedBank.value,
    rerank: useRerank.value,
    rerank_mode: rerankMode.value,
    multiHypothesis: useMultiHypothesis.value,
    nocache: forceRefresh.value,
    categories: categoryFilter.value,
  })
}

function handleWebSearch() {
  if (!queryText.value.trim()) return
  startQueryTimer()
  queryStore.doWebSearch({
    q: queryText.value.trim(),
    bank: selectedBank.value,
    context: queryStore.answer,
  })
}

function handleSuggestionSearch(nextQuery: string) {
  queryText.value = nextQuery
  queryStore.submitQuery({
    q: nextQuery,
    bank: selectedBank.value,
    rerank: useRerank.value,
    rerank_mode: rerankMode.value,
    nocache: forceRefresh.value,
    categories: categoryFilter.value,
  })
}

function handleRefreshFromCache() {
  if (!queryText.value.trim()) return
  queryStore.submitQuery({
    q: queryText.value.trim(),
    bank: selectedBank.value,
    rerank: useRerank.value,
    rerank_mode: rerankMode.value,
    multiHypothesis: useMultiHypothesis.value,
    nocache: true,
    categories: categoryFilter.value,
  })
}

async function handleClearCache() {
  const result = await queryStore.clearCache()
  if (result) {
    queryStore.clear()
  }
}

function abortQuery() {
  queryStore.clear()
  stopQueryTimer()
}

function formatTime(ts: number): string {
  const d = new Date(ts)
  const now = new Date()
  const pad = (n: number) => n.toString().padStart(2, '0')
  if (d.toDateString() === now.toDateString()) {
    return `今天 ${pad(d.getHours())}:${pad(d.getMinutes())}`
  }
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) {
    return `昨天 ${pad(d.getHours())}:${pad(d.getMinutes())}`
  }
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function rerunHistory(item: { q: string; bank: string }) {
  queryText.value = item.q
  selectedBank.value = item.bank || 'all'
  handleQuery()
}
</script>

<style scoped>
.query-page {
  max-width: 800px;
}

.page-title {
  font-size: clamp(1.1rem, 2vw, 1.4rem);
  font-weight: 700;
  margin-bottom: 1.25rem;
  letter-spacing: -0.02em;
}

.query-form {
  margin-bottom: 0.75rem;
}

.query-input-row {
  display: flex;
  gap: 0.5rem;
}

.query-input {
  flex: 1;
  font-size: 0.95rem;
  padding: 0.6rem 0.75rem;
  box-shadow: var(--shadow-sm);
  transition: box-shadow var(--transition), border-color var(--transition);
}

.query-input:focus {
  box-shadow: var(--shadow);
  border-color: var(--accent);
}

.query-options {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-top: 0.75rem;
}

.option-label {
  font-size: 0.8rem;
  color: var(--fg-muted);
  display: flex;
  align-items: center;
  gap: 0.3rem;
  cursor: pointer;
}

.nocache-label {
  color: var(--accent);
}

.nocache-text {
  font-weight: 600;
}

.bank-select {
  font-size: 0.8rem;
  padding: 0.3rem 0.5rem;
}

.cat-filter {
  font-size: 0.8rem;
  padding: 0.3rem 0.5rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--fg);
  cursor: pointer;
}

.action-bar {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.btn-clear-cache {
  font-size: 0.75rem;
  padding: 0.25rem 0.6rem;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--fg-muted);
  cursor: pointer;
  border-radius: var(--radius-sm);
}

.btn-clear-cache:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.btn-clear-cache:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.query-loading-overlay {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  padding: 3rem 0;
}
.btn-abort {
  font-size: 0.8rem;
  padding: 0.4rem 1.2rem;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--fg-muted);
  cursor: pointer;
  border-radius: var(--radius-sm);
}
.btn-abort:hover { border-color: var(--accent); color: var(--accent); }
.query-history {
  margin-top: 1.5rem;
  border-top: 1px solid var(--border);
  padding-top: 1rem;
}
.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}
.history-title {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--fg-muted);
}
.btn-clear-history {
  font-size: 0.75rem;
  padding: 0.2rem 0.5rem;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--fg-muted);
  cursor: pointer;
  border-radius: var(--radius-sm);
}
.btn-clear-history:hover { border-color: var(--accent); color: var(--accent); }

.result-wrapper {
  max-width: 100%;
  overflow: hidden;
}

.result-wrapper :deep(.result-card) {
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  cursor: pointer;
  border-radius: var(--radius);
  transition: background var(--transition);
}
.history-item:hover { background: var(--surface-hover); }
.history-q {
  flex: 1;
  font-size: 0.85rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-time {
  font-size: 0.72rem;
  color: var(--fg-muted);
  white-space: nowrap;
  flex-shrink: 0;
}
.history-delete {
  font-size: 1rem;
  line-height: 1;
  border: none;
  background: none;
  color: var(--fg-muted);
  cursor: pointer;
  padding: 0 0.25rem;
  opacity: 0.5;
}
.history-delete:hover { opacity: 1; color: var(--accent); }
</style>
