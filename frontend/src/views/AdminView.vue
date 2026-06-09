<template>
  <div class="admin-page">
    <h1 class="page-title">管理</h1>

    <!-- 系统状态 -->
    <section class="card">
      <h2 class="section-title">系统状态</h2>
      <button :disabled="statsLoading" @click="loadStats">
        {{ statsLoading ? '加载中...' : '加载系统状态' }}
      </button>
      <div v-if="statsError" class="error-msg">{{ statsError }}</div>
      <div v-if="stats" class="stats-grid">
        <div class="stat-item">
          <span class="stat-value">{{ stats.total_nodes }}</span>
          <span class="stat-label">节点总数</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">{{ stats.total_documents }}</span>
          <span class="stat-label">文档总数</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">{{ stats.total_links }}</span>
          <span class="stat-label">链接总数</span>
        </div>
      </div>
      <div v-if="health" class="health-info">
        <div class="health-row"><span>状态</span><span class="badge">{{ health.status }}</span></div>
        <div class="health-row"><span>数据库</span><span>{{ health.db }}</span></div>
        <div class="health-row"><span>版本</span><span>{{ health.version }}</span></div>
        <div class="health-row"><span>Hindsight</span><span>{{ health.hindsight }}</span></div>
      </div>
    </section>

    <!-- 质量审计 -->
    <section class="card">
      <h2 class="section-title">质量审计</h2>
      <button :disabled="auditLoading" @click="loadAudit">
        {{ auditLoading ? '加载中...' : '加载审计数据' }}
      </button>
      <div v-if="auditError" class="error-msg">{{ auditError }}</div>
      <div v-if="audit" class="audit-summary">
        <div class="stat-item">
          <span class="stat-value">{{ audit.total_docs }}</span>
          <span class="stat-label">总文档</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">{{ audit.avg_score?.toFixed(2) }}</span>
          <span class="stat-label">平均分</span>
        </div>
        <div class="stat-item">
          <span class="stat-value danger">{{ audit.low_quality_count }}</span>
          <span class="stat-label">低质量</span>
        </div>
      </div>
      <div v-if="lowQualityDocs.length" class="audit-table">
        <div class="table-header">
          <span class="col-doc">文档</span>
          <span class="col-bank">知识库</span>
          <span class="col-score">评分</span>
          <span class="col-issues">问题</span>
        </div>
        <div v-for="doc in lowQualityDocs" :key="doc.doc_id" class="table-row">
          <span class="col-doc">
            <RouterLink :to="'/documents/' + doc.doc_id" class="doc-link">{{ doc.title }}</RouterLink>
          </span>
          <span class="col-bank"><span class="badge">{{ doc.bank }}</span></span>
          <span class="col-score" :class="{ 'danger': doc.score < 0.5 }">{{ doc.score?.toFixed(2) }}</span>
          <span class="col-issues">{{ doc.issues?.join(', ') || '-' }}</span>
        </div>
      </div>
    </section>

    <!-- RAG 评估 -->
    <section class="card">
      <h2 class="section-title">RAG 评估</h2>
      <button :disabled="ragLoading" @click="loadRagEval">
        {{ ragLoading ? '评估中（可能需要 1-2 分钟）...' : '运行 RAG 评估' }}
      </button>
      <div v-if="ragError" class="error-msg">{{ ragError }}</div>
      <div v-if="ragEval" class="rag-result">
        <div class="stat-item">
          <span class="stat-value">{{ ragEval.overall?.toFixed(3) }}</span>
          <span class="stat-label">总体评分</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">{{ ragEval.total_cases }}</span>
          <span class="stat-label">总案例</span>
        </div>
        <div class="stat-item">
          <span class="stat-value">{{ ragEval.evaluated }}</span>
          <span class="stat-label">已评估</span>
        </div>
        <div v-if="ragEval.avg_scores" class="avg-scores">
          <h3>分项评分</h3>
          <div v-for="(score, key) in ragEval.avg_scores" :key="key" class="score-row">
            <span>{{ key }}</span>
            <span>{{ (score as number).toFixed(3) }}</span>
          </div>
        </div>
        <details v-if="ragEval.details?.length" class="rag-details">
          <summary>详细结果 ({{ ragEval.details.length }} 条)</summary>
          <pre>{{ JSON.stringify(ragEval.details, null, 2) }}</pre>
        </details>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import {
  getStats,
  getHealth,
  getAudit,
  getRagEval,
  type AdminStats,
  type AdminHealth,
  type AuditResponse,
  type AuditDocument,
  type RagEvalResponse,
} from '@/services/admin'

