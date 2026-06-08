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
      </div>
    </form>

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
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useQueryStore } from '@/stores/query'
import { useBanksStore } from '@/stores/banks'
import ResultCard from '@/components/ResultCard.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import Toast from '@/components/Toast.vue'

const queryStore = useQueryStore()
const banksStore = useBanksStore()

const queryText = ref('')
const selectedBank = ref('all')
const useRerank = ref(false)

onMounted(() => {
  banksStore.fetchBanks()
})

function handleQuery() {
  if (!queryText.value.trim()) return
  queryStore.submitQuery({
    q: queryText.value.trim(),
    bank: selectedBank.value,
    rerank: useRerank.value,
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
  margin-bottom: 1.5rem;
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

.bank-select {
  font-size: 0.8rem;
  padding: 0.3rem 0.5rem;
}
</style>
