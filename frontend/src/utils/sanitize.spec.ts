/**
 * XSS 收口回归锁（批次 C，2026-09-17）
 *
 * 背景：ResultCard.vue 的「来源文本」v-html 链曾漏消毒，实测可被
 *   `src.text = "<img src=x onerror=alert(1) 等保测评"` + queryKeywords=['等保测评']
 * 绕过（highlightKeywords 插入的 <mark ...> 自带字面 `>`，闭合了 cleanSourceText
 * 阶段残留的未闭合 <img 标签）→ 注入 img[onerror]。
 *
 * 本文件两层防护：
 *   ① 纯函数级：sanitizeHtml 必须剥离一切 on* 与可执行容器；
 *   ② 组件级（mount ResultCard）：真实渲染链的最终 DOM 里不得出现 on* 属性，
 *      且关键词高亮功能不得退化。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { sanitizeHtml } from './sanitize'
import ResultCard from '@/components/ResultCard.vue'

// ResultCard 顶层 import 了 api，组件级测试里替换为桩，避免真实请求
vi.mock('@/services/api', () => ({ default: { get: vi.fn().mockResolvedValue({ data: {} }) } }))

/** 把 HTML 解析进 DOM，返回所有 on* 事件属性（形如 img[onerror]） */
function eventAttrs(html: string): string[] {
  const d = document.createElement('div')
  d.innerHTML = html
  return Array.from(d.querySelectorAll('*')).flatMap((el) =>
    Array.from(el.attributes)
      .filter((a) => a.name.toLowerCase().startsWith('on'))
      .map((a) => `${el.tagName.toLowerCase()}[${a.name.toLowerCase()}]`),
  )
}

/** 把 HTML 解析进 DOM，返回所有标签名（形如 ['img','mark']）。
 *
 * 【为什么要 DOM 断言而不是字符串断言】字符串 `not.toContain('<input')`
 * 只能证明"这串文本里没有 <input"，证明不了"元素被剥离"（例如被转义成
 * `&lt;input` 也会通过）。标签名断言直接看解析结果，才是真断言。 */
function tagNames(html: string): string[] {
  const d = document.createElement('div')
  d.innerHTML = html
  return Array.from(d.querySelectorAll('*')).map((el) => el.tagName.toLowerCase())
}

/** 实际生效的载荷 —— 全部来自 jsdom 探针实测（修复前可注入） */
const PAYLOADS: Array<[string, string]> = [
  // 核心绕过：未闭合标签 + 后续 <mark> 提供的闭合 `>`
  ['未闭合 img + mark 闭合', '<img src=x onerror=alert(1) <mark class="kw-highlight">等保</mark>'],
  // 实体解码后残留（&gt; 不被 cleanSourceText 处理）
  ['实体残留 img', '<img src=x onerror=alert(1)&gt; <mark class="kw-highlight">等保</mark>'],
  // svg onload
  ['未闭合 svg', '<svg onload=alert(1) <mark class="kw-highlight">等保</mark>'],
  // 经典向量
  ['script 标签', '<script>alert(1)</script>'],
  ['img 事件属性', '<img src=x onerror=alert(1)>'],
  ['iframe', '<iframe src="https://evil.example/x"></iframe>'],
  // 注：原有一条 form/input 载荷已移除 —— 它不含任何 on* 属性，
  // 而本组断言是 eventAttrs(out) === [] ⇒ 恒真、无牙齿
  // （2026-09-17 CC 对抗审查发现，实测复核确认）。form/input 的剥离
  // 改由下方「容器标签被剥离」用例做 DOM 断言（tagNames），才是真断言。
  // 大小写混淆（HTML 属性名不区分大小写）
  ['大写 ONERROR', '<img src=x ONERROR=alert(1)>'],
  // 多事件属性
  ['多事件属性', '<img src=x onerror="alert(1)" onload="alert(2)">'],
  // javascript: 协议
  ['javascript: href', '<a href="javascript:alert(1)">点我</a>'],
]

/**
 * 组件级载荷：必须是**未经任何拼装的原始 src.text**（模拟后端真实返回）。
 *
 * 【为什么不复用上面的 PAYLOADS】那是喂给 sanitizeHtml 的「已拼装危险 HTML」。
 * 若把同一批字符串直接当 src.text 传入组件，它会先过 cleanSourceText ——
 * 其中已预置的 `<mark class="kw-highlight">` 含字面 `>`，会被 `<[^>]*>` 删掉，
 * 连带把关键词一起删掉 ⇒ highlightKeywords 插不进 mark ⇒ 无 `>` 闭合残留标签
 * ⇒ 载荷被「洗白」成安全，测试变成假阳性（实测：曾因此让 4/4 突变全部漏检）。
 *
 * 真实可利用组合 = 未闭合标签残留 + **关键词出现在其之后**（关键词由
 * highlightKeywords 插入的 `<mark ...>` 提供闭合用的 `>`）。来自探针 B1/B2/B3/B5。
 */
