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
        <p class="drop-text">拖拽文件/文件夹到此处，或</p>
        <div class="upload-btn-row">
          <label class="upload-btn-wrap">
            <button type="button" class="primary">选择文件</button>
            <input
              ref="fileInput"
              type="file"
              multiple
              class="file-input-hidden"
              accept=".pdf,.docx,.doc,.xlsx,.xls,.txt,.md,.csv"
              @change="handleFileSelect"
            />
          </label>
          <label class="upload-btn-wrap">
            <button type="button" class="secondary">选择文件夹</button>
            <input
              ref="folderInput"
              type="file"
              multiple
              webkitdirectory
              directory
              class="file-input-hidden"
              @change="handleFolderSelect"
            />
          </label>
        </div>
        <p v-if="scanInfo" class="scan-info">{{ scanInfo }}</p>
      </div>
    </div>

    <div v-if="selectedFiles.length > 0" class="upload-form card">
      <div class="file-info">
        <div class="file-list">
          <span
            v-for="(f, i) in displayedFiles"
            :key="i"
            class="file-tag"
            :title="webkitRelativePath(f)"
          >
            {{ webkitRelativePath(f) }}
            <span class="file-size-inline">{{ formatSize(f.size) }}</span>
          </span>
          <span v-if="selectedFiles.length > 10" class="file-more">
            …共 {{ selectedFiles.length }} 个文件
          </span>
        </div>
        <span class="file-total-size">总大小 {{ formatSize(totalSize) }}</span>
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
      <p v-if="uploadPhase" class="upload-phase">
        {{ uploadPhase }}
        <span v-if="currentFileName" class="upload-file-name">{{ currentFileName }}</span>
      </p>
    </div>

    <!-- 单文件上传结果 -->
    <div v-if="uploadResult && !isBatchResult" class="upload-result card">
      <h3>上传结果</h3>
      <div class="result-row">
        <span class="result-label">文档ID</span>
        <span class="result-value">{{ (uploadResult as UploadResultData).doc_id }}</span>
      </div>
      <div class="result-row">
        <span class="result-label">标题</span>
        <span class="result-value">{{ (uploadResult as UploadResultData).title }}</span>
      </div>
      <div class="result-row">
        <span class="result-label">分块数</span>
        <span class="result-value">{{ (uploadResult as UploadResultData).chunks }}</span>
      </div>
      <div v-if="(uploadResult as UploadResultData).quality" class="result-row">
        <span class="result-label">质量评分</span>
        <span
          class="result-value quality-score"
          :class="{ low: (uploadResult as UploadResultData).quality!.score < 80 }"
        >
          {{ (uploadResult as UploadResultData).quality!.score }}%
        </span>
      </div>
    </div>

    <!-- 批量上传结果 -->
    <div v-if="uploadResult && isBatchResult" class="upload-result card">
      <h3>批量上传结果</h3>
      <div class="batch-summary">
        <span class="batch-stat">总计 {{ (uploadResult as BatchUploadResultData).total }} 个文件</span>
        <span class="batch-stat success">成功 {{ (uploadResult as BatchUploadResultData).success }}</span>
        <span v-if="(uploadResult as BatchUploadResultData).failed > 0" class="batch-stat failed">
          失败 {{ (uploadResult as BatchUploadResultData).failed }}
        </span>
      </div>
      <div class="batch-results-list">
        <div
          v-for="(r, i) in (uploadResult as BatchUploadResultData).results"
          :key="i"
          class="batch-result-item"
          :class="{ 'result-ok': r.ok, 'result-fail': !r.ok }"
        >
          <span class="batch-filename">{{ r.filename }}</span>
          <span v-if="r.ok" class="batch-doc-id">{{ r.doc_id?.slice(0, 8) }}</span>
          <span v-else class="batch-error">{{ r.detail }}</span>
        </div>
      </div>
    </div>

    <Toast v-if="toastMsg" :message="toastMsg" :type="toastType" @close="toastMsg = ''" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useBanksStore } from '@/stores/banks'
import api from '@/services/api'
import Toast from '@/components/Toast.vue'

const banksStore = useBanksStore()

const fileInput = ref<HTMLInputElement | null>(null)
const folderInput = ref<HTMLInputElement | null>(null)
const selectedFiles = ref<File[]>([])
const title = ref('')
const category = ref('')
const uploadBank = ref('general')
const uploading = ref(false)
const uploadProgress = ref('')
const isDragOver = ref(false)
const scanInfo = ref('')
const uploadPhase = ref('')
const batchIndex = ref(0)
const totalBatches = ref(0)
const currentFileName = ref('')

interface UploadQuality {
  score: number
  issues?: string[]
  needs_confirm?: boolean
}