const stats = ref<AdminStats | null>(null)
const health = ref<AdminHealth | null>(null)
const statsLoading = ref(false)
const statsError = ref('')

const audit = ref<AuditResponse | null>(null)
const auditLoading = ref(false)
const auditError = ref('')

const ragEval = ref<RagEvalResponse | null>(null)
const ragLoading = ref(false)
const ragError = ref('')

const lowQualityDocs = ref<AuditDocument[]>([])

async function loadStats() {
  statsLoading.value = true
  statsError.value = ''
  try {
    const [s, h] = await Promise.all([getStats(), getHealth()])
    stats.value = s
    health.value = h
  } catch (e: unknown) {
    statsError.value = (e as Error).message || '加载失败'
  } finally {
    statsLoading.value = false
  }
}

async function loadAudit() {
  auditLoading.value = true
  auditError.value = ''
  try {
    const a = await getAudit()
    audit.value = a
    // Sort by score ascending, take top 30
    lowQualityDocs.value = [...a.documents]
      .sort((x, y) => x.score - y.score)
      .slice(0, 30)
  } catch (e: unknown) {
    auditError.value = (e as Error).message || '加载失败'
  } finally {
    auditLoading.value = false
  }
}

async function loadRagEval() {
  ragLoading.value = true
  ragError.value = ''
  try {
    ragEval.value = await getRagEval()
  } catch (e: unknown) {
    ragError.value = (e as Error).message || '评估失败'
  } finally {
    ragLoading.value = false
  }
}
</script>

<style scoped>
.admin-page {
  max-width: 900px;
}

.page-title {
  font-size: clamp(1.1rem, 2vw, 1.4rem);
  font-weight: 700;
  margin-bottom: 1.25rem;
  letter-spacing: -0.02em;
}

.card {
  margin-bottom: 1.5rem;
}

.section-title {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
}

.stats-grid,
.audit-summary {
  display: flex;
  gap: 1.5rem;
  margin-top: 1rem;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.2rem;
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--accent);
}

.stat-value.danger {
  color: var(--danger);
}

.stat-label {
  font-size: 0.7rem;
  color: var(--fg-muted);
  text-transform: uppercase;
}

.health-info {
  margin-top: 1rem;
  font-size: 0.85rem;
}

.health-row {
  display: flex;
  justify-content: space-between;
  padding: 0.35rem 0;
  border-bottom: 1px solid var(--bg-alt);
  max-width: 400px;
}

.error-msg {
  margin-top: 0.5rem;
  color: var(--danger);
  font-size: 0.85rem;
}

.audit-table {
  margin-top: 1rem;
  overflow: hidden;
}

.table-header {
  display: grid;
  grid-template-columns: 1fr 100px 60px 1fr;
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
  grid-template-columns: 1fr 100px 60px 1fr;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  font-size: 0.8rem;
  align-items: center;
  border-bottom: 1px solid var(--bg-alt);
}

.col-doc {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-link {
  color: var(--fg);
  text-decoration: none;
}

.doc-link:hover {
  color: var(--accent);
  text-decoration: underline;
}

.col-score.danger {
  color: var(--danger);
  font-weight: 600;
}

.col-issues {
  color: var(--fg-muted);
  font-size: 0.75rem;
}

.rag-result {
  margin-top: 1rem;
}

.avg-scores {
  margin-top: 1rem;
}

.avg-scores h3 {
  font-size: 0.85rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
}

.score-row {
  display: flex;
  justify-content: space-between;
  max-width: 300px;
  padding: 0.25rem 0;
  font-size: 0.85rem;
  border-bottom: 1px solid var(--bg-alt);
}

.rag-details {
  margin-top: 1rem;
}

.rag-details pre {
  font-size: 0.75rem;
  max-height: 400px;
  overflow: auto;
  background: var(--bg-alt);
  padding: 0.5rem;
}
</style>
