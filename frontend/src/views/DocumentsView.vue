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
      <button class="secondary" @click="loadDocs">刷新</button>
    </div>

    <LoadingSpinner v-if="docsStore.loading" label="加载中..." />

    <!-- Batch actions toolbar (visible when items selected) -->
    <div v-if="selectedIds.size > 0" class="batch-bar card">
      <span class="batch-info">已选 {{ selectedIds.size }} 篇</span>
      <button v-if="authStore.isAdmin" class="primary" @click="showBatchSubcat = true">批量设置细分类</button>
      <button class="secondary" @click="clearSelection">取消选择</button>
    </div>

    <!-- Batch subcategory modal -->
    <div v-if="showBatchSubcat && authStore.isAdmin" class="modal-overlay" @click.self="showBatchSubcat = false">
      <div class="modal card">
        <h3>批量设置（{{ selectedIds.size }} 篇）</h3>
        <label class="field-label">分类</label>
        <select v-model="batchCatValue" class="cat-select wide">
          <option value="">— 不修改 —</option>
          <option v-for="c in docsStore.categories" :key="c.key" :value="c.key">{{ c.label }}</option>
        </select>
        <label class="field-label">细分类</label>
        <input v-model="batchSubcatValue" type="text" placeholder="输入细分类名称..." class="subcat-input wide" />
        <div class="modal-actions">
          <button class="primary" :disabled="!batchSubcatValue.trim() && !batchCatValue" @click="doBatchPatch">确认</button>
          <button @click="showBatchSubcat = false">取消</button>
        </div>
      </div>
    </div>

    <div v-if="filteredDocs.length" class="doc-table card">
      <div class="table-header">
        <span class="col-check">
          <input v-if="authStore.isAdmin" type="checkbox" :checked="allSelected" :indeterminate="someSelected" @change="toggleAll" />
        </span>
        <span class="col-title">标题</span>
        <span class="col-bank">知识库</span>
        <span class="col-cat">分类</span>
        <span class="col-subcat">细分类</span>
        <span class="col-chunks">分块</span>
        <span class="col-status">状态</span>
        <span class="col-date">日期</span>
        <span class="col-actions">操作</span>
      </div>
      <div v-for="doc in filteredDocs" :key="doc.id" class="table-row" :class="{ selected: selectedIds.has(doc.id) }">
        <span class="col-check">
          <input v-if="authStore.isAdmin" type="checkbox" :checked="selectedIds.has(doc.id)" @change="toggleDoc(doc.id)" />
        </span>
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
          <span v-else class="badge cat-badge" @click="authStore.isAdmin && startEditCat(doc)">{{ getCatLabel(doc.category) }}</span>
        </span>
        <span class="col-subcat">
          <template v-if="editingSubcat === doc.id">
            <input v-model="editSubcatValue" class="subcat-input" placeholder="细分类" @blur="saveSubcategory(doc.id)" @keyup.enter="saveSubcategory(doc.id)" />
          </template>
          <span v-else class="badge subcat-badge" @click="authStore.isAdmin && startEditSubcat(doc)">{{ doc.subcategory || '—' }}</span>
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
import { ref, computed, watch, onMounted } from 'vue'
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
// Connect to banksStore.selectedBank so sidebar clicks sync the document filter
const filterBank = computed({
  get: () => banksStore.selectedBank,
  set: (val: string) => { banksStore.selectBank(val); loadDocs() },
})
const toastMsg = ref('')
const toastType = ref<'info' | 'success' | 'error' | 'warning'>('info')
const editingCat = ref<string | null>(null)
const editCatValue = ref('')
const editingSubcat = ref<string | null>(null)
const editSubcatValue = ref('')

// Batch edit state
const selectedIds = ref(new Set<string>())
const showBatchSubcat = ref(false)
const batchSubcatValue = ref('')
const batchCatValue = ref('')

const allSelected = computed(() =>
  filteredDocs.value.length > 0 && selectedIds.value.size === filteredDocs.value.length
)
const someSelected = computed(() =>
  selectedIds.value.size > 0 && selectedIds.value.size < filteredDocs.value.length
)

function toggleAll() {
  if (allSelected.value) {
    clearSelection()
  } else {
    selectedIds.value = new Set(filteredDocs.value.map((d) => d.id))
  }
}

function toggleDoc(id: string) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
}

function clearSelection() {
  selectedIds.value = new Set()
}