interface UploadResultData {
  ok?: boolean
  detail?: string
  doc_id?: string
  title?: string
  chunks?: number | string
  quality?: UploadQuality
  [key: string]: unknown
}

interface BatchResultItem {
  filename: string
  ok: boolean
  doc_id?: string
  title?: string
  chunks?: number
  quality?: UploadQuality
  detail?: string
  status_code?: number
}

interface BatchUploadResultData {
  ok: boolean
  total: number
  success: number
  failed: number
  results: BatchResultItem[]
}

const uploadResult = ref<UploadResultData | BatchUploadResultData | null>(null)
const toastMsg = ref('')
const toastType = ref<'info' | 'success' | 'error' | 'warning'>('info')

const isBatchResult = computed(() => {
  const r = uploadResult.value as BatchUploadResultData | null
  return r && Array.isArray(r.results)
})

const displayedFiles = computed(() => selectedFiles.value.slice(0, 10))

const totalSize = computed(() =>
  selectedFiles.value.reduce((sum, f) => sum + f.size, 0)
)

onMounted(() => {
  banksStore.fetchBanks()
})

function handleDrop(e: DragEvent) {
  isDragOver.value = false
  const files = e.dataTransfer?.files
  if (files && files.length > 0) {
    const raw = Array.from(files)
    const filtered = raw.filter(f => {
      const ext = '.' + (f.name.split('.').pop() || '').toLowerCase()
      return SUPPORTED_EXTS.has(ext) && !isHiddenOrMetadata(f)
    })
    scanInfo.value = raw.length > filtered.length
      ? `已扫描 ${raw.length} 个文件，过滤后 ${filtered.length} 个支持的文件`
      : ''
    selectedFiles.value = filtered
  }
}

function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files && input.files.length > 0) {
    selectedFiles.value = Array.from(input.files)
    scanInfo.value = ''
  }
}

const SUPPORTED_EXTS = new Set(['.pdf','.docx','.doc','.xlsx','.xls','.txt','.md','.csv'])

function webkitRelativePath(file: File): string {
  return (file as any).webkitRelativePath || file.name
}

function isHiddenOrMetadata(file: File): boolean {
  const name = file.name
  if (name.startsWith('.') || name.startsWith('~')) return true
  const hidden = ['.DS_Store', 'Thumbs.db', 'desktop.ini', '~$']
  return hidden.some(h => name.startsWith(h) || name.toLowerCase() === h.toLowerCase())
}

function handleFolderSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files || input.files.length === 0) return

  const raw = Array.from(input.files)
  const filtered = raw.filter(f => {
    const ext = '.' + (f.name.split('.').pop() || '').toLowerCase()
    return SUPPORTED_EXTS.has(ext) && !isHiddenOrMetadata(f)
  })

  scanInfo.value = `已扫描 ${raw.length} 个文件，过滤后 ${filtered.length} 个支持的文件`
  selectedFiles.value = filtered

  // reset input so re-selecting same folder triggers change
  input.value = ''
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ── 计算文件 SHA-256（与后端 hashlib.sha256 一致，用于 precheck 精确匹配） ──
async function sha256OfFile(file: File): Promise<string> {
  const buf = await file.arrayBuffer()
  const digest = await crypto.subtle.digest('SHA-256', buf)
  return Array.from(new Uint8Array(digest))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('')
}

interface PrecheckItem {
  filename: string
  title: string
  status: 'new' | 'dup_hash' | 'dup_title' | 'dup_standard'
  existing_doc_id?: string
  existing_title?: string
  reason?: string
}

async function runPrecheck(files: File[], bank: string): Promise<PrecheckItem[]> {
  // 1. 本地计算 sha1 — 分块（每块 5 个），块间让出主线程避免 UI 冻结
  uploadPhase.value = `计算文件指纹 0/${files.length}`
  const items: { filename: string; sha1: string; title: string; bank: string }[] = []
  const CHUNK_SIZE = 5
  for (let start = 0; start < files.length; start += CHUNK_SIZE) {
    const chunk = files.slice(start, start + CHUNK_SIZE)
    for (let j = 0; j < chunk.length; j++) {
      const f = chunk[j]
      const idx = start + j
      uploadPhase.value = `计算文件指纹 ${idx + 1}/${files.length}`
      let sha1 = ''
      try { sha1 = await sha256OfFile(f) } catch (e) { console.warn('[sha1]', f.name, e) }
      items.push({
        filename: f.name,
        sha1,
        title: title.value || f.name.replace(/\.[^.]+$/, ''),
        bank,
      })
      // 每文件刷新进度（不只是每5个）
      uploadPhase.value = `计算文件指纹 ${idx + 1}/${files.length}`
    }
    // 让出主线程，避免大文件 SHA1 阻塞 UI
    await new Promise(r => setTimeout(r, 0))
  }

  // 2. 调 precheck endpoint（30s 超时，超时不阻塞上传）
  uploadPhase.value = `预检 ${files.length} 个文件...`
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), 30000)
  try {
    const { data } = await api.post('/upload/precheck', { items }, {
      signal: controller.signal,
    })
    return data.results as PrecheckItem[]
  } finally {
    clearTimeout(timeoutId)
  }
}

