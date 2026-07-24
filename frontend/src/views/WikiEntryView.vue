<template>
  <div class="wiki-entry-page">
    <h1 class="page-title">Wiki 结构化知识库</h1>

    <!-- Toolbar -->
    <div class="toolbar">
      <div class="search-row">
        <input v-model="searchQuery" type="text" class="search-input" placeholder="搜索标准/条目名称…"
               @keyup.enter="doSearch" />
        <select v-model="filterCategory" class="filter-select">
          <option value="">全部分类</option>
          <option v-for="c in categories" :key="c.category" :value="c.category">
            {{ c.category }} ({{ c.cnt }})
          </option>
        </select>
        <button @click="doSearch" class="btn-primary">搜索</button>
        <button v-if="authStore.isAdmin" @click="showCreate = true" class="btn-secondary">+ 新建条目</button>
      </div>
    </div>

    <LoadingSpinner v-if="loading" label="加载中…" />

    <div v-if="error" class="error-msg">{{ error }}</div>

    <!-- Entry list -->
    <div v-if="entries.length" class="entry-list">
      <div v-for="entry in entries" :key="entry.id" class="entry-card"
           @click="viewEntry(entry.id)">
        <div class="entry-header">
          <span v-if="entry.standard_no" class="std-badge">{{ entry.standard_no }}</span>
          <span class="entry-title">{{ entry.title }}</span>
          <span class="entry-cat">{{ entry.category }}</span>
          <span v-if="entry.importance > 5" class="imp-badge">重要</span>
        </div>
        <div class="entry-summary">{{ entry.summary || '暂无摘要' }}</div>
        <div class="entry-meta">
          <span class="meta-status" :class="entry.status">{{ statusLabel(entry.status) }}</span>
          <span class="meta-date">{{ entry.updated_at?.slice(0,10) }}</span>
        </div>
      </div>
    </div>

    <div v-else-if="!loading && !error" class="empty-state">
      <p>暂无条目。{{ authStore.isAdmin ? '点击"+ 新建条目"创建第一个。' : '' }}</p>
    </div>

    <!-- Detail panel -->
    <div v-if="selectedEntry" class="detail-panel" @click.self="selectedEntry = null">
      <div class="detail-card">
        <button class="close-btn" @click="selectedEntry = null">✕</button>
        <h2>{{ selectedEntry.title }}</h2>
        <div v-if="selectedEntry.standard_no" class="std-row">
          <strong>标准编号：</strong>{{ selectedEntry.standard_no }}
        </div>
        <div class="meta-row">
          <span class="meta-tag">{{ selectedEntry.category }}</span>
          <span v-if="selectedEntry.subcategory" class="meta-tag">{{ selectedEntry.subcategory }}</span>
          <span class="meta-status" :class="selectedEntry.status">{{ statusLabel(selectedEntry.status) }}</span>
        </div>

        <div v-if="selectedEntry.summary" class="section">
          <h3>摘要</h3>
          <p>{{ selectedEntry.summary }}</p>
        </div>

        <div v-if="selectedContent.scope" class="section">
          <h3>适用范围</h3>
          <p>{{ selectedContent.scope }}</p>
        </div>
        <div v-if="selectedContent.key_clauses" class="section">
          <h3>核心条款</h3>
          <p style="white-space:pre-wrap">{{ selectedContent.key_clauses }}</p>
        </div>
        <div v-if="selectedContent.application" class="section">
          <h3>应用场景</h3>
          <p>{{ selectedContent.application }}</p>
        </div>
        <div v-if="selectedContent.notes" class="section">
          <h3>备注</h3>
          <p>{{ selectedContent.notes }}</p>
        </div>

        <!-- Relations -->
        <div v-if="selectedEntry.relations?.length" class="section">
          <h3>交叉引用（{{ selectedEntry.relations.length }}）</h3>
          <ul class="rel-list">
            <li v-for="rel in selectedEntry.relations" :key="rel.id">
              {{ rel.relation_type }} → <a href="#" @click.prevent="viewEntry(rel.target_entry_id)">{{ rel.target_title }}</a>
              <span v-if="rel.target_std" class="std-badge">{{ rel.target_std }}</span>
            </li>
          </ul>
        </div>

        <div v-if="authStore.isAdmin && selectedEntry" class="admin-row">
          <button @click="deleteEntry(selectedEntry.id)" class="btn-danger btn-sm">删除</button>
        </div>
      </div>
    </div>

    <!-- Create form -->
    <div v-if="showCreate" class="modal-overlay" @click.self="showCreate = false">
      <div class="modal-card">
        <h2>新建 Wiki 条目</h2>
        <div class="form-row">
          <label>标题 *</label>
          <input v-model="form.title" type="text" class="form-input" />
        </div>
        <div class="form-row">
          <label>标准编号</label>
          <input v-model="form.standard_no" type="text" class="form-input" placeholder="e.g. GB 50174-2017" />
        </div>
        <div class="form-row">
          <label>分类</label>
          <select v-model="form.category" class="form-input">
            <option value="">选择分类</option>
            <option>standard</option>
            <option>faq</option>
            <option>guide</option>
            <option>term</option>
          </select>
        </div>
        <div class="form-row">
          <label>摘要</label>
          <textarea v-model="form.summary" class="form-input" rows="2"></textarea>
        </div>
        <div class="form-row">
          <label>适用范围</label>
          <textarea v-model="form.scope" class="form-input" rows="2"></textarea>
        </div>
        <div class="form-row">
          <label>核心条款</label>
          <textarea v-model="form.key_clauses" class="form-input" rows="4"></textarea>
        </div>
        <div class="form-actions">
          <button @click="submitCreate" class="btn-primary" :disabled="!form.title.trim()">创建</button>
          <button @click="showCreate = false" class="btn-secondary">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import LoadingSpinner from '@/components/LoadingSpinner.vue'

