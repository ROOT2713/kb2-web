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
  id: string
  title: string
  content?: string
}

export async function listDocuments(bank = 'all'): Promise<DocumentListResponse> {
  const { data } = await api.get<DocumentListResponse>('/documents', {
    params: { bank },
  })
  return data
}

export async function getDocument(docId: string): Promise<DocumentDetail> {
  const { data } = await api.get<DocumentDetail>(`/documents/${docId}`)
  return data
}

export async function deleteDocument(docId: string): Promise<{ ok: boolean }> {
  const { data } = await api.delete<{ ok: boolean }>(`/documents/${docId}`)
  return data
}

export async function reparseDocument(
  docId: string,
): Promise<{ ok: boolean; [key: string]: unknown }> {
  const formData = new FormData()
  formData.append('doc_id', docId)
  const { data } = await api.post('/documents/reparse', formData)
  return data
}
