/**
 * 接线级测试（批次 E）—— 证明「utils 被真的用上了」，而不只是「utils 自己是对的」。
 *
 * 为什么单独写这一层：`utils/error.spec.ts` 只能证明 getErrorMessage 函数正确，
 * 若某处 store 仍写着 `e instanceof Error ? e.message : '...'`，那些单测**依然全绿**
 * 而用户依旧只看到 "Request failed with status code 400"。本文件断言的是
 * **端到端的可观察结果**：后端的中文 detail 必须出现在 `store.error` 上。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const postQuery = vi.fn()
const listBanks = vi.fn()

vi.mock('@/services/query', () => ({
  postQuery: (...a: unknown[]) => postQuery(...a),
  webSearch: vi.fn(),
  clearQueryCache: vi.fn(),
}))
vi.mock('@/services/banks', () => ({
  listBanks: (...a: unknown[]) => listBanks(...a),
  createBank: vi.fn(),
  deleteBank: vi.fn(),
}))

import { useQueryStore } from '@/stores/query'
import { useBanksStore } from '@/stores/banks'

/** 后端风格的中文业务错误（FastAPI HTTPException(detail="中文")） */
function backendError(detail: string, status = 400) {
  return { response: { status, data: { detail } }, message: `Request failed with status code ${status}` }
}

describe('stores/query：错误消息必须透出后端中文 detail', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    postQuery.mockReset()
  })

  it('★ 查询失败时 error 是后端中文提示，而不是 "Request failed with status code 400"', async () => {
    postQuery.mockRejectedValueOnce(backendError('分类不能为空'))
    const store = useQueryStore()
    await store.submitQuery({ q: '测试' })

    expect(store.error).toBe('分类不能为空')
    expect(store.error).not.toContain('Request failed')
    expect(store.error).not.toContain('status code')
  })

  it('★ 用户主动取消（C5）不得弹错误提示，也不得残留 loading', async () => {
    postQuery.mockRejectedValueOnce({ name: 'CanceledError', code: 'ERR_CANCELED', message: 'canceled' })
    const store = useQueryStore()
    await store.submitQuery({ q: '测试' })
    expect(store.error).toBe('')
    expect(store.loading).toBe(false)
  })

  it('★ AbortError 形态（原生/兼容路径）同样视为主动取消', async () => {
    postQuery.mockRejectedValueOnce({ name: 'AbortError' })
    const store = useQueryStore()
    await store.submitQuery({ q: '测试' })
    expect(store.error).toBe('')
  })
})

describe('stores/banks：错误消息必须透出后端中文 detail', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    listBanks.mockReset()
  })

  it('★ 加载失败时 error 是后端中文提示', async () => {
    listBanks.mockRejectedValueOnce(backendError('知识库不存在', 404))
    const store = useBanksStore()
    await store.fetchBanks()
    expect(store.error).toBe('知识库不存在')
  })
})
