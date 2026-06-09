import api from './api'

export interface BankItem {
  key: string
  name: string
  count: number
  searchable: number
  description: string
  hindsight?: string
}

export interface BanksResponse {
  banks: BankItem[]
}

export async function listBanks(): Promise<BanksResponse> {
  const { data } = await api.get<BanksResponse>('/banks')
  return data
}

export async function createBank(payload: {
  key: string
  label: string
  description?: string
  prompt?: string
}): Promise<{ ok: boolean; bank: string; hindsight_bank?: string }> {
  const formData = new FormData()
  formData.append('key', payload.key)
  formData.append('label', payload.label)
  if (payload.description) formData.append('description', payload.description)
  if (payload.prompt) formData.append('prompt', payload.prompt)
  const { data } = await api.post('/banks', formData)
  return data
}

export async function deleteBank(
  bankKey: string,
  confirm = false,
): Promise<{ ok: boolean }> {
  const { data } = await api.delete<{ ok: boolean }>(
    `/banks/${encodeURIComponent(bankKey)}`,
    { params: { confirm } },
  )
  return data
}
