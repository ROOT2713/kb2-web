<template>
  <div class="documents-page">
    <h1 class="page-title">文档管理</h1>

    <div class="toolbar">
      <input
        v-model="search"
        type="text"
        class="search-input"
        placeholder="搜索文档..."
      />
      <select v-model="filterBank" class="bank-filter" @change="loadDocs">
        <option value="all">全部知识库</option>
        <option v-for="bank in banksStore.banks" :key="bank.key" :value="bank.key">
          {{ bank.name }}
        </option>
      </select>
      <button @click="loadDocs">刷新</button>
    </div>

    <LoadingSpinner v-if="docsStore.loading" label="加载中..." />

    <div v-if="filteredDocs.length" class="doc-table card">
      <div class="table-header">
        <span class="col-title">标题</span>
        <span class="col-bank">知识库</span>
        <span class="col-chunks">分块</span>
        <span class="col-status">状态</span>
        <span class="col-date">日期</span>
        <span class="col-actions">操作</span>
      </div>
      <div v-for="doc in filteredDocs" :key="doc.id" class="table-row">
        <span class="col-title" :title="doc.filename"><router-link :to="'/documents/' + doc.id" class="doc-title-link">{{ doc.title }}</router-link></span>
        <span class="col-bank">
          <span class="badge">{{ doc.bank }}</span>
        </span>
        <span class="col-chunks">{{ doc.chunks }}</span>
        <span class="col-status">
          <span
            class="status-dot"
            :class="doc.searchable ? 'ok' : 'pending'"
          ></span>
        </span>
        <span class="col-date">{{ formatDate(doc.created) }}</span>
        <span class="col-actions">
          <button class="btn-sm" @click="handleReparse(doc.id)">重解析</button>
          <button class="btn-sm danger" @click="handleDelete(doc.id)">删除</button>
        </span>
      </div>
    </div>

    <div v-else-if="!docsStore.loading" class="empty-state">
      <p>暂无文档</p>
    </div>

    <Toast v-if="toastMsg" :message="toastMsg" :type="toastType" @close="toastMsg = ''" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useDocumentsStore } from '@/stores/documents'
import { useBanksStore } from '@/stores/banks'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import Toast from '@/components/Toast.vue'

const docsStore = useDocumentsStore()
const banksStore = useBanksStore()

const search = ref('')
const filterBank = ref('all')
const toastMsg = ref('')
const toastType = ref<'info' | 'success' | 'error' | 'warning'>('info')

const filteredDocs = computed(() => {
  const q = search.value.toLowerCase().trim()
  if (!q) return docsStore.documents
  return docsStore.documents.filter(
    (d) =>
      d.title.toLowerCase().includes(q) ||
      d.filename.toLowerCase().includes(q) ||
      d.category.toLowerCase().includes(q),
  )
})

onMounted(() => {
  banksStore.fetchBanks()
  loadDocs()
})

function loadDocs() {
  docsStore.fetchDocuments(filterBank.value)
}

function formatDate(iso: string): string {
  if (!iso) return '-'
  return iso.substring(0, 10)
}

async function handleDelete(docId: string) {
  if (!confirm('确认删除此文档？')) return
  try {
    await docsStore.removeDocument(docId)
    toastMsg.value = '已删除'
    toastType.value = 'success'
  } catch {
    toastMsg.value = '删除失败'
    toastType.value = 'error'
  }
}

async function handleReparse(docId: string) {
  try {
    await docsStore.reparse(docId)
    toastMsg.value = '重新解析完成'
    toastType.value = 'success'
    loadDocs()
  } catch {
    toastMsg.value = '重新解析失败'
    toastType.value = 'error'
  }
}
</script>

<style scoped>
.documents-page {
  max-width: 1000px;
}

.page-title {
  font-size: clamp(1.1rem, 2vw, 1.4rem);
  font-weight: 700;
  margin-bottom: 1.25rem;
  letter-spacing: -0.02em;
}

.toolbar {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.search-input {
  flex: 1;
}

.bank-filter {
  min-width: 140px;
}

.doc-table {
  padding: 0;
  overflow: hidden;
}

.table-header {
  display: grid;
  grid-template-columns: 1fr 100px 60px 50px 100px 130px;
  gap: 0.5rem;
  padding: 0.6rem 1rem;
  background: var(--bg-alt);
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--fg-muted);
  border-bottom: 1px solid var(--border);
}

.table-row {
  display: grid;
  grid-template-columns: 1fr 100px 60px 50px 100px 130px;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  font-size: 0.825rem;
  align-items: center;
  border-bottom: 1px solid var(--bg-alt);
  transition: background 0.1s;
}

.table-row:hover {
  background: var(--bg);
}

.col-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.col-chunks {
  text-align: center;
  color: var(--fg-muted);
}

.col-date {
  font-size: 0.75rem;
  color: var(--fg-muted);
}

.doc-title-link {
  color: var(--fg);
  text-decoration: none;
}
.doc-title-link:hover {
  color: var(--accent);
  text-decoration: underline;
}
.col-actions {
  display: flex;
  gap: 0.35rem;
}

.btn-sm {
  font-size: 0.72rem;
  padding: 0.25rem 0.5rem;
}

.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-dot.ok {
  background: var(--success);
}

.status-dot.pending {
  background: var(--border);
}

.empty-state {
  text-align: center;
  padding: 3rem;
  color: var(--fg-muted);
  font-size: 0.9rem;
}
</style>
