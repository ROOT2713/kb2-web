import api from './api'

export interface Source {
  doc: string
  doc_id?: string
  score?: number
  chunk?: string
  text?: string
}

export interface TermHint {
  user_term: string
  kb_term: string
  doc?: string
}

export interface RelatedDoc {
  doc_id?: string
  title: string
}

export interface StandardHint {
  doc_id?: string
  title: string
  reason?: string
  recommended_query: string
}

export interface QuerySuggestions {
  refined_query?: string
  term_hints?: TermHint[]
  related_docs?: RelatedDoc[]
  standard_hints?: StandardHint[]
  follow_up_questions?: string[]
}

export interface StandardContent {
  title: string
  doc_id: string
  total_chars: number
  sections_count: number
  preview: string
}

export interface QueryResponse {
  answer: string
  sources: Source[]
  cache_hit?: string
  quality_check?: unknown
  suggestions?: QuerySuggestions | null
  standard_contents?: StandardContent[]
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
  rerank_mode?: string
  multiHypothesis?: boolean
  nocache?: boolean
}): Promise<QueryResponse> {
  const formData = new FormData()
  formData.append('q', params.q)
  if (params.bank) formData.append('bank', params.bank)
  if (params.history) formData.append('history', params.history)
  if (params.rerank) formData.append('rerank', 'true')
  if (params.rerank_mode) formData.append('rerank_mode', params.rerank_mode)
  if (params.multiHypothesis) formData.append('multi_hypothesis', 'true')
  if (params.nocache) formData.append('nocache', 'true')
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


export async function clearQueryCache(): Promise<{status: string, cleared: number, message: string}> {
  const { data } = await api.post('/query/cache-clear')
  return data
}
