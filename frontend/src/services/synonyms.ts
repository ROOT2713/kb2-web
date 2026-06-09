import api from './api'

export interface SynonymItem {
  id: number
  term: string
  expansion: string
  category: string
}

export interface SynonymPayload {
  term: string
  expansion: string
  category?: string
}

function toFormData(payload: SynonymPayload): FormData {
  const fd = new FormData()
  fd.append('term', payload.term)
  fd.append('expansion', payload.expansion)
  if (payload.category) fd.append('category', payload.category)
  return fd
}

export async function listSynonyms(): Promise<SynonymItem[]> {
  const { data } = await api.get<SynonymItem[]>('/synonyms')
  return data
}

export async function addSynonym(
  payload: SynonymPayload,
): Promise<{ ok: boolean; message?: string }> {
  const { data } = await api.post<{ ok: boolean; message?: string }>(
    '/synonyms',
    toFormData(payload),
  )
  return data
}

export async function updateSynonym(
  id: number,
  payload: SynonymPayload,
): Promise<{ ok: boolean; message?: string }> {
  const { data } = await api.put<{ ok: boolean; message?: string }>(
    `/synonyms/${id}`,
    toFormData(payload),
  )
  return data
}

export async function deleteSynonym(
  id: number,
): Promise<{ ok: boolean; message?: string }> {
  const { data } = await api.delete<{ ok: boolean; message?: string }>(`/synonyms/${id}`)
  return data
}