async function handleUpload() {
  if (selectedFiles.value.length === 0) return
  uploading.value = true
  uploadProgress.value = '0%'
  uploadResult.value = null

  // ── 预检：识别已存在的文档 ──
  let originalFiles = selectedFiles.value.slice()
  let skippedDup: PrecheckItem[] = []
  try {
    const precheck = await runPrecheck(originalFiles, uploadBank.value)
    const fileByName = new Map(originalFiles.map(f => [f.name, f]))
    const keep: File[] = []
    for (const p of precheck) {
      if (p.status === 'new') {
        const f = fileByName.get(p.filename)
        if (f) keep.push(f)
      } else {
        skippedDup.push(p)
      }
    }
    if (skippedDup.length > 0) {
      scanInfo.value = `预检发现 ${skippedDup.length} 个已存在文档已跳过（${precheck.filter(p=>p.status==='dup_hash').length}重复内容/${precheck.filter(p=>p.status==='dup_standard').length}同标准号/${precheck.filter(p=>p.status==='dup_title').length}同标题）`
    }
    if (keep.length === 0) {
      toastMsg.value = `全部 ${originalFiles.length} 个文件均已存在，无需上传`
      toastType.value = 'warning'
      uploading.value = false
      uploadProgress.value = ''
      uploadPhase.value = ''
      // 显示跳过详情
      uploadResult.value = {
        ok: true,
        total: originalFiles.length,
        success: 0,
        failed: 0,
        results: skippedDup.map(p => ({
          filename: p.filename,
          ok: false,
          detail: p.reason || '已存在',
        })),
      }
      return
    }
    // 用过滤后的列表继续
    originalFiles = keep
  } catch (e: unknown) {
    console.warn('precheck failed, falling back to direct upload:', e)
    // 区分超时/网络错误/其他异常，给出具体文案
    const err = e as Error
    const isTimeout = err?.name === 'AbortError' || err?.name === 'CanceledError'
    const isNetwork = err instanceof TypeError && (err.message || '').includes('NetworkError')
    if (isTimeout) {
      uploadPhase.value = `预检超时（30s），跳过预检直接上传 ${originalFiles.length} 个文件...`
      scanInfo.value = '预检未响应，重复文件将由服务端检测'
    } else if (isNetwork) {
      uploadPhase.value = `预检网络异常，跳过预检直接上传 ${originalFiles.length} 个文件...`
      scanInfo.value = '网络不稳定，请检查连接'
    } else {
      uploadPhase.value = `预检异常，直接上传 ${originalFiles.length} 个文件...`
      scanInfo.value = `预检失败: ${err?.message?.slice(0, 80) || '未知错误'}`
    }
  }

  const allFiles = originalFiles
  const isBatch = allFiles.length > 1
  uploadPhase.value = isBatch
    ? `准备上传 ${allFiles.length} 个文件，分 ${Math.ceil(allFiles.length / 20)} 批...`
    : `开始上传...`

  // ── 大量文件自动分批：每批 20 个，避免单请求超时 ──
  const BATCH_SIZE = 20
  const batches: File[][] = []
  if (isBatch) {
    for (let i = 0; i < allFiles.length; i += BATCH_SIZE) {
      batches.push(allFiles.slice(i, i + BATCH_SIZE))
    }
  } else {
    batches.push(allFiles)
  }
  totalBatches.value = batches.length

  // 累积结果
  const aggregated: BatchUploadResultData = {
    ok: true,
    total: allFiles.length,
    success: 0,
    failed: 0,
    results: [],
  }

  for (let bi = 0; bi < batches.length; bi++) {
    try {
      batchIndex.value = bi + 1
      const batch = batches[bi]
      const batchIsMulti = batch.length > 1 || batches.length > 1
      const endpoint = batchIsMulti ? '/upload/batch' : '/upload'

      const formData = new FormData()
      if (batchIsMulti) {
        for (const f of batch) formData.append('files', f)
        if (title.value) formData.append('title_prefix', title.value)
      } else {
        formData.append('file', batch[0])
        if (title.value) formData.append('title', title.value)
      }
      if (category.value) formData.append('category', category.value)
      formData.append('bank', uploadBank.value)

      if (batches.length > 1) {
        currentFileName.value = ''
        uploadPhase.value = `批次 ${bi + 1}/${batches.length}（${batch.length} 个文件）`
      } else if (batch.length === 1) {
        currentFileName.value = batch[0].name
        uploadPhase.value = `上传中: ${batch[0].name}`
      }

      const { data } = await api.post(endpoint, formData, {
        onUploadProgress: (e) => {
          if (e.total) {
            const batchPct = (e.loaded / e.total) * 100
            const overallPct = ((bi + batchPct / 100) / batches.length) * 100
            uploadProgress.value = `${Math.round(overallPct)}%`
          }
        },
      })

      // 累积到 aggregated
      if (batchIsMulti) {
        const b = data as BatchUploadResultData
        aggregated.success += b.success || 0
        aggregated.failed += b.failed || 0
        aggregated.results.push(...(b.results || []))
      } else {
        const single = data as UploadResultData
        if (single.ok) {
          aggregated.success += 1
          aggregated.results.push({
            filename: batch[0].name,
            ok: true,
            doc_id: single.doc_id,
            title: single.title,
            chunks: typeof single.chunks === 'number' ? single.chunks : undefined,
            quality: single.quality,
          })
        } else {
          aggregated.failed += 1
          aggregated.results.push({
            filename: batch[0].name,
            ok: false,
            detail: single.detail || '上传失败',
          })
        }
      }
    } catch (e: unknown) {
      // 单批失败不阻断剩余批次，记录每个文件的名称
      const failedFiles = batches[bi] || []
      aggregated.failed += failedFiles.length
      for (const f of failedFiles) {
        aggregated.results.push({
          filename: f.name,
          ok: false,
          detail: '批次上传失败，已跳过',
        })
      }
      console.warn(`[upload] batch ${bi + 1}/${batches.length} (${failedFiles.length} files) failed:`, e)
    }
  }

  aggregated.ok = aggregated.success > 0
  uploadResult.value = aggregated
  uploadPhase.value = ''

  if (aggregated.ok) {
    toastMsg.value = `批量上传完成：成功 ${aggregated.success} / 失败 ${aggregated.failed}`
    toastType.value = aggregated.failed > 0 ? 'warning' : 'success'
  } else {
    toastMsg.value = '全部失败，详见结果列表'
    toastType.value = 'error'
  }
  uploading.value = false
  uploadProgress.value = ''
  uploadPhase.value = ''
  // 上传完成后清空文件列表，允许用户选择下一批
  selectedFiles.value = []
  if (fileInput.value) fileInput.value.value = ''
  if (folderInput.value) folderInput.value.value = ''
}

