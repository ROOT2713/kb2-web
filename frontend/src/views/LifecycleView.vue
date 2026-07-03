<template>
  <div class="lifecycle-page">
    <h1 class="page-title">文档生命周期</h1>
    <p class="page-desc">查看和管理文档过期状态</p>

    <!-- 操作按钮组 -->
    <div class="action-bar">
      <button :disabled="loading" @click="loadSummary" class="primary">
        {{ loading ? '加载中...' : '刷新状态' }}
      </button>
      <button :disabled="loadingDetect" @click="runDetection" class="btn-detect">
        {{ loadingDetect ? '检测中...' : '运行过期检测' }}
      </button>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>

    <!-- 统计卡 -->
    <section v-if="summary" class="card">
      <h2 class="section-title">过期文档统计</h2>
      <div class="stats-grid">
        <div class="stat-item">
          <span class="stat-value">{{ summary.active }}</span>
          <span class="stat-label">活跃</span>
        </div>
        <div class="stat-item">
          <span class="stat-value danger">{{ summary.stale }}</span>
          <span class="stat-label">过期</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">{{ summary.superseded }}</span>
          <span class="stat-label">已取代</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">{{ summary.total }}</span>
          <span class="stat-label">总计</span>
        </div>
      </div>
      <div v-if="summary.stale_by_reason && Object.keys(summary.stale_by_reason).length" class="reason-breakdown">
        <h3>过期原因分布</h3>
        <div v-for="(count, reason) in summary.stale_by_reason" :key="reason" class="reason-row">
          <span class="reason-label">{{ reason }}</span>
          <span class="reason-count">{{ count }}</span>
        </div>
      </div>
    </section>

    <!-- 过期文档列表 -->
    <section v-if="staleDocs.length" class="card">
      <h2 class="section-title">过期文档列表（{{ staleDocs.length }}）</h2>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th class="col-title">文档标题</th>
              <th class="col-bank">知识库</th>
              <th class="col-reason">过期原因</th>
              <th class="col-days">天数</th>
              <th class="col-actions">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="doc in staleDocs" :key="doc.doc_id">
              <td class="col-title">
                <RouterLink :to="'/documents/' + doc.doc_id" class="doc-link">
                  {{ doc.title || doc.doc_id.slice(0, 12) + '...' }}
                </RouterLink>
              </td>
              <td class="col-bank"><span class="badge">{{ doc.bank }}</span></td>
              <td class="col-reason"><span class="reason-text">{{ doc.stale_reason }}</span></td>
              <td class="col-days">{{ doc.days_since }}d</td>
              <td class="col-actions">
                <button
                  class="btn-sm btn-confirm"
                  :disabled="actionLoading === doc.doc_id"
                  @click="handleConfirm(doc.doc_id)"
                >
                  {{ actionLoading === doc.doc_id ? '确认中...' : '确认有效' }}
                </button>
                <button
                  class="btn-sm btn-restore"
                  :disabled="actionLoading === doc.doc_id"
                  @click="handleRestore(doc.doc_id)"
                >
                  {{ actionLoading === doc.doc_id ? '恢复中...' : '恢复' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 无过期文档 -->
    <section v-else-if="!loading && summary" class="card">
      <div class="empty-state">
        <p>✅ 没有过期文档</p>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import {
  getStaleSummary,
  detectStale,
  restoreDoc,
  confirmDoc,
  type StaleSummary,
  type StaleDoc,
} from '@/services/lifecycle'

const loading = ref(false)
const loadingDetect = ref(false)
const actionLoading = ref<string | null>(null)
const error = ref('')
const summary = ref<StaleSummary | null>(null)
const staleDocs = ref<StaleDoc[]>([])

async function loadSummary() {
  loading.value = true
  error.value = ''
  try {
    summary.value = await getStaleSummary()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载统计失败'
  } finally {
    loading.value = false
  }
}

async function runDetection() {
  loadingDetect.value = true
  error.value = ''
  try {
    const result = await detectStale(90, false)
    staleDocs.value = result.stale_docs || []
    summary.value = await getStaleSummary()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '检测失败'
  } finally {
    loadingDetect.value = false
  }
}

async function handleConfirm(docId: string) {
  actionLoading.value = docId
  error.value = ''
  try {
    await confirmDoc(docId)
    staleDocs.value = staleDocs.value.filter(d => d.doc_id !== docId)
    summary.value = await getStaleSummary()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '确认失败'
  } finally {
    actionLoading.value = null
  }
}

async function handleRestore(docId: string) {
  actionLoading.value = docId
  error.value = ''
  try {
    await restoreDoc(docId)
    staleDocs.value = staleDocs.value.filter(d => d.doc_id !== docId)
    summary.value = await getStaleSummary()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '恢复失败'
  } finally {
    actionLoading.value = null
  }
}
</script>

<style scoped>
.lifecycle-page {
  max-width: 900px;
}

.page-title {
  font-size: clamp(1.1rem, 2vw, 1.4rem);
  font-weight: 700;
  margin-bottom: 0.25rem;
  letter-spacing: -0.02em;
}

.page-desc {
  font-size: 0.85rem;
  color: var(--fg-muted, #666);
  margin-bottom: 1rem;
}

.action-bar {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.btn-detect {
  font-size: 0.85rem;
  padding: 0.5rem 1rem;
  border: 1px solid var(--border, #ddd);
  background: var(--bg-card, #fff);
  color: var(--fg, #333);
  cursor: pointer;
  border-radius: 4px;
}
.btn-detect:hover {
  border-color: var(--accent, #e67e22);
  color: var(--accent, #e67e22);
}

.card {
  background: var(--bg-card, #fff);
  border: 1px solid var(--border, #e0e0e0);
  border-radius: 6px;
  padding: 1rem 1.25rem;
  margin-bottom: 1rem;
}

.section-title {
  font-size: 0.95rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.75rem;
}

.stat-item {
  text-align: center;
}

.stat-value {
  display: block;
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--accent, #e67e22);
}

.stat-value.danger {
  color: #e74c3c;
}

.stat-label {
  font-size: 0.75rem;
  color: var(--fg-muted, #666);
}

.reason-breakdown {
  margin-top: 0.75rem;
  border-top: 1px solid var(--border, #eee);
  padding-top: 0.75rem;
}

.reason-breakdown h3 {
  font-size: 0.85rem;
  font-weight: 600;
  margin-bottom: 0.4rem;
}

.reason-row {
  display: flex;
  justify-content: space-between;
  font-size: 0.8rem;
  padding: 0.2rem 0;
}

.reason-label {
  color: var(--fg-muted, #666);
}

.reason-count {
  font-weight: 600;
}

.table-wrap {
  overflow-x: auto;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}

.data-table th {
  text-align: left;
  font-weight: 600;
  padding: 0.5rem 0.6rem;
  border-bottom: 2px solid var(--border, #e0e0e0);
  white-space: nowrap;
  color: var(--fg-muted, #666);
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.data-table td {
  padding: 0.5rem 0.6rem;
  border-bottom: 1px solid var(--border, #eee);
  vertical-align: middle;
}

.col-title { min-width: 220px; }
.col-bank { min-width: 80px; }
.col-reason { min-width: 160px; }
.col-days { min-width: 50px; text-align: center; }
.col-actions { min-width: 140px; white-space: nowrap; }

.doc-link {
  color: var(--accent, #e67e22);
  text-decoration: none;
  font-weight: 500;
}
.doc-link:hover {
  text-decoration: underline;
}

.badge {
  display: inline-block;
  font-size: 0.7rem;
  padding: 0.15rem 0.4rem;
  background: var(--bg-muted, #f5f5f5);
  border-radius: 3px;
  color: var(--fg-muted, #666);
}

.reason-text {
  color: #e74c3c;
  font-size: 0.75rem;
}

.btn-sm {
  font-size: 0.75rem;
  padding: 0.25rem 0.5rem;
  border: 1px solid var(--border, #ddd);
  border-radius: 3px;
  cursor: pointer;
  background: var(--bg-card, #fff);
  margin-right: 0.3rem;
}

.btn-confirm {
  color: #27ae60;
  border-color: #27ae60;
}
.btn-confirm:hover {
  background: #27ae60;
  color: #fff;
}

.btn-restore {
  color: #2980b9;
  border-color: #2980b9;
}
.btn-restore:hover {
  background: #2980b9;
  color: #fff;
}

.btn-sm:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error-msg {
  background: #fdecea;
  color: #c0392b;
  padding: 0.5rem 0.75rem;
  border-radius: 4px;
  font-size: 0.8rem;
  margin-bottom: 0.75rem;
}

.empty-state {
  text-align: center;
  padding: 1.5rem;
  color: var(--fg-muted, #666);
  font-size: 0.9rem;
}
</style>
