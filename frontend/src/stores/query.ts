import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  postQuery as apiPostQuery,
  webSearch as apiWebSearch,
  clearQueryCache as apiClearCache,
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

  async function submitQuery(params: {
    q: string
    bank?: string
    history?: string
    rerank?: boolean
    rerank_mode?: string
    multiHypothesis?: boolean
    nocache?: boolean
    categories?: string
  }) {
    loading.value = true
    error.value = ''
    answer.value = ''
    sources.value = []
    cacheHit.value = ''
    suggestions.value = null
    standardContents.value = []
    try {
      const data = await apiPostQuery(params)
      answer.value = data.answer
      sources.value = data.sources || []
      cacheHit.value = data.cache_hit || ''
      suggestions.value = data.suggestions || null
      standardContents.value = data.standard_contents || []
      if (data.answer) {
        addToHistory(params.q, params.bank || 'all', data.answer)
      }
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '查询失败'
      suggestions.value = null
      standardContents.value = []
    } finally {
      loading.value = false
    }
  }

  async function doWebSearch(params: {
    q: string
    bank?: string
    context?: string
  }) {
    webSearching.value = true
    error.value = ''
    suggestions.value = null
    try {
      const data = await apiWebSearch(params)
      answer.value = data.answer
      sources.value = []
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '联网搜索失败'
    } finally {
      webSearching.value = false
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
    submitQuery,
    doWebSearch,
    clear,
    clearCache,
    queryHistory,
    addToHistory,
    removeFromHistory,
    clearHistory,
  }
})
