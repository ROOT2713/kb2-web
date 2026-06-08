<template>
  <div class="upload-page">
    <h1 class="page-title">上传文档</h1>

    <div
      class="drop-zone card"
      :class="{ dragover: isDragOver }"
      @dragover.prevent="isDragOver = true"
      @dragleave="isDragOver = false"
      @drop.prevent="handleDrop"
    >
      <div class="drop-content">
        <p class="drop-text">拖拽文件到此处，或</p>
        <label class="upload-btn-wrap">
          <button type="button" class="primary">选择文件</button>
          <input
            ref="fileInput"
            type="file"
            class="file-input-hidden"
            accept=".pdf,.docx,.doc,.xlsx,.xls,.txt,.md,.csv"
            @change="handleFileSelect"
          />
        </label>
      </div>
    </div>

    <div v-if="selectedFile" class="upload-form card">
      <div class="file-info">
        <span class="file-name">{{ selectedFile.name }}</span>
        <span class="file-size">{{ formatSize(selectedFile.size) }}</span>
      </div>

      <div class="form-row">
        <label class="form-label">标题</label>
        <input v-model="title" type="text" placeholder="留空则自动提取" />
      </div>

      <div class="form-row">
        <label class="form-label">分类</label>
        <input v-model="category" type="text" placeholder="可选分类" />
      </div>

      <div class="form-row">
        <label class="form-label">知识库</label>
        <select v-model="uploadBank">
          <option v-for="bank in banksStore.banks" :key="bank.key" :value="bank.key">
            {{ bank.name }}
          </option>
        </select>
      </div>

      <div class="form-actions">
        <button class="primary" :disabled="uploading" @click="handleUpload">
          {{ uploading ? '上传中...' : '开始上传' }}
        </button>
        <button @click="resetForm">取消</button>
      </div>

      <div v-if="uploadProgress" class="progress-bar">
        <div class="progress-fill" :style="{ width: uploadProgress }"></div>
      </div>
    </div>

    <div v-if="uploadResult" class="upload-result card">
      <h3>上传结果</h3>
      <div class="result-row">
        <span class="result-label">文档ID</span>
        <span class="result-value">{{ uploadResult.doc_id }}</span>
      </div>
      <div class="result-row">
        <span class="result-label">标题</span>
        <span class="result-value">{{ uploadResult.title }}</span>
      </div>
      <div class="result-row">
        <span class="result-label">分块数</span>
        <span class="result-value">{{ uploadResult.chunks }}</span>
      </div>
      <div v-if="uploadResult.quality" class="result-row">
        <span class="result-label">质量评分</span>
        <span
          class="result-value quality-score"
          :class="{ low: uploadResult.quality.score < 80 }"
        >
          {{ uploadResult.quality.score }}%
        </span>
      </div>
    </div>

    <Toast v-if="toastMsg" :message="toastMsg" :type="toastType" @close="toastMsg = ''" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useBanksStore } from '@/stores/banks'
import api from '@/services/api'
import Toast from '@/components/Toast.vue'

const banksStore = useBanksStore()

const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const title = ref('')
const category = ref('')
const uploadBank = ref('general')
const uploading = ref(false)
const uploadProgress = ref('')
const isDragOver = ref(false)
interface UploadQuality {
  score: number
  issues?: string[]
  needs_confirm?: boolean
}

interface UploadResultData {
  doc_id?: string
  title?: string
  chunks?: number | string
  quality?: UploadQuality
  [key: string]: unknown
}

const uploadResult = ref<UploadResultData | null>(null)
const toastMsg = ref('')
const toastType = ref<'info' | 'success' | 'error' | 'warning'>('info')

onMounted(() => {
  banksStore.fetchBanks()
})

function handleDrop(e: DragEvent) {
  isDragOver.value = false
  const files = e.dataTransfer?.files
  if (files && files.length > 0) {
    selectedFile.value = files[0]
  }
}

function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files && input.files.length > 0) {
    selectedFile.value = input.files[0]
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

async function handleUpload() {
  if (!selectedFile.value) return
  uploading.value = true
  uploadProgress.value = '0%'
  uploadResult.value = null

  const formData = new FormData()
  formData.append('file', selectedFile.value)
  if (title.value) formData.append('title', title.value)
  if (category.value) formData.append('category', category.value)
  formData.append('bank', uploadBank.value)

  try {
    const { data } = await api.post('/upload', formData, {
      onUploadProgress: (e) => {
        if (e.total) {
          uploadProgress.value = `${Math.round((e.loaded / e.total) * 100)}%`
        }
      },
    })
    uploadResult.value = data
    toastMsg.value = '上传成功'
    toastType.value = 'success'
  } catch (e: unknown) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toastMsg.value = msg || '上传失败'
    toastType.value = 'error'
  } finally {
    uploading.value = false
    uploadProgress.value = ''
  }
}

function resetForm() {
  selectedFile.value = null
  title.value = ''
  category.value = ''
  uploadResult.value = null
  if (fileInput.value) fileInput.value.value = ''
}
</script>

<style scoped>
.upload-page {
  max-width: 700px;
}

.page-title {
  font-size: clamp(1.1rem, 2vw, 1.4rem);
  font-weight: 700;
  margin-bottom: 1.25rem;
  letter-spacing: -0.02em;
}

.drop-zone {
  padding: 2.5rem;
  text-align: center;
  border: 2px dashed var(--border);
  background: var(--bg);
  transition: border-color 0.15s, background 0.15s;
  margin-bottom: 1rem;
}

.drop-zone.dragover {
  border-color: var(--accent);
  background: var(--accent-light);
}

.drop-text {
  font-size: 0.9rem;
  color: var(--fg-muted);
  margin-bottom: 0.75rem;
}

.upload-btn-wrap {
  position: relative;
  display: inline-block;
}

.file-input-hidden {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}

.upload-form {
  margin-bottom: 1rem;
}

.file-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--border);
}

.file-name {
  font-weight: 600;
  font-size: 0.9rem;
}

.file-size {
  font-size: 0.75rem;
  color: var(--fg-muted);
}

.form-row {
  margin-bottom: 0.75rem;
}

.form-label {
  display: block;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--fg-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.3rem;
}

.form-row input,
.form-row select {
  width: 100%;
}

.form-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 1rem;
}

.progress-bar {
  height: 3px;
  background: var(--border);
  margin-top: 0.75rem;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.2s;
}

.upload-result h3 {
  font-size: 0.9rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
}

.result-row {
  display: flex;
  justify-content: space-between;
  padding: 0.35rem 0;
  font-size: 0.85rem;
  border-bottom: 1px solid var(--bg-alt);
}

.result-label {
  color: var(--fg-muted);
}

.quality-score.low {
  color: var(--warning);
  font-weight: 600;
}
</style>
