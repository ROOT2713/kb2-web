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
        <span class="col-cat">分类</span>
        <span class="col-subcat">细分类</span>
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
        <span class="col-cat">
          <template v-if="editingCat === doc.id">
            <select v-model="editCatValue" class="cat-select" @change="saveCategory(doc.id)">
              <option value="">未分类</option>
              <option v-for="c in docsStore.categories" :key="c.key" :value="c.key">{{ c.label }}</option>
            </select>
          </template>
          <span v-else class="badge cat-badge" @click="startEditCat(doc)">{{ getCatLabel(doc.category) }}</span>
        </span>
        <span class="col-subcat">
          <template v-if="editingSubcat === doc.id">
            <input v-model="editSubcatValue" class="subcat-input" placeholder="细分类" @blur="saveSubcategory(doc.id)" @keyup.enter="saveSubcategory(doc.id)" />
          </template>
          <span v-else class="badge subcat-badge" @click="startEditSubcat(doc)">{{ doc.subcategory || '—' }}</span>
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
          <button v-if="authStore.isAdmin" class="btn-sm" @click="handleReparse(doc.id)">重解析</button>
          <button v-if="authStore.isAdmin" class="btn-sm danger" @click="handleDelete(doc.id)">删除</button>
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
import { useAuthStore } from '@/stores/auth'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import Toast from '@/components/Toast.vue'
import type { DocumentItem } from '@/services/documents'

const docsStore = useDocumentsStore()
const banksStore = useBanksStore()
const authStore = useAuthStore()

const search = ref('')
const filterBank = ref('all')
const toastMsg = ref('')
const toastType = ref<'info' | 'success' | 'error' | 'warning'>('info')
const editingCat = ref<string | null>(null)
const editCatValue = ref('')
const editingSubcat = ref<string | null>(null)
const editSubcatValue = ref('')

function getCatLabel(key: string): string {
  const found = docsStore.categories.find((c) => c.key === key)
  return found ? found.label : (key || '未分类')
}

function startEditCat(doc: DocumentItem) {
  editingCat.value = doc.id
  editCatValue.value = doc.category || ''
}

function startEditSubcat(doc: DocumentItem) {
  editingSubcat.value = doc.id
  editSubcatValue.value = doc.subcategory || ''
}

async function saveCategory(docId: string) {
  try {
    await docsStore.patchDocument(docId, { category: editCatValue.value })
  } catch {
    toastMsg.value = '更新分类失败'
    toastType.value = 'error'
  } finally {
    editingCat.value = null
  }
}

async function saveSubcategory(docId: string) {
  try {
    await docsStore.patchDocument(docId, { subcategory: editSubcatValue.value })
    toastMsg.value = '细分类已更新'
    toastType.value = 'success'
  } catch {
    toastMsg.value = '更新细分类失败'
    toastType.value = 'error'
  } finally {
    editingSubcat.value = null
  }
}

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
  docsStore.fetchCategories()
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
  grid-template-columns: 1fr 100px 80px 80px 60px 50px 100px 130px;
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
  grid-template-columns: 1fr 100px 80px 80px 60px 50px 100px 130px;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  font-size: 0.825rem;
  align-items: center;
  border-bottom: 1px solid var(--bg-alt);
  transition: background 0.1s;
}

.table-row:hover {
  background: var(--surface-hover);
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

.col-subcat {
  font-size: 0.75rem;
}
.subcat-badge {
  cursor: pointer;
  padding: 0.1rem 0.3rem;
  border-radius: 4px;
  font-size: 0.75rem;
  background: var(--bg-alt);
  border: 1px dashed var(--border);
}
.subcat-badge:hover {
  background: var(--surface-hover);
}
.subcat-input {
  width: 65px;
  font-size: 0.75rem;
  padding: 0.15rem 0.3rem;
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

.col-cat { min-width: 80px; }
.cat-badge { cursor: pointer; }
.cat-badge:hover { background: var(--accent-light); border-color: var(--accent); }
.cat-select { font-size: 0.8rem; padding: 2px 4px; width: 90px; }
</style>