async function doBatchPatch() {
  const subcatVal = batchSubcatValue.value.trim()
  const catVal = batchCatValue.value
  if (!subcatVal && !catVal) return
  try {
    const ids = Array.from(selectedIds.value)
    const payload: { doc_ids: string[]; category?: string; subcategory?: string } = { doc_ids: ids }
    if (catVal) payload.category = catVal
    if (subcatVal) payload.subcategory = subcatVal
    await docsStore.batchPatch(payload)
    toastMsg.value = `已更新 ${ids.length} 篇文档`
    toastType.value = 'success'
    showBatchSubcat.value = false
    batchSubcatValue.value = ''
    batchCatValue.value = ''
    selectedIds.value = new Set()
    loadDocs()
  } catch {
    toastMsg.value = '批量更新失败'
    toastType.value = 'error'
  }
}

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

// Watch sidebar bank selection for documents page
watch(() => banksStore.selectedBank, () => {
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
  min-width: 120px;
}

/* Batch bar */
.batch-bar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6rem 1rem;
  margin-bottom: 0.75rem;
  background: var(--accent-light);
  border-color: var(--accent);
}

.batch-info {
  font-weight: 600;
  font-size: 0.85rem;
  color: var(--accent);
}

/* Modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}

.modal {
  padding: 1.5rem;
  min-width: 360px;
}

.modal h3 {
  font-size: 1rem;
  margin-bottom: 1rem;
}

.modal .wide {
  width: 100%;
  box-sizing: border-box;
}

.field-label {
  display: block;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--fg-muted);
  margin-top: 0.5rem;
  margin-bottom: 0.2rem;
}

.modal-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 1rem;
  justify-content: flex-end;
}

/* Table */
.doc-table {
  display: flex;
  flex-direction: column;
}

.table-header, .table-row {
  display: flex;
  align-items: center;
  padding: 0.5rem 0.75rem;
  gap: 0.5rem;
  font-size: 0.8rem;
}

.table-header {
  font-weight: 600;
  color: var(--fg-muted);
  border-bottom: 1px solid var(--border);
  text-transform: uppercase;
  font-size: 0.7rem;
  letter-spacing: 0.05em;
}

.table-row {
  border-bottom: 1px solid var(--border-light);
  transition: background 0.1s;
}

.table-row:hover {
  background: var(--surface-hover);
}

.table-row.selected {
  background: var(--accent-light);
}

.col-check {
  width: 28px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
}

.col-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.col-bank { width: 80px; flex-shrink: 0; }
.col-cat { width: 90px; flex-shrink: 0; }
.col-subcat { width: 140px; flex-shrink: 0; }
.col-chunks { width: 50px; flex-shrink: 0; text-align: center; }
.col-status { width: 40px; flex-shrink: 0; text-align: center; }
.col-date { width: 100px; flex-shrink: 0; }
.col-actions { width: 130px; flex-shrink: 0; text-align: right; }

.doc-title-link {
  color: var(--fg);
  text-decoration: none;
}
.doc-title-link:hover {
  color: var(--accent);
  text-decoration: underline;
}

.cat-select {
  font-size: 0.75rem;
  padding: 0.2rem 0.3rem;
  max-width: 90px;
}

.subcat-input {
  font-size: 0.75rem;
  padding: 0.2rem 0.3rem;
  width: 120px;
}

.badge {
  display: inline-block;
  font-size: 0.7rem;
  padding: 0.15rem 0.4rem;
  border-radius: var(--radius-sm);
  background: var(--surface-hover);
  cursor: default;
}

.cat-badge, .subcat-badge {
  cursor: pointer;
  transition: background 0.1s;
}

.cat-badge:hover, .subcat-badge:hover {
  background: var(--accent-light);
  color: var(--accent);
}

.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.status-dot.ok { background: var(--success); }
.status-dot.pending { background: var(--warning); }

.btn-sm {
  font-size: 0.7rem;
  padding: 0.2rem 0.45rem;
  border-radius: var(--radius-sm);
}
.btn-sm.danger { color: var(--danger); border-color: var(--danger); }

.empty-state {
  text-align: center;
  padding: 3rem 0;
  color: var(--fg-muted);
}

@media (max-width: 768px) {
  .col-bank, .col-date, .col-chunks, .col-status, .col-actions { display: none; }
  .col-subcat { width: 100px; }
}
</style>
