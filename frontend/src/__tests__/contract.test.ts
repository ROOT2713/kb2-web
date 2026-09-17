/**
 * 契约修复回归测试（批次 D，2026-09-17）
 *
 * 这一组 bug 的共性是**静默失效** —— 不报错、不崩溃，功能就是不对：
 *   C1  前端从不回传 session_id  → 后端多轮域锁定（复用上轮文档白名单）完全失效，
 *       追问「那东莞呢」变成重新全库检索 → 召回漂移。grep session_id 零命中，无声无息。
 *   C4  读 `health.hindsight`，后端返 `vector_store` → 管理页该行**永远空白**。
 *   C5  abortQuery 只清本地状态    → HTTP 请求仍在后端跑满检索 + LLM，**计费照常发生**。
 *   C6  打 `/admin/categories`（admin 角色门控）→ viewer 必 403，被 catch 吞掉
 *       → 分类下拉框**静默变空**。
 *   C7  哨兵值 `''` 语义过载       → 用户把分类改回空时传 '' 被判空 → 400，改不回去。
 *
 * 所以判据不是「代码长什么样」，而是「参数真的发出去了 / DOM 真的变了」。
 * 这也是本文件同时做**纯函数级**与**组件级**（mount QueryView）两层的原因。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type MountingOptions } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const postMock = vi.fn()
const getMock = vi.fn()

vi.mock('@/services/api', () => ({
  default: {
    post: (...args: unknown[]) => postMock(...args),
    get: (...args: unknown[]) => getMock(...args),
  },
}))

// 组件级测试里 banks store 会打接口，替换为桩
vi.mock('@/stores/banks', () => ({
  useBanksStore: () => ({
    banks: [],
    selectedBank: 'all',
    selectBank: () => {},
    fetchBanks: () => {},
  }),
}))

import { postQuery, webSearch, EXCLUDE_DAILY_CATEGORIES, toCategoriesParam } from '@/services/query'
import { getCategories, getHealth, type AdminHealth } from '@/services/admin'
import { useQueryStore } from '@/stores/query'
import QueryView from '@/views/QueryView.vue'

/** 把 FormData 转成普通对象便于断言 */
function formToObject(fd: FormData): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of fd.entries()) out[k] = String(v)
  return out
}

/**
 * 组件级测试必须先让分类接口有数据 ——
 * 否则 `<option v-for>` 为空，`setValue('fee')` 找不到对应 option，
 * DOM 会把 select.value 置回 ''（这是 jsdom 行为，会被误读成产品缺陷）。
 */
function mockCategories() {
  getMock.mockResolvedValue({
    data: {
      super_categories: [
        { name: '费用类', categories: [{ key: 'fee', label: '费率', isolated: false }] },
      ],
    },
  })
}

/** 统一挂载选项：ResultCard 内有 router-link，测试环境无 router ⇒ 打桩消警告 */
const MOUNT_OPTS = { global: { stubs: { 'router-link': true } } } as MountingOptions<unknown>

beforeEach(() => {
  postMock.mockReset()
  getMock.mockReset()
  sessionStorage.clear()
  setActivePinia(createPinia())
})

// ══════════════════════════════════════════════════════════════════
// C1 —— session_id 必须回传（多轮域锁定的前提）
// ══════════════════════════════════════════════════════════════════
describe('C1 session_id 回传', () => {
  it('传了 session_id 就必须出现在 FormData 里', async () => {
    postMock.mockResolvedValue({ data: { answer: 'x', sources: [], session_id: 's2' } })
    await postQuery({ q: '费率', session_id: 'abc123' })
    expect(formToObject(postMock.mock.calls[0][1] as FormData).session_id).toBe('abc123')
  })

  it('没传 session_id 时不得凭空造一个字段（不产生噪声参数）', async () => {
    postMock.mockResolvedValue({ data: { answer: 'x', sources: [] } })
    await postQuery({ q: '费率' })
    expect(formToObject(postMock.mock.calls[0][1] as FormData)).not.toHaveProperty('session_id')
  })

  it('响应里的 session_id 必须回写到 sessionStorage（下一步追问才有得回传）', async () => {
    postMock.mockResolvedValue({ data: { answer: 'a', sources: [], session_id: 'srv-1' } })
    const store = useQueryStore()
    await store.submitQuery({ q: '费率' })
    expect(store.sessionId).toBe('srv-1')
    expect(sessionStorage.getItem('kb2_query_session')).toBe('srv-1')
  })

  it('store 自动把已存 session 注入下一轮请求（调用方无需手拼）', async () => {
    sessionStorage.setItem('kb2_query_session', 'stored-9')
    postMock.mockResolvedValue({ data: { answer: 'a', sources: [], session_id: 'stored-9' } })
    const store = useQueryStore()
    await store.submitQuery({ q: '那东莞呢' })
    expect(formToObject(postMock.mock.calls[0][1] as FormData).session_id).toBe('stored-9')
  })

  it('新会话：resetSession 后不再回传旧 session（回到全库检索）', async () => {
    sessionStorage.setItem('kb2_query_session', 'old-1')
    postMock.mockResolvedValue({ data: { answer: 'a', sources: [] } })
    const store = useQueryStore()
    store.resetSession()
    expect(store.sessionId).toBe('')
    expect(sessionStorage.getItem('kb2_query_session')).toBeNull()
    await store.submitQuery({ q: '新话题' })
    expect(formToObject(postMock.mock.calls[0][1] as FormData)).not.toHaveProperty('session_id')
  })
})