const COMPONENT_PAYLOADS: Array<[string, string, string]> = [
  ['未闭合 img（裸标签，无字面 >）', '<img src=x onerror=alert(1) 等保测评', '等保测评'],
  ['实体 &lt; 解码后残留', '&lt;img src=x onerror=alert(1) 等保测评', '等保测评'],
  ['未闭合 svg onload', '<svg onload=alert(1) 等保测评', '等保测评'],
  ['实体含 &gt; 残留', '&lt;img src=x onerror=alert(1)&gt; 等保测评', '等保测评'],
  ['文档前缀剥离后接载荷', '[文档:x][章节:y] <img src=x onerror=alert(1) 等保测评', '等保测评'],
]

describe('sanitizeHtml：载荷锁（on* 必须被剥离）', () => {
  for (const [name, payload] of PAYLOADS) {
    it(`剥离事件处理器 — ${name}`, () => {
      const out = sanitizeHtml(payload)
      expect(eventAttrs(out)).toEqual([])
    })
  }

  it('容器标签被剥离（DOM 断言，非字符串包含）', () => {
    // DOM 断言：直接看解析后的标签名，避免"被转义也算通过"的假阳性
    const formHtml = '<form action="//evil"><input name=a></form>'
    expect(tagNames(sanitizeHtml('<script>alert(1)</script>'))).not.toContain('script')
    expect(tagNames(sanitizeHtml('<iframe src="//evil"></iframe>'))).not.toContain('iframe')
    expect(tagNames(sanitizeHtml(formHtml))).not.toContain('form')
    expect(tagNames(sanitizeHtml(formHtml))).not.toContain('input')
    expect(tagNames(sanitizeHtml('<button>x</button>'))).not.toContain('button')
    expect(tagNames(sanitizeHtml('<textarea>x</textarea>'))).not.toContain('textarea')
    // 反向：承重项若被移除，本用例必须变红（见 /tmp/reverse_check_sanitize.py M3）
  })

  it('移除 javascript: 协议链接', () => {
    expect(sanitizeHtml('<a href="javascript:alert(1)">x</a>')).not.toContain('javascript:')
  })

  it('空输入返回空串（不返回 null/undefined）', () => {
    expect(sanitizeHtml('')).toBe('')
  })
})

describe('sanitizeHtml：功能不退化', () => {
  it('保留关键词高亮标记与 class（否则来源高亮失效）', () => {
    const out = sanitizeHtml('<mark class="kw-highlight">等保测评</mark>')
    expect(out).toContain('<mark')
    expect(out).toContain('class="kw-highlight"')
    expect(out).toContain('等保测评')
  })

  it('保留回答正文所需的 Markdown 结构（表格/标题/链接/换行）', () => {
    const md =
      '<h2>标题</h2><table><thead><tr><th>项</th></tr></thead>' +
      '<tbody><tr><td>值</td></tr></tbody></table>' +
      '<p>段落<br>换行</p><a href="https://example.com">链接</a>'
    const out = sanitizeHtml(md)
    expect(out).toContain('<h2')
    expect(out).toContain('<table')
    expect(out).toContain('<th')
    expect(out).toContain('<br')
    expect(out).toContain('href="https://example.com"')
  })

  it('普通文本原样保留', () => {
    expect(sanitizeHtml('等保测评 三级 与 二级 的差异')).toBe('等保测评 三级 与 二级 的差异')
  })
})

describe('ResultCard 组件级：真实渲染链最终 DOM 不得出现 on*', () => {
  for (const [name, text, kw] of COMPONENT_PAYLOADS) {
    it(`来源文本链消毒生效 — ${name}`, () => {
      const wrapper = mount(ResultCard, {
        props: {
          content: '正常回答',
          sources: [{ doc: 'd', doc_id: 'doc-1', text }],
          queryKeywords: [kw],
        },
        global: { stubs: { 'router-link': true } },
      })
      const node = wrapper.element.querySelector('.source-text')
      expect(node).not.toBeNull()
      const attrs = [...node!.querySelectorAll('*')].flatMap((el) =>
        [...el.attributes].map((a) => a.name.toLowerCase()),
      )
      expect(attrs.filter((n) => n.startsWith('on'))).toEqual([])
    })
  }

  it('关键词高亮在组件内仍然生效（收口未误伤功能）', () => {
    const wrapper = mount(ResultCard, {
      props: {
        content: '正常回答',
        sources: [{ doc: 'd', doc_id: 'doc-1', text: '这是关于等保测评的说明' }],
        queryKeywords: ['等保'],
      },
      global: { stubs: { 'router-link': true } },
    })
    const mark = wrapper.element.querySelector('.source-text mark.kw-highlight')
    expect(mark).not.toBeNull()
    expect(mark!.textContent).toBe('等保')
  })
})
