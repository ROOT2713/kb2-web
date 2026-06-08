import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  postQuery as apiPostQuery,
  webSearch as apiWebSearch,
  type Source,
} from '@/services/query'

export const useQueryStore = defineStore('query', () => {
  const answer = ref('')
  const sources = ref<Source[]>([])
  const loading = ref(false)
  const webSearching = ref(false)
  const error = ref('')
  const cacheHit = ref('')

  async function submitQuery(params: {
    q: string
    bank?: string
    history?: string
    rerank?: boolean
  }) {
    loading.value = true
    error.value = ''
    answer.value = ''
    sources.value = []
    cacheHit.value = ''
    try {
      const data = await apiPostQuery(params)
      answer.value = data.answer
      sources.value = data.sources || []
      cacheHit.value = data.cache_hit || ''
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '查询失败'
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
  }

  return {
    answer,
    sources,
    loading,
    webSearching,
    error,
    cacheHit,
    submitQuery,
    doWebSearch,
    clear,
  }
})