// ══════════════════════════════════════════════════════════════════
// C5 —— 取消查询要真取消
// ══════════════════════════════════════════════════════════════════
describe('C5 取消查询', () => {
  it('signal 必须透传到 axios（否则 C5 的取消是假的）', async () => {
    postMock.mockResolvedValue({ data: { answer: 'x', sources: [] } })
    const ctrl = new AbortController()
    await postQuery({ q: '费率' }, ctrl.signal)
    const opts = postMock.mock.calls[0][2] as { signal?: AbortSignal }
    expect(opts?.signal).toBe(ctrl.signal)
  })

  it('webSearch 同样透传 signal', async () => {
    postMock.mockResolvedValue({ data: { answer: 'x', web_searched: true, fallback_mode: false } })
    const ctrl = new AbortController()
    await webSearch({ q: 'x' }, ctrl.signal)
    expect((postMock.mock.calls[0][2] as { signal?: AbortSignal })?.signal).toBe(ctrl.signal)
  })

  it('abortQuery 真的 abort 请求，且不落红色错误（取消不是失败）', async () => {
    let seen: AbortSignal | undefined
    postMock.mockImplementation((_u: unknown, _fd: unknown, cfg?: { signal?: AbortSignal }) => {
      seen = cfg?.signal
      return new Promise((_res, rej) => {
        cfg?.signal?.addEventListener('abort', () => {
          const err = new Error('canceled')
          err.name = 'CanceledError'
          rej(err)
        })
      })
    })
    const store = useQueryStore()
    const p = store.submitQuery({ q: '慢查询' })
    await flushPromises()
    expect(seen).toBeDefined()
    expect(seen!.aborted).toBe(false)

    store.abortQuery()
    await p

    expect(seen!.aborted).toBe(true)
    expect(store.error).toBe('')       // 取消不弹错误
    expect(store.loading).toBe(false)  // loading 必须复位
  })

  it('新请求发起前先取消旧请求（防响应乱序覆盖）', async () => {
    const signals: AbortSignal[] = []
    postMock.mockImplementation((_u: unknown, _fd: unknown, cfg?: { signal?: AbortSignal }) => {
      signals.push(cfg!.signal!)
      return new Promise((_res, rej) => {
        cfg?.signal?.addEventListener('abort', () => {
          const err = new Error('canceled')
          err.name = 'CanceledError'
          rej(err)
        })
      })
    })
    const store = useQueryStore()
    void store.submitQuery({ q: '第一问' })
    await flushPromises()
    void store.submitQuery({ q: '第二问' })
    await flushPromises()
    expect(signals).toHaveLength(2)
    expect(signals[0].aborted).toBe(true)   // 旧的被取消
    expect(signals[1].aborted).toBe(false)  // 新的仍在跑
  })
})

// ══════════════════════════════════════════════════════════════════
// C4 —— health 字段名对齐后端
// ══════════════════════════════════════════════════════════════════
describe('C4 health 字段名', () => {
  it('后端返回 vector_store + mineru，前端必须能读到', async () => {
    getMock.mockResolvedValue({
      data: {
        status: 'ok',
        version: '2.0.0',
        vector_store: 'ok',
        db: 'ok',
        mineru: { success: 3, fail: 0 },
      },
    })
    const h = await getHealth()
    expect(h.vector_store).toBe('ok')
    expect(h.mineru).toEqual({ success: 3, fail: 0 })
  })

  it('类型层面不再有 hindsight（编译期锁）', () => {
    const h: AdminHealth = {
      status: 'ok',
      version: '2.0.0',
      vector_store: 'ok',
      db: 'ok',
      mineru: 'ok',
    }
    // @ts-expect-error hindsight 已从 AdminHealth 移除；若有人加回来，
    // 本行会因「无错误可忽略」而报错 —— 这把锁在 vue-tsc 下生效
    const bad: AdminHealth = { ...h, hindsight: 'x' }
    expect(bad.vector_store).toBe('ok')
  })
})

