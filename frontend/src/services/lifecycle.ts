import api from './api'

export interface StaleSummary {
  active: number
  stale: number
  superseded: number
  total: number
  stale_by_reason: Record<string, number>
}

export interface StaleDoc {
  doc_id: string
  title: string
  bank: string
  stale_reason: string
  days_since: number
  verified_at?: string
  updated_at?: string
}

export interface LifecycleConfirmResponse {
  ok: boolean
  doc_id: string
  status: string
  last_confirmed: string
}

export async function getStaleSummary(): Promise<StaleSummary> {
  const { data } = await api.get<StaleSummary>('/admin/stale/summary')
  return data
}

export async function detectStale(maxDays: number = 90, dryRun: boolean = false): Promise<{
  total_checked: number
  stale_count: number
  stale_docs: StaleDoc[]
  max_days: number
  dry_run: boolean
}> {
  const { data } = await api.get('/admin/stale/detect', {
    params: { max_days: maxDays, dry_run: dryRun },
  })
  return data
}

export async function restoreDoc(docId: string): Promise<{ ok: boolean; doc_id: string }> {
  const { data } = await api.post<{ ok: boolean; doc_id: string }>(
    `/admin/stale/restore/${docId}`
  )
  return data
}

export async function confirmDoc(docId: string): Promise<LifecycleConfirmResponse> {
  const { data } = await api.post<LifecycleConfirmResponse>(
    `/admin/lifecycle/confirm/${docId}`
  )
  return data
}
