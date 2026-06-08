import api from './api'

export interface Source {
  doc: string
  doc_id?: string
  score?: number
  chunk?: string
  text?: string
}

export interface QueryResponse {
  answer: string
  sources: Source[]
  cache_hit?: string
  quality_check?: unknown
}

export interface WebSearchResponse {
  answer: string
  web_searched: boolean
  fallback_mode: boolean
}

export async function postQuery(params: {
  q: string
  bank?: string
  history?: string
  rerank?: boolean
}): Promise<QueryResponse> {
  const formData = new FormData()
  formData.append('q', params.q)
  if (params.bank) formData.append('bank', params.bank)
  if (params.history) formData.append('history', params.history)
  if (params.rerank) formData.append('rerank', 'true')
  const { data } = await api.post<QueryResponse>('/query', formData)
  return data
}

export async function webSearch(params: {
  q: string
  bank?: string
  context?: string
}): Promise<WebSearchResponse> {
  const formData = new FormData()
  formData.append('q', params.q)
  if (params.bank) formData.append('bank', params.bank)
  if (params.context) formData.append('context', params.context)
  const { data } = await api.post<WebSearchResponse>('/query/web-search', formData)
  return data
}