describe('C4 health 渲染（组件级 —— 类型擦除后仍能抓回归）', () => {
  it('管理页真的把 vector_store / mineru 渲染出来', async () => {
    getMock.mockImplementation((url: string) => {
      if (url === '/admin/health') {
        return Promise.resolve({
          data: {
            // 刻意不用 'ok' 这类通用词：否则 status 字段会顺带满足断言，
            // 让「回退成 health.hindsight（渲染空串）」这种突变偷偷溜过去
            status: 'HEALTHY',
            version: 'v9.9.9',
            vector_store: 'VECSTORE-STATE',
            db: 'DB-STATE',
            mineru: { success: 7, fail: 1 },
          },
        })
      }
      if (url === '/admin/stats') {
        return Promise.resolve({ data: { total_nodes: 1, total_documents: 2, total_links: 3 } })
      }
      // AdminView 在 onMounted 里还会拉一次费用（模板对 costs 直接取值，给空对象会渲染报错）
      if (url === '/admin/costs') {
        return Promise.resolve({
          data: {
            period: 'today',
            call_count: 0,
            total_prompt_tokens: 0,
            total_completion_tokens: 0,
            total_tokens: 0,
            total_cost_yuan: 0,
            by_model: [],
          },
        })
      }
      return Promise.resolve({ data: {} })
    })
    const AdminView = (await import('@/views/AdminView.vue')).default
    const wrapper = mount(AdminView, { global: { plugins: [createPinia()], ...MOUNT_OPTS.global } })
    await flushPromises()
    // 点「加载系统状态」触发 loadStats（stats 未加载时按钮才在）
    const btn = wrapper.findAll('button').find((b) => b.text().includes('加载系统状态'))
    if (btn) await btn.trigger('click')
    await flushPromises()

    const text = wrapper.text()
    const rows = wrapper.findAll('.health-row').map((el) => el.text())

    // 逐行断言（而不是全页 contains）—— 全页断言会被 status/db 等无关字段满足，
    // 突变测试实测过：退回 health.hindsight 时它照样通过
    const vecRow = rows.find((t) => t.includes('向量库'))
    expect(vecRow, '必须存在「向量库」这一行').toBeDefined()
    expect(vecRow).toContain('VECSTORE-STATE')   // ← 读 health.hindsight 时此处为空 → 必红

    const mineruRow = rows.find((t) => t.includes('MinerU'))
    expect(mineruRow, '必须存在 MinerU 这一行').toBeDefined()
    expect(mineruRow).toContain('success=7')
    expect(mineruRow).not.toContain('[object Object]')

    expect(text).not.toContain('Hindsight')      // 旧字段标签已消失
    expect(text).not.toContain('undefined')
  })
})


// ══════════════════════════════════════════════════════════════════
// C6 —— 分类接口走 viewer 可访问的端点
// ══════════════════════════════════════════════════════════════════
describe('C6 getCategories 走 viewer 端点', () => {
  it('优先调 /banks/categories 并正确解包 super_categories', async () => {
    getMock.mockResolvedValue({
      data: {
        super_categories: [
          { name: '费用类', categories: [{ key: 'fee', label: '费率', isolated: false }] },
        ],
      },
    })
    const list = await getCategories()
    expect(getMock.mock.calls[0][0]).toBe('/banks/categories')
    expect(list).toEqual([{ key: 'fee', label: '费率', isolated: false }])
  })

  it('/banks/categories 失败时回退到 /admin/categories（管理员场景仍可用）', async () => {
    getMock
      .mockRejectedValueOnce(new Error('403'))
      .mockResolvedValueOnce({
        data: [{ name: '费用类', categories: [{ key: 'fee', label: '费率', isolated: false }] }],
      })
    const list = await getCategories()
    expect(getMock.mock.calls[1][0]).toBe('/admin/categories')
    expect(list).toHaveLength(1)
  })

  it('两条路都失败时向上抛（调用方可区分「空」与「失败」）', async () => {
    getMock.mockRejectedValue(new Error('network'))
    await expect(getCategories()).rejects.toThrow()
  })
})

