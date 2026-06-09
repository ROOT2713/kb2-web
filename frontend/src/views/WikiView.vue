<template>
  <div class="wiki-page">
    <h1 class="page-title">Wiki 文档目录</h1>

    <div class="toolbar">
      <button @click="loadWiki">刷新</button>
      <span class="total-count">共 {{ wikiData?.total ?? 0 }} 篇文档</span>
    </div>

    <LoadingSpinner v-if="loading" label="加载中..." />

    <div v-if="error" class="error-msg">{{ error }}</div>

    <div v-if="wikiData && wikiData.tree" class="wiki-tree">
      <div v-for="(bank, bankName) in wikiData.tree" :key="bankName" class="bank-node">
        <details :open="bankName === Object.keys(wikiData.tree)[0]">
          <summary class="bank-summary">
            <span class="bank-icon">📁</span>
            <span class="bank-name">{{ bankName }}</span>
            <span class="bank-count">{{ wikiData.bank_counts?.[bankName] || getBankDocCount(bank) }} 篇</span>
          </summary>
          <div class="bank-categories">
            <div v-for="(cat, catName) in bank" :key="catName" class="category-node">
              <details>
                <summary class="cat-summary">
                  <span class="cat-icon">📂</span>
                  <span class="cat-name">{{ catName || '未分类' }}</span>
                  <span class="cat-count">{{ cat.length }} 篇</span>
                </summary>
                <ul class="doc-list">
                  <li v-for="doc in cat" :key="doc.id" class="doc-item">
                    <span class="doc-icon">📄</span>
                    <RouterLink :to="'/documents/' + doc.id" class="doc-link">{{ doc.title }}</RouterLink>
                  </li>
                </ul>
              </details>
            </div>
          </div>
        </details>
      </div>
    </div>

    <div v-else-if="!loading && !error" class="empty-state">
      <p>暂无 Wiki 数据</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/services/api'
import LoadingSpinner from '@/components/LoadingSpinner.vue'

interface WikiDoc {
  id: string
  title: string
  bank?: string
  [key: string]: unknown
}

interface WikiResponse {
  tree: Record<string, Record<string, WikiDoc[]>>
  bank_names: string[]
  bank_counts: Record<string, number>
  total: number
}

const wikiData = ref<WikiResponse | null>(null)
const loading = ref(false)
const error = ref('')

onMounted(() => {
  loadWiki()
})

async function loadWiki() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get<WikiResponse>('/banks/wiki', { params: { bank: 'all' } })
    wikiData.value = data
  } catch (e: unknown) {
    error.value = (e as Error).message || '加载失败'
  } finally {
    loading.value = false
  }
}

function getBankDocCount(bank: Record<string, WikiDoc[]>): number {
  return Object.values(bank).reduce((sum, docs) => sum + docs.length, 0)
}
</script>

<style scoped>
.wiki-page {
  max-width: 900px;
}

.page-title {
  font-size: clamp(1.1rem, 2vw, 1.4rem);
  font-weight: 700;
  margin-bottom: 1.25rem;
  letter-spacing: -0.02em;
}

.toolbar {
  display: flex;
  gap: 1rem;
  align-items: center;
  margin-bottom: 1rem;
}

.total-count {
  font-size: 0.85rem;
  color: var(--fg-muted);
}

.error-msg {
  color: var(--danger);
  font-size: 0.85rem;
  margin-bottom: 1rem;
}

.wiki-tree {
  font-size: 0.9rem;
}

.bank-node {
  margin-bottom: 0.75rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}

.bank-summary {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 1rem;
  background: var(--bg-alt);
  cursor: pointer;
  font-weight: 600;
  user-select: none;
}

.bank-summary::-webkit-details-marker {
  display: none;
}

.bank-icon {
  font-size: 0.85rem;
}

.bank-name {
  flex: 1;
}

.bank-count {
  font-size: 0.75rem;
  color: var(--fg-muted);
  font-weight: 400;
}

.bank-categories {
  padding: 0.5rem 0;
}

.category-node {
  margin: 0;
}

.cat-summary {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 1.5rem;
  cursor: pointer;
  font-size: 0.85rem;
  color: var(--fg-muted);
  user-select: none;
}

.cat-summary::-webkit-details-marker {
  display: none;
}

.cat-icon {
  font-size: 0.75rem;
}

.cat-name {
  flex: 1;
  font-weight: 500;
}

.cat-count {
  font-size: 0.7rem;
  color: var(--fg-muted);
}

.doc-list {
  list-style: none;
  margin: 0;
  padding: 0.25rem 0 0.5rem;
}

.doc-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.3rem 2.5rem;
  font-size: 0.825rem;
  transition: background 0.1s;
}

.doc-item:hover {
  background: var(--bg);
}

.doc-icon {
  font-size: 0.75rem;
  flex-shrink: 0;
}

.doc-link {
  color: var(--fg);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-link:hover {
  color: var(--accent);
  text-decoration: underline;
}

.empty-state {
  text-align: center;
  padding: 3rem;
  color: var(--fg-muted);
  font-size: 0.9rem;
}
</style>
