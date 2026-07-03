import api from './api'

export interface ExtractResult {
  doc_id: string
  title: string
  domain: string
  confidence: number
  concept_count: number
  concepts: Array<{
    concept_id: string
    title: string
    summary: string
    confidence: number
    access_count: number
  }>
  total_chars: number
}

export interface Pagination {
  page: number
  page_size: number
  total: number
  total_pages: number
}

export interface ExtractResponse {
  topic: string
  total_documents: number
  total_concepts: number
  results: ExtractResult[]
  summary: string
  pagination: Pagination
}

export async function extractByTopic(
  topic: string,
  bank = 'all',
  min_confidence = 0.0,
  limit = 50,
  page = 1,
  page_size = 20,
  summarize = false,
): Promise<ExtractResponse> {
  const { data } = await api.post<ExtractResponse>('/articles/extract', {
    topic,
    bank,
    min_confidence,
    limit,
    page,
    page_size,
    summarize,
  })
  return data
}
