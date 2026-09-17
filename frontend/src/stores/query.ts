import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  postQuery as apiPostQuery,
  webSearch as apiWebSearch,
  clearQueryCache as apiClearCache,
  type PostQueryParams,
  type Source,
  type QuerySuggestions,
} from '@/services/query'

interface StandardContent {
  title: string
  doc_id: string
  total_chars: number
  sections_count: number
  preview: string
}

const HISTORY_KEY = 'kb2_query_history'
/**
 * 【C1】多轮会话 ID 的存储键。
 *
 * 用 sessionStorage 而非 localStorage：会话天然按「一次对话/一个标签页」划分，
 * 关闭标签页即失效。放 localStorage 会导致一周后回来提问仍沿用一周前那批文档
 * 白名单 —— 比「没有会话」更糟。
 */
const SESSION_KEY = 'kb2_query_session'
const MAX_HISTORY = 20

interface HistoryItem {
  q: string
  bank: string
  timestamp: number
  answer_preview: string
}

export const useQueryStore = defineStore('query', () => {
  const answer = ref('')
  const sources = ref<Source[]>([])
  const loading = ref(false)
  const webSearching = ref(false)
  const clearingCache = ref(false)
  const error = ref('')
  const cacheHit = ref('')
  const suggestions = ref<QuerySuggestions | null>(null)
  const standardContents = ref<StandardContent[]>([])

  const queryHistory = ref<HistoryItem[]>([])

  /** 【C1】当前多轮会话 ID（初值从 sessionStorage 恢复） */
  const sessionId = ref<string>(readSession())

  /** 【C5】进行中的请求控制器 —— abort 时真正中断 HTTP 连接 */
  let controller: AbortController | null = null

  function readSession(): string {
    try {
      return sessionStorage.getItem(SESSION_KEY) || ''
    } catch {
      return ''
    }
  }

  function writeSession(id: string) {
    sessionId.value = id
    try {
      if (id) sessionStorage.setItem(SESSION_KEY, id)
      else sessionStorage.removeItem(SESSION_KEY)
    } catch {
      /* 隐私模式下 sessionStorage 可能不可用，静默降级 */
    }
  }

  /** 【C5】主动取消不是错误 —— axios 取消后 name 为 CanceledError/AbortError */
  function isAbortError(e: unknown): boolean {
    const name = (e as { name?: string } | null | undefined)?.name
    return name === 'CanceledError' || name === 'AbortError'
  }

  /** 【C5】中断进行中的查询。controller.abort() 让 axios 立刻断连。 */
  function abortQuery() {
    if (controller) {
      controller.abort()
      controller = null
    }
    loading.value = false
    webSearching.value = false
  }

  // Load from localStorage on init
  function loadHistory() {
    try {
      const raw = localStorage.getItem(HISTORY_KEY)
      if (raw) queryHistory.value = JSON.parse(raw)
    } catch { /* ignore */ }
  }
  loadHistory()

  function saveHistory() {
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(queryHistory.value))
    } catch { /* quota exceeded */ }
  }

  function addToHistory(q: string, bank: string, answer: string) {
    queryHistory.value = queryHistory.value.filter(h => h.q !== q)
    queryHistory.value.unshift({
      q,
      bank: bank || 'all',
      timestamp: Date.now(),
      answer_preview: answer ? answer.slice(0, 120) : '',
    })
    if (queryHistory.value.length > MAX_HISTORY) {
      queryHistory.value = queryHistory.value.slice(0, MAX_HISTORY)
    }
    saveHistory()
  }

  function removeFromHistory(index: number) {
    queryHistory.value.splice(index, 1)
    saveHistory()
  }

  function clearHistory() {
    queryHistory.value = []
    localStorage.removeItem(HISTORY_KEY)
  }

  async function submitQuery(params: PostQueryParams) {
    // 【C5】上一个请求还在跑 → 先取消，避免响应乱序覆盖
    abortQuery()
    controller = new AbortController()
    const signal = controller.signal

    loading.value = true
    error.value = ''
    answer.value = ''
    sources.value = []
    cacheHit.value = ''
    suggestions.value = null
    standardContents.value = []
    try {
      // 【C1】带上 session_id；调用方显式传了就用调用方的
      const payload: PostQueryParams = {
        ...params,
        session_id: params.session_id || sessionId.value,
      }
      const data = await apiPostQuery(payload, signal)
      // 【C1】把后端返回（可能新建）的 session_id 写回，供下一轮复用
      if (data.session_id) writeSession(data.session_id)
      answer.value = data.answer
      sources.value = data.sources || []
      cacheHit.value = data.cache_hit || ''
      suggestions.value = data.suggestions || null
      standardContents.value = data.standard_contents || []
      if (data.answer) {
        addToHistory(params.q, params.bank || 'all', data.answer)
      }
    } catch (e: unknown) {
      // 【C5】主动取消不是错误，不弹红色提示
      if (isAbortError(e)) return
      error.value = e instanceof Error ? e.message : '查询失败'
      suggestions.value = null
      standardContents.value = []
    } finally {
      // 【C5】只有「当前这一次」请求才允许改 loading ——
      // 防止被后来者取消的请求在 finally 里把 loading 又置回 false
      if (controller?.signal === signal) {
        loading.value = false
        controller = null
      }
    }
  }

  async function doWebSearch(params: { q: string; bank?: string; context?: string }) {
    abortQuery()
    controller = new AbortController()
    const signal = controller.signal

    webSearching.value = true
    error.value = ''
    suggestions.value = null
    try {
      const data = await apiWebSearch(params, signal)
      answer.value = data.answer
      sources.value = []
    } catch (e: unknown) {
      if (isAbortError(e)) return
      error.value = e instanceof Error ? e.message : '联网搜索失败'
    } finally {
      if (controller?.signal === signal) {
        webSearching.value = false
        controller = null
      }
    }
  }

  function clear() {
    answer.value = ''
    sources.value = []
    error.value = ''
    cacheHit.value = ''
    suggestions.value = null
    standardContents.value = []
  }

  /** 【C1】重置多轮会话 —— 用户点「新会话」时调用，下轮不再沿用旧文档白名单 */
  function resetSession() {
    writeSession('')
  }

  async function clearCache() {
    clearingCache.value = true
    try {
      const result = await apiClearCache()
      error.value = ''
      return result
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '清除缓存失败'
      return null
    } finally {
      clearingCache.value = false
    }
  }

  return {
    answer,
    sources,
    loading,
    webSearching,
    clearingCache,
    error,
    cacheHit,
    suggestions,
    standardContents,
    sessionId,
    submitQuery,
    doWebSearch,
    abortQuery,
    clear,
    clearCache,
    resetSession,
    queryHistory,
    addToHistory,
    removeFromHistory,
    clearHistory,
  }
})
