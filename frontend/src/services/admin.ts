import api from './api'

export interface AdminStats {
  total_nodes: number
  total_documents: number
  total_links: number
}

/**
 * 【C4】字段名对齐后端 `admin.py:admin_health` 的**实际返回**。
 *
 * 修复前这里是 `hindsight: string` —— 后端从未返回过该字段
 * （Hindsight 已退役，健康检查项改名为 `vector_store`），
 * 于是管理页那一行**永远空白**。后端另返 `mineru`（`get_mineru_stats()` 的 dict），
 * 此前完全没读。
 */
export interface AdminHealth {
  status: string
  version: string
  vector_store: string
  mineru: Record<string, unknown> | string
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

export interface CategoryTreeNode {
  name: string
  categories: CategoryItem[]
}

/** 把 `/admin/categories` 的树形结构拍平（返回裸数组） */
function flattenAdminTree(nodes: CategoryTreeNode[]): CategoryItem[] {
  const flat: CategoryItem[] = []
  for (const group of nodes || []) {
    for (const cat of group.categories || []) flat.push(cat)
  }
  return flat
}

/**
 * 把 `/banks/categories` 的 `super_categories` 结构拍平。
 *
 * 后端 `banks.py:list_categories` 返回：
 *   { "super_categories": [ { name, categories: [ {key,label,count} ] } ] }
 */
function flattenBanksTree(payload: unknown): CategoryItem[] {
  const raw = (payload as { super_categories?: unknown } | null)?.super_categories
  if (!Array.isArray(raw)) return []
  const flat: CategoryItem[] = []
  for (const group of raw as CategoryTreeNode[]) {
    for (const cat of group.categories || []) flat.push(cat)
  }
  return flat
}

/**
 * 【C6】取分类列表。
 *
 * 修复前直接打 `/admin/categories`（挂载在 `require_role("admin")` 下），
 * viewer 账号必拿 **403**；而调用方把异常静默吞掉，
 * 于是分类下拉框**静默变空**，用户只能选「未分类」。
 *
 * 现优先走 `/banks/categories`（`router.py:17` 只要求登录，viewer 可访问）。
 * ⚠️ 两个端点的响应结构不同，不能只换 URL：
 *   · `/admin/categories` → `CategoryTreeNode[]`          裸数组
 *   · `/banks/categories` → `{ super_categories: [...] }` 包一层
 * 只有前者失败时才回退（管理员场景仍可用）；两条都失败则**向上抛**
 * —— 不再被这一层吞掉，让调用方能区分「空」与「失败」。
 */
export async function getCategories(): Promise<CategoryItem[]> {
  try {
    const { data } = await api.get('/banks/categories')
    const flat = flattenBanksTree(data)
    if (flat.length) return flat
  } catch {
    /* 回退到 admin 端点 */
  }

  const { data } = await api.get<CategoryTreeNode[]>('/admin/categories')
  return flattenAdminTree(data)
}