const authStore = useAuthStore()

interface WikiEntry {
  id: number; title: string; standard_no: string; category: string
  subcategory: string; tags: string[]; summary: string
  content: Record<string, string>; source_doc_id: string
  importance: number; status: string; created_at: string; updated_at: string
  relations?: WikiRelation[]
}
interface WikiRelation {
  id: number; source_entry_id: number; target_entry_id: number
  relation_type: string; description: string
  target_title: string; target_std: string
}
interface CategoryCount {
  category: string; subcategory: string; cnt: number
}

const entries = ref<WikiEntry[]>([])
const categories = ref<CategoryCount[]>([])
const selectedEntry = ref<WikiEntry | null>(null)
const selectedContent = ref<Record<string, string>>({})
const loading = ref(false)
const error = ref('')
const searchQuery = ref('')
const filterCategory = ref('')
const showCreate = ref(false)

const form = ref({
  title: '', standard_no: '', category: 'standard',
  summary: '', scope: '', key_clauses: '',
})

function statusLabel(s: string) {
  const m: Record<string, string> = { published: '已发布', draft: '草稿', archived: '已归档' }
  return m[s] || s
}

onMounted(() => {
  loadCategories()
  doSearch()
})

async function loadCategories() {
  try {
    const { data } = await api.get('/wiki/categories')
    categories.value = data.categories || []
  } catch { /* ignore */ }
}

async function doSearch() {
  loading.value = true; error.value = ''
  try {
    const { data } = await api.get('/wiki/search', {
      params: { q: searchQuery.value, category: filterCategory.value, limit: 50 },
    })
    entries.value = data.items || []
  } catch (e: unknown) {
    error.value = (e as Error).message || '搜索失败'
  } finally {
    loading.value = false
  }
}

