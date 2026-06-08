<template>
  <div class="banks-page">
    <h1 class="page-title">知识库管理</h1>

    <div class="banks-grid">
      <div v-for="bank in banksStore.banks" :key="bank.key" class="bank-card card">
        <div class="bank-card-header">
          <h3 class="bank-card-name">{{ bank.name }}</h3>
          <span class="bank-card-count">{{ bank.count }} 文档</span>
        </div>
        <p class="bank-card-desc">{{ bank.description || '暂无描述' }}</p>
        <div class="bank-card-meta">
          <span class="badge">{{ bank.key }}</span>
          <span v-if="bank.searchable" class="searchable-count">
            {{ bank.searchable }} 可搜索
          </span>
        </div>
        <div v-if="bank.key !== 'all'" class="bank-card-actions">
          <button class="btn-sm danger" @click="handleDelete(bank.key)">删除</button>
        </div>
      </div>
    </div>

    <div class="create-section card">
      <h2 class="section-title">新建知识库</h2>
      <form class="create-form" @submit.prevent="handleCreate">
        <div class="form-row">
          <label class="form-label">标识 (key)</label>
          <input v-model="newKey" type="text" placeholder="仅小写字母和下划线" />
        </div>
        <div class="form-row">
          <label class="form-label">名称</label>
          <input v-model="newLabel" type="text" placeholder="显示名称" />
        </div>
        <div class="form-row">
          <label class="form-label">描述</label>
          <input v-model="newDesc" type="text" placeholder="可选描述" />
        </div>
        <div class="form-actions">
          <button
            type="submit"
            class="primary"
            :disabled="!newKey.trim() || !newLabel.trim() || creating"
          >
            {{ creating ? '创建中...' : '创建' }}
          </button>
        </div>
      </form>
    </div>

    <Toast v-if="toastMsg" :message="toastMsg" :type="toastType" @close="toastMsg = ''" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useBanksStore } from '@/stores/banks'
import Toast from '@/components/Toast.vue'

const banksStore = useBanksStore()

const newKey = ref('')
const newLabel = ref('')
const newDesc = ref('')
const creating = ref(false)
const toastMsg = ref('')
const toastType = ref<'info' | 'success' | 'error' | 'warning'>('info')

onMounted(() => {
  banksStore.fetchBanks()
})

async function handleCreate() {
  if (!newKey.value.trim() || !newLabel.value.trim()) return
  creating.value = true
  try {
    await banksStore.addBank({
      key: newKey.value.trim(),
      label: newLabel.value.trim(),
      description: newDesc.value.trim(),
    })
    toastMsg.value = '知识库创建成功'
    toastType.value = 'success'
    newKey.value = ''
    newLabel.value = ''
    newDesc.value = ''
  } catch {
    toastMsg.value = banksStore.error || '创建失败'
    toastType.value = 'error'
  } finally {
    creating.value = false
  }
}

async function handleDelete(key: string) {
  if (!confirm(`确认删除知识库 "${key}"？`)) return
  try {
    await banksStore.removeBank(key, true)
    toastMsg.value = '已删除'
    toastType.value = 'success'
  } catch {
    toastMsg.value = banksStore.error || '删除失败'
    toastType.value = 'error'
  }
}
</script>

<style scoped>
.banks-page {
  max-width: 900px;
}

.page-title {
  font-size: clamp(1.1rem, 2vw, 1.4rem);
  font-weight: 700;
  margin-bottom: 1.25rem;
  letter-spacing: -0.02em;
}

.banks-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}

.bank-card {
  padding: 1rem;
}

.bank-card-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 0.35rem;
}

.bank-card-name {
  font-size: 0.95rem;
  font-weight: 600;
}

.bank-card-count {
  font-size: 0.75rem;
  color: var(--fg-muted);
}

.bank-card-desc {
  font-size: 0.8rem;
  color: var(--fg-muted);
  margin-bottom: 0.5rem;
}

.bank-card-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.searchable-count {
  font-size: 0.7rem;
  color: var(--success);
}

.bank-card-actions {
  padding-top: 0.5rem;
  border-top: 1px solid var(--border);
}

.btn-sm {
  font-size: 0.72rem;
  padding: 0.25rem 0.5rem;
}

.section-title {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 1rem;
}

.create-form {
  max-width: 400px;
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
}
</style>
