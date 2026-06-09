import api from './api'

export interface DocumentItem {
  id: string
  title: string
  category: string
  filename: string
  chunks: number
  size_chars: number
  created: string
  bank: string
  searchable: number
  coverage_pct: number
}

export interface DocumentListResponse {
  documents: DocumentItem[]
}

export interface DocumentDetail {
  id?: string
  doc_id: string
  title: string
  filename?: string
  bank?: string
  chunks?: number
  searchable?: number
  created?: string
  coverage_pct?: number
  text?: string
  content?: string
}

export async function listDocuments(bank = 'all'): Promise<DocumentListResponse> {
  const { data } = await api.get<DocumentListResponse>('/documents', {
    params: { bank },
  })
  return data
}

export async function getDocument(docId: string): Promise<DocumentDetail> {
  const { data } = await api.get<DocumentDetail>(`/documents/${encodeURIComponent(docId)}`)
  return data
}

export async function deleteDocument(docId: string): Promise<{ ok: boolean }> {
  const { data } = await api.delete<{ ok: boolean }>(`/documents/${encodeURIComponent(docId)}`)
  return data
}

export async function reparseDocument(
  docId: string,
): Promise<{ ok: boolean; [key: string]: unknown }> {
  const { data } = await api.post(`/documents/${encodeURIComponent(docId)}/reparse`)
  return data
}
