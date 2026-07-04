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

    <LoadingSpinner v-if="queryStore.loading" label="正在查询..." />
    <LoadingSpinner v-if="queryStore.webSearching" label="联网搜索中..." />

    <Toast
      v-if="queryStore.error"
      :message="queryStore.error"
      type="error"
      @close="queryStore.clear()"
    />

    <ResultCard
      v-if="queryStore.answer"
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
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useQueryStore } from '@/stores/query'
import { useBanksStore } from '@/stores/banks'
import ResultCard from '@/components/ResultCard.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import Toast from '@/components/Toast.vue'

const queryStore = useQueryStore()
const banksStore = useBanksStore()

const queryText = ref('')
const selectedBank = ref('all')

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

onMounted(() => {
  banksStore.fetchBanks()
})

function handleQuery() {
  if (!queryText.value.trim()) return
  queryStore.submitQuery({
    q: queryText.value.trim(),
    bank: selectedBank.value,
    rerank: useRerank.value,
    rerank_mode: rerankMode.value,
    multiHypothesis: useMultiHypothesis.value,
    nocache: forceRefresh.value,
  })
}

function handleWebSearch() {
  if (!queryText.value.trim()) return
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
  })
}

async function handleClearCache() {
  const result = await queryStore.clearCache()
  if (result) {
    queryStore.clear()
  }
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
  color: var(--accent, #e67e22);
}

.nocache-text {
  font-weight: 600;
}

.bank-select {
  font-size: 0.8rem;
  padding: 0.3rem 0.5rem;
}

.action-bar {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.btn-clear-cache {
  font-size: 0.75rem;
  padding: 0.25rem 0.6rem;
  border: 1px solid var(--border, #ddd);
  background: var(--bg-card, #fff);
  color: var(--fg-muted, #666);
  cursor: pointer;
  border-radius: 4px;
}

.btn-clear-cache:hover {
  border-color: var(--accent, #e67e22);
  color: var(--accent, #e67e22);
}

.btn-clear-cache:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