function resetForm() {
  selectedFiles.value = []
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

.upload-btn-row {
  display: inline-flex;
  gap: 0.6rem;
  flex-wrap: wrap;
  justify-content: center;
}

.scan-info {
  margin-top: 0.75rem;
  font-size: 0.82rem;
  color: var(--fg-muted);
}

button.secondary {
  background: var(--bg-elevated, #f3f3f3);
  color: var(--fg, #333);
  border: 1px solid var(--border, #d0d0d0);
  padding: 0.5rem 1rem;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
}

button.secondary:hover {
  background: var(--bg-hover, #e8e8e8);
}

.upload-phase {
  margin-top: 0.4rem;
  font-size: 0.82rem;
  color: var(--fg-muted);
  font-variant-numeric: tabular-nums;
}
.upload-file-name {
  display: block;
  font-size: 0.75rem;
  color: var(--fg);
  margin-top: 0.2rem;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--border);
}

.file-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.file-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  background: var(--bg-alt);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0.2rem 0.5rem;
  font-size: 0.8rem;
  font-weight: 500;
}

.file-size-inline {
  font-size: 0.7rem;
  color: var(--fg-muted);
}

.file-more {
  font-size: 0.75rem;
  color: var(--fg-muted);
  align-self: center;
}

.file-total-size {
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

/* ── 批量上传结果样式 ── */
.batch-summary {
  display: flex;
  gap: 1rem;
  margin-bottom: 0.75rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--bg-alt);
}

.batch-stat {
  font-size: 0.85rem;
  font-weight: 600;
}

.batch-stat.success {
  color: var(--success, #22c55e);
}

.batch-stat.failed {
  color: var(--warning);
}

.batch-results-list {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  max-height: 300px;
  overflow-y: auto;
}

.batch-result-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.35rem 0.5rem;
  border-radius: 4px;
  font-size: 0.8rem;
}

.batch-result-item.result-ok {
  background: rgba(34, 197, 94, 0.08);
}

.batch-result-item.result-fail {
  background: rgba(239, 68, 68, 0.08);
}

.batch-filename {
  font-weight: 500;
  max-width: 60%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.batch-doc-id {
  font-family: monospace;
  font-size: 0.7rem;
  color: var(--fg-muted);
}

.batch-error {
  font-size: 0.7rem;
  color: var(--warning);
  max-width: 55%;
  text-align: right;
}
</style>
