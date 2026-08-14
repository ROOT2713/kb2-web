<template>
  <div class="synonyms-page">
    <h1 class="page-title">同义词管理</h1>

    <div class="toolbar">
      <input
        v-model="search"
        type="text"
        class="search-input"
        placeholder="搜索同义词..."
      />
      <button @click="loadSynonyms">刷新</button>
      <button v-if="authStore.isAdmin" class="primary" @click="openAdd">添加</button>
    </div>

    <LoadingSpinner v-if="loading" label="加载中..." />

    <div v-if="filteredSynonyms.length" class="syn-table card">
      <div class="table-header">
        <span class="col-term">词条</span>
        <span class="col-expansion">扩展</span>
        <span class="col-category">分类</span>
        <span class="col-actions">操作</span>
      </div>
      <div v-for="syn in filteredSynonyms" :key="syn.id" class="table-row">
        <span class="col-term">{{ syn.term }}</span>
        <span class="col-expansion">{{ syn.expansion }}</span>
        <span class="col-category">
          <span class="badge">{{ syn.category || '-' }}</span>
        </span>
        <span class="col-actions">
          <button v-if="authStore.isAdmin" class="btn-sm" @click="openEdit(syn)">编辑</button>
          <button v-if="authStore.isAdmin" class="btn-sm danger" @click="handleDelete(syn.id)">删除</button>
        </span>
      </div>
    </div>

    <div v-else-if="!loading" class="empty-state">
      <p>暂无同义词</p>
    </div>

    <!-- Inline form dialog -->
    <div v-if="showForm" class="dialog-overlay" @click.self="closeForm">
      <div class="dialog card">
        <h2 class="dialog-title">{{ editingId ? '编辑' : '添加' }}同义词</h2>
        <form @submit.prevent="handleSubmit">
          <div class="form-row">
            <label class="form-label">词条</label>
            <input v-model="form.term" type="text" placeholder="术语" required />
          </div>
          <div class="form-row">
            <label class="form-label">扩展</label>
            <input v-model="form.expansion" type="text" placeholder="扩展写法" required />
          </div>
          <div class="form-row">
            <label class="form-label">分类</label>
            <input v-model="form.category" type="text" placeholder="可选分类" />
          </div>
          <div class="form-actions">
            <button type="submit" class="primary" :disabled="submitting">
              {{ submitting ? '提交中...' : '提交' }}
            </button>
            <button type="button" @click="closeForm">取消</button>
          </div>
        </form>
      </div>
    </div>

    <Toast v-if="toastMsg" :message="toastMsg" :type="toastType" @close="toastMsg = ''" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import Toast from '@/components/Toast.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import { useAuthStore } from '@/stores/auth'
import {
  listSynonyms,
  addSynonym,
  updateSynonym,
  deleteSynonym,
  type SynonymItem,
} from '@/services/synonyms'

const authStore = useAuthStore()

const synonyms = ref<SynonymItem[]>([])
const loading = ref(false)
const search = ref('')
const toastMsg = ref('')
const toastType = ref<'info' | 'success' | 'error' | 'warning'>('info')

const showForm = ref(false)
const editingId = ref<number | null>(null)
const submitting = ref(false)
const form = ref({ term: '', expansion: '', category: '' })

const filteredSynonyms = computed(() => {
  const q = search.value.toLowerCase().trim()
  if (!q) return synonyms.value
  return synonyms.value.filter(
    (s) =>
      s.term.toLowerCase().includes(q) ||
      s.expansion.toLowerCase().includes(q) ||
      s.category.toLowerCase().includes(q),
  )
})

onMounted(() => {
  loadSynonyms()
})

async function loadSynonyms() {
  loading.value = true
  try {
    synonyms.value = await listSynonyms()
  } catch {
    toastMsg.value = '加载同义词失败'
    toastType.value = 'error'
  } finally {
    loading.value = false
  }
}

function openAdd() {
  editingId.value = null
  form.value = { term: '', expansion: '', category: '' }
  showForm.value = true
}

function openEdit(syn: SynonymItem) {
  editingId.value = syn.id
  form.value = { term: syn.term, expansion: syn.expansion, category: syn.category }
  showForm.value = true
}

function closeForm() {
  showForm.value = false
  editingId.value = null
}

async function handleSubmit() {
  if (!form.value.term.trim() || !form.value.expansion.trim()) return
  submitting.value = true
  try {
    const payload = {
      term: form.value.term.trim(),
      expansion: form.value.expansion.trim(),
      category: form.value.category.trim() || undefined,
    }
    if (editingId.value) {
      await updateSynonym(editingId.value, payload)
      toastMsg.value = '更新成功'
    } else {
      await addSynonym(payload)
      toastMsg.value = '添加成功'
    }
    toastType.value = 'success'
    closeForm()
    await loadSynonyms()
  } catch {
    toastMsg.value = '操作失败'
    toastType.value = 'error'
  } finally {
    submitting.value = false
  }
}

async function handleDelete(id: number) {
  if (!confirm('确认删除此同义词？')) return
  try {
    await deleteSynonym(id)
    toastMsg.value = '已删除'
    toastType.value = 'success'
    await loadSynonyms()
  } catch {
    toastMsg.value = '删除失败（可能需要管理员 Basic Auth）'
    toastType.value = 'error'
  }
}
</script>

<style scoped>
.synonyms-page {
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
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.search-input {
  flex: 1;
}

.syn-table {
  padding: 0;
  overflow: hidden;
}

.table-header {
  display: grid;
  grid-template-columns: 1fr 1fr 120px 130px;
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
  grid-template-columns: 1fr 1fr 120px 130px;
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

.col-actions {
  display: flex;
  gap: 0.35rem;
}

.btn-sm {
  font-size: 0.72rem;
  padding: 0.25rem 0.5rem;
}

.empty-state {
  text-align: center;
  padding: 3rem;
  color: var(--fg-muted);
  font-size: 0.9rem;
}

/* Dialog */
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.25);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 300;
}

.dialog {
  width: 400px;
  max-width: 90vw;
  padding: 1.5rem;
}

.dialog-title {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 1rem;
}

.form-row {
  margin-bottom: 0.75rem;
}

.form-label {
  display: block;
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--fg-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.3rem;
}

.form-row input {
  width: 100%;
}

.form-actions {
  margin-top: 1rem;
  display: flex;
  gap: 0.5rem;
}
</style>
