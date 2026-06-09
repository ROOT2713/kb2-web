<template>
  <div class="document-detail-page">
    <div class="detail-header">
      <button class="btn-back" @click="router.back()">← 返回</button>
      <h1 class="page-title">{{ docDetail?.title || '文档详情' }}</h1>
    </div>

    <LoadingSpinner v-if="loading" label="加载中..." />

    <div v-else-if="error" class="error-state">
      <p>{{ error }}</p>
      <button @click="loadDetail">重试</button>
    </div>

    <div v-else-if="docDetail" class="detail-content">
      <!-- 基本信息卡片 -->
      <div class="info-card card">
        <h2 class="section-title">基本信息</h2>
        <div class="info-grid">
          <div class="info-item">
            <span class="info-label">标题</span>
            <span class="info-value">{{ docDetail.title }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">文档 ID</span>
            <span class="info-value mono">{{ docDetail.doc_id }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">文件名</span>
            <span class="info-value">{{ docDetail.filename || '-' }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">所属知识库</span>
            <span class="info-value"><span class="badge">{{ docDetail.bank || 'kb' }}</span></span>
          </div>
          <div class="info-item">
            <span class="info-label">分块数</span>
            <span class="info-value">{{ docDetail.chunks || 0 }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">状态</span>
            <span class="info-value">
              <span class="status-dot" :class="docDetail.searchable ? 'ok' : 'pending'"></span>
              {{ docDetail.searchable ? '已索引' : '待索引' }}
            </span>
          </div>
          <div class="info-item">
            <span class="info-label">创建时间</span>
            <span class="info-value">{{ formatDate(docDetail.created || '') }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">覆盖率</span>
            <span class="info-value">{{ docDetail.coverage_pct || 0 }}%</span>
          </div>
        </div>
      </div>

      <!-- 文档内容预览 -->
      <div v-if="docDetail.text" class="content-card card">
        <h2 class="section-title">内容预览</h2>
        <div class="content-preview">
          <pre class="content-text">{{ docDetail.text.substring(0, 5000) }}{{ docDetail.text.length > 5000 ? '...' : '' }}</pre>
        </div>
        <p class="content-meta">总字数: {{ docDetail.text.length.toLocaleString() }}</p>
      </div>

      <!-- 操作 -->
      <div class="action-bar">
        <button class="btn-primary" @click="handleReparse">重解析</button>
        <button class="btn-danger" @click="handleDelete">删除文档</button>
      </div>
    </div>

    <Toast v-if="toastMsg" :message="toastMsg" :type="toastType" @close="toastMsg = ''" />
  </div>
</template>

<script setup lang="ts">
/**
 * 文档详情页 — 展示文档的基本信息、内容预览和操作按钮
 * 路由: /documents/:id
 */
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getDocument, type DocumentDetail } from '@/services/documents'
import { useDocumentsStore } from '@/stores/documents'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import Toast from '@/components/Toast.vue'

const route = useRoute()
const router = useRouter()
const docsStore = useDocumentsStore()

const docDetail = ref<DocumentDetail | null>(null)
const loading = ref(true)
const error = ref('')
const toastMsg = ref('')
const toastType = ref<'info' | 'success' | 'error' | 'warning'>('info')

onMounted(() => {
  loadDetail()
})

async function loadDetail() {
  const docId = Array.isArray(route.params.id) ? route.params.id[0] : route.params.id
  if (!docId) {
    error.value = '缺少文档 ID'
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  try {
    docDetail.value = await getDocument(docId)
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

function formatDate(iso: string): string {
  if (!iso) return '-'
  return iso.substring(0, 10)
}

async function handleDelete() {
  if (!docDetail.value) return
  if (!confirm(`确认删除文档「${docDetail.value.title}」？`)) return
  try {
    await docsStore.removeDocument(docDetail.value.doc_id)
    toastMsg.value = '已删除'
    toastType.value = 'success'
    setTimeout(() => router.push('/documents'), 1000)
  } catch {
    toastMsg.value = '删除失败'
    toastType.value = 'error'
  }
}

async function handleReparse() {
  if (!docDetail.value) return
  try {
    await docsStore.reparse(docDetail.value.doc_id)
    toastMsg.value = '重新解析完成'
    toastType.value = 'success'
    loadDetail()
  } catch {
    toastMsg.value = '重新解析失败'
    toastType.value = 'error'
  }
}
</script>

<style scoped>
.document-detail-page {
  max-width: 860px;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.25rem;
}

.btn-back {
  font-size: 0.825rem;
  padding: 0.35rem 0.75rem;
  background: var(--bg-alt);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  color: var(--fg);
  transition: background 0.15s;
}

.btn-back:hover {
  background: var(--border);
}

.page-title {
  font-size: clamp(1.1rem, 2vw, 1.4rem);
  font-weight: 700;
  letter-spacing: -0.02em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.info-card {
  padding: 1.25rem;
  margin-bottom: 1rem;
}

.section-title {
  font-size: 0.85rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--fg-muted);
  margin-bottom: 1rem;
}

.info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.85rem 2rem;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.info-label {
  font-size: 0.72rem;
  color: var(--fg-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.info-value {
  font-size: 0.875rem;
  color: var(--fg);
  word-break: break-all;
}

.info-value.mono {
  font-family: monospace;
  font-size: 0.78rem;
  color: var(--fg-muted);
}

.content-card {
  padding: 1.25rem;
  margin-bottom: 1rem;
}

.content-preview {
  max-height: 400px;
  overflow-y: auto;
  background: var(--bg-alt);
  border-radius: 8px;
  padding: 1rem;
  border: 1px solid var(--border);
}

.content-text {
  font-size: 0.8rem;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  font-family: inherit;
}

.content-meta {
  font-size: 0.75rem;
  color: var(--fg-muted);
  margin-top: 0.5rem;
}

.action-bar {
  display: flex;
  gap: 0.75rem;
  margin-top: 0.5rem;
}

.btn-primary {
  padding: 0.5rem 1.25rem;
  font-size: 0.85rem;
}

.btn-danger {
  padding: 0.5rem 1.25rem;
  font-size: 0.85rem;
  background: var(--danger);
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
}

.btn-danger:hover {
  opacity: 0.9;
}

.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
}

.status-dot.ok {
  background: var(--success);
}

.status-dot.pending {
  background: var(--border);
}

.badge {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  font-size: 0.7rem;
  background: var(--bg-alt);
  border-radius: 4px;
  border: 1px solid var(--border);
}

.error-state {
  text-align: center;
  padding: 3rem;
  color: var(--fg-muted);
}

.error-state button {
  margin-top: 1rem;
}
</style>
