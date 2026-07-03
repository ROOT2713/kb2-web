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

export interface ExtractResponse {
  topic: string
  total_documents: number
  total_concepts: number
  results: ExtractResult[]
}

export async function extractByTopic(
  topic: string,
  bank = 'all',
  min_confidence = 0.0,
  limit = 50,
): Promise<ExtractResponse> {
  const { data } = await api.post<ExtractResponse>('/articles/extract', {
    topic,
    bank,
    min_confidence,
    limit,
  })
  return data
}
