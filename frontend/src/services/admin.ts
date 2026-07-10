import api from './api'

export interface AdminStats {
  total_nodes: number
  total_documents: number
  total_links: number
}

export interface AdminHealth {
  status: string
  version: string
  hindsight: string
  db: string
}

export interface AuditDocument {
  doc_id: string
  title: string
  bank: string
  filename?: string
  chars: number
  score: number
  issues: string[]
  needs_refetch: boolean
  completeness?: unknown
}

export interface AuditResponse {
  total_docs: number
  avg_score: number
  low_quality_count: number
  documents: AuditDocument[]
}

export interface RagEvalResponse {
  total_cases: number
  evaluated: number
  avg_scores: Record<string, number>
  overall: number
  details: Array<Record<string, unknown>>
}

export async function getStats(): Promise<AdminStats> {
  const { data } = await api.get<AdminStats>('/admin/stats')
  return data
}

export async function getHealth(): Promise<AdminHealth> {
  const { data } = await api.get<AdminHealth>('/admin/health')
  return data
}

export async function getAudit(): Promise<AuditResponse> {
  const { data } = await api.get<AuditResponse>('/documents/audit')
  return data
}

export async function getRagEval(): Promise<RagEvalResponse> {
  const { data } = await api.get<RagEvalResponse>('/documents/rag-eval')
  return data
}

export interface AdminCosts {
  period: string
  call_count: number
  total_prompt_tokens: number
  total_completion_tokens: number
  total_tokens: number
  total_cost_yuan: number
  by_model: Array<{
    model: string
    calls: number
    prompt_tokens: number
    completion_tokens: number
    cost_yuan: number
  }>
}

export async function getCosts(period: string = 'today'): Promise<AdminCosts> {
  const { data } = await api.get<AdminCosts>('/admin/costs', { params: { period } })
  return data
}

export interface CategoryItem {
  key: string
  label: string
  isolated: boolean
}

export async function getCategories(): Promise<CategoryItem[]> {
  const { data } = await api.get<CategoryItem[]>('/admin/categories')
  return data
}