async function viewEntry(id: number) {
  loading.value = true
  try {
    const { data } = await api.get(`/wiki/entry/${id}`)
    selectedEntry.value = data
    selectedContent.value = (data.content || {}) as Record<string, string>
  } catch (e: unknown) {
    error.value = (e as Error).message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function submitCreate() {
  if (!form.value.title.trim()) return
  loading.value = true
  try {
    const content: Record<string, string> = {}
    if (form.value.scope) content.scope = form.value.scope
    if (form.value.key_clauses) content.key_clauses = form.value.key_clauses
    await api.post('/wiki/entry', {
      title: form.value.title,
      standard_no: form.value.standard_no,
      category: form.value.category,
      summary: form.value.summary || form.value.title,
      content,
      status: 'draft',
      importance: 5,
    })
    showCreate.value = false
    form.value = { title: '', standard_no: '', category: 'standard', summary: '', scope: '', key_clauses: '' }
    doSearch()
  } catch (e: unknown) {
    error.value = (e as Error).message || '创建失败'
  } finally {
    loading.value = false
  }
}

async function deleteEntry(id: number) {
  if (!confirm('确认删除此条目？')) return
  try {
    await api.delete(`/wiki/entry/${id}`)
    selectedEntry.value = null
    doSearch()
  } catch (e: unknown) {
    error.value = (e as Error).message || '删除失败'
  }
}
</script>

<style scoped>
.wiki-entry-page { max-width: 900px; }
.page-title { font-size: clamp(1.1rem, 2vw, 1.4rem); font-weight: 700; margin-bottom: 1.25rem; letter-spacing: -0.02em; }
.toolbar { margin-bottom: 1rem; }
.search-row { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }
.search-input { flex: 1; min-width: 180px; padding: 0.45rem 0.75rem; border: 1px solid var(--border); border-radius: 6px; font-size: 0.85rem; background: var(--bg); color: var(--fg); }
.filter-select { padding: 0.45rem 0.5rem; border: 1px solid var(--border); border-radius: 6px; font-size: 0.85rem; background: var(--bg); color: var(--fg); }
.error-msg { color: var(--danger); font-size: 0.85rem; margin-bottom: 1rem; }

.entry-list { display: flex; flex-direction: column; gap: 0.5rem; }
.entry-card { padding: 0.75rem 1rem; border: 1px solid var(--border); border-radius: 6px; cursor: pointer; transition: border-color 0.15s; }
.entry-card:hover { border-color: var(--accent); }
.entry-header { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.3rem; }
.std-badge { font-family: monospace; font-size: 0.75rem; padding: 0.1rem 0.4rem; background: var(--accent-subtle, #e0e7ff); color: var(--accent); border-radius: 4px; }
.entry-title { font-weight: 600; font-size: 0.9rem; }
.entry-cat { font-size: 0.75rem; color: var(--fg-muted); }
.imp-badge { font-size: 0.7rem; padding: 0.05rem 0.35rem; background: #fef3c7; color: #92400e; border-radius: 4px; }
.entry-summary { font-size: 0.8rem; color: var(--fg-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.entry-meta { display: flex; gap: 1rem; margin-top: 0.3rem; font-size: 0.75rem; }
.meta-status { padding: 0.05rem 0.35rem; border-radius: 4px; }
.meta-status.published { background: #d1fae5; color: #065f46; }
.meta-status.draft { background: #f3f4f6; color: #6b7280; }
.meta-date { color: var(--fg-muted); }

.empty-state { text-align: center; padding: 3rem; color: var(--fg-muted); }

.detail-panel { position: fixed; inset: 0; background: rgba(0,0,0,0.4); z-index: 100; display: flex; align-items: center; justify-content: center; }
.detail-card { background: var(--bg); border-radius: 10px; padding: 1.5rem; max-width: 600px; width: 90%; max-height: 80vh; overflow-y: auto; position: relative; }
.close-btn { position: absolute; top: 0.75rem; right: 0.75rem; background: none; border: none; font-size: 1.2rem; cursor: pointer; color: var(--fg-muted); }
.std-row { font-size: 0.85rem; margin-bottom: 0.5rem; }
.meta-row { display: flex; gap: 0.5rem; margin-bottom: 0.75rem; flex-wrap: wrap; }
.meta-tag { font-size: 0.75rem; padding: 0.1rem 0.4rem; background: var(--bg-alt); border-radius: 4px; color: var(--fg-muted); }
.section { margin-top: 1rem; }
.section h3 { font-size: 0.85rem; font-weight: 600; margin-bottom: 0.35rem; color: var(--fg); }
.section p { font-size: 0.85rem; line-height: 1.5; color: var(--fg); }
.rel-list { list-style: none; padding: 0; }
.rel-list li { font-size: 0.85rem; padding: 0.25rem 0; }
.admin-row { margin-top: 1rem; padding-top: 0.75rem; border-top: 1px solid var(--border); }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); z-index: 200; display: flex; align-items: center; justify-content: center; }
.modal-card { background: var(--bg); border-radius: 10px; padding: 1.5rem; max-width: 500px; width: 90%; max-height: 80vh; overflow-y: auto; }
.modal-card h2 { font-size: 1rem; margin-bottom: 1rem; }
.form-row { margin-bottom: 0.75rem; }
.form-row label { display: block; font-size: 0.8rem; font-weight: 500; margin-bottom: 0.25rem; }
.form-input { width: 100%; padding: 0.4rem 0.6rem; border: 1px solid var(--border); border-radius: 6px; font-size: 0.85rem; background: var(--bg); color: var(--fg); box-sizing: border-box; }
textarea.form-input { resize: vertical; font-family: inherit; }
.form-actions { display: flex; gap: 0.5rem; margin-top: 1rem; }
</style>
