import api from './api'

export interface Source {
  doc: string
  doc_id?: string
  score?: number
  chunk?: string
  text?: string
  fee_tier?: string
  keyword_matches?: number
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
  /** 【C1】多轮会话 ID —— 必须在后续请求中原样回传，否则后端每轮新建 session */
  session_id?: string
}

export interface WebSearchResponse {
  answer: string
  web_searched: boolean
  fallback_mode: boolean
}

/**
 * 【C1】查询参数的唯一具名类型。
 *
 * 修复前该类型内联在 postQuery 的形参里，store 侧又抄了一份内联副本
 * —— 两份会漂移（交付包自身就因此产生 TS2339：内联副本少了 session_id）。
 * 这里收敛成唯一来源，store 直接引用。
 */
export interface PostQueryParams {
  q: string
  bank?: string
  history?: string
  rerank?: boolean
  rerank_mode?: string
  multiHypothesis?: boolean
  nocache?: boolean
  categories?: string
  /** 【C1】上一轮返回的 session_id，用于多轮域锁定 */
  session_id?: string
}

export async function postQuery(
  params: PostQueryParams,
  signal?: AbortSignal,
): Promise<QueryResponse> {
  const formData = new FormData()
  formData.append('q', params.q)
  if (params.bank) formData.append('bank', params.bank)
  if (params.history) formData.append('history', params.history)
  if (params.rerank) formData.append('rerank', 'true')
  if (params.rerank_mode) formData.append('rerank_mode', params.rerank_mode)
  if (params.multiHypothesis) formData.append('multi_hypothesis', 'true')
  if (params.nocache) formData.append('nocache', 'true')
  if (params.categories) formData.append('categories', params.categories)
  // 【C1】回传会话 ID —— 缺失时后端每轮都新建 session，多轮文档白名单复用失效
  if (params.session_id) formData.append('session_id', params.session_id)
  // 【C5】透传 signal —— 否则「取消」只清本地 UI，后端仍跑满检索 + LLM 链路
  const { data } = await api.post<QueryResponse>('/query', formData, { signal })
  return data
}

/**
 * 【C7】「排除日常/资讯」的 UI 哨兵值。
 *
 * 修复前 QueryView 的 `<option>` 用 `''` 同时表示「排除日常/资讯」与
 * 「不传该字段」，而 DocumentsView 的 `''` 表示「未分类」
 * —— 同一个空串在两个页面承载**相反**语义，用户把分类改回空时被后端判空 → 400。
 * 现在：哨兵值只做 UI 标识，`''` 只保留「不传该字段」一层含义。
 */
export const EXCLUDE_DAILY_CATEGORIES = '__exclude_daily__'

/** 【C7】把 UI 选择值翻译成后端 `categories` 语义（哨兵 → 空串 = 不传该字段） */
export function toCategoriesParam(value: string): string {
  return value === EXCLUDE_DAILY_CATEGORIES ? '' : value
}

export async function webSearch(
  params: { q: string; bank?: string; context?: string },
  signal?: AbortSignal,
): Promise<WebSearchResponse> {
  const formData = new FormData()
  formData.append('q', params.q)
  if (params.bank) formData.append('bank', params.bank)
  if (params.context) formData.append('context', params.context)
  const { data } = await api.post<WebSearchResponse>('/query/web-search', formData, { signal })
  return data
}


export async function clearQueryCache(): Promise<{status: string, cleared: number, message: string}> {
  const { data } = await api.post('/query/cache-clear')
  return data
}