// ══════════════════════════════════════════════════════════════════
// C7 —— 哨兵值语义分离
// ══════════════════════════════════════════════════════════════════
describe('C7 分类哨兵值', () => {
  it('哨兵 → 空串（= 不传该字段）；具体 key 原样透传', () => {
    expect(toCategoriesParam(EXCLUDE_DAILY_CATEGORIES)).toBe('')
    expect(toCategoriesParam('fee')).toBe('fee')
    expect(toCategoriesParam('all')).toBe('all')
    // 空串现在只有「不传该字段」一层含义，不再是 UI 的「排除日常/资讯」
    expect(toCategoriesParam('')).toBe('')
  })

  it('哨兵值本身不得与任何真实分类 key 相同', () => {
    expect(EXCLUDE_DAILY_CATEGORIES.startsWith('__')).toBe(true)
    expect(EXCLUDE_DAILY_CATEGORIES).not.toBe('all')
    expect(EXCLUDE_DAILY_CATEGORIES).not.toBe('daily,news')
  })

  it('组件级：<option> 不再有两个同值选项，默认值即哨兵', async () => {
    const wrapper = mount(QueryView, { global: { plugins: [createPinia()], ...MOUNT_OPTS.global } })
    await flushPromises()

    const select = wrapper.find('select.cat-filter').element as HTMLSelectElement
    const values = Array.from(select.options).map((o) => o.value)

    expect(values).toContain(EXCLUDE_DAILY_CATEGORIES)
    expect(values).not.toContain('')            // ← 核心回归锁：裸空串选项已消失
    expect(new Set(values).size).toBe(values.length)  // 无重复值
    expect(select.value).toBe(EXCLUDE_DAILY_CATEGORIES) // 默认选中哨兵
    expect(select.options[0].text).toContain('排除日常/资讯')
  })

  it('组件级：默认筛选下发起查询，categories 字段根本不发出（保原行为）', async () => {
    mockCategories()
    postMock.mockResolvedValue({ data: { answer: 'a', sources: [], session_id: 'srv-2' } })
    const wrapper = mount(QueryView, { global: { plugins: [createPinia()], ...MOUNT_OPTS.global } })
    await flushPromises()

    await wrapper.find('input.query-input').setValue('佛山市800万项目测评费')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const obj = formToObject(postMock.mock.calls[0][1] as FormData)
    expect(obj.q).toBe('佛山市800万项目测评费')
    expect(obj).not.toHaveProperty('categories')   // 哨兵 → 空串 → 不发字段
    // C1：首轮不该凭空带 session（此前没有）；但响应回来后必须已落盘
    expect(obj).not.toHaveProperty('session_id')
    expect(sessionStorage.getItem('kb2_query_session')).toBe('srv-2')

    // 第二轮（模拟追问「那东莞呢」）必须带上上一轮的 session —— 多轮域锁定的前提
    await wrapper.find('input.query-input').setValue('那东莞呢')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(formToObject(postMock.mock.calls[1][1] as FormData).session_id).toBe('srv-2')
    // 且第二轮不应把 session 换掉（后端沿用同一 session）
    expect(sessionStorage.getItem('kb2_query_session')).toBe('srv-2')
  })

  it('组件级：选具体分类时 categories 原样发出', async () => {
    mockCategories()
    postMock.mockResolvedValue({ data: { answer: 'a', sources: [] } })
    const wrapper = mount(QueryView, { global: { plugins: [createPinia()], ...MOUNT_OPTS.global } })
    await flushPromises()

    await wrapper.find('select.cat-filter').setValue('fee')
    await wrapper.find('input.query-input').setValue('费率问题')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(formToObject(postMock.mock.calls[0][1] as FormData).categories).toBe('fee')
  })
})

// ══════════════════════════════════════════════════════════════════
// C1 组件级 —— 「新会话」按钮是 resetSession 的消费方
// ══════════════════════════════════════════════════════════════════
describe('C1 新会话按钮接线', () => {
  it('无 session 时不显示；有 session 时点击清空 sessionStorage', async () => {
    mockCategories()
    const wrapper = mount(QueryView, { global: { plugins: [createPinia()], ...MOUNT_OPTS.global } })
    await flushPromises()
    const findBtn = () =>
      wrapper.findAll('button').find((b) => b.text().includes('新会话'))
    expect(findBtn()).toBeUndefined()   // 全新对话：无 session，按钮不出现

    // 走一轮查询拿到 session
    postMock.mockResolvedValue({ data: { answer: 'a', sources: [], session_id: 'srv-3' } })
    await wrapper.find('input.query-input').setValue('第一问')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const btn = findBtn()
    expect(btn).toBeDefined()
    await btn!.trigger('click')
    await flushPromises()
    expect(sessionStorage.getItem('kb2_query_session')).toBeNull()
  })
})
