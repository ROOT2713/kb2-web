import { describe, it, expect, vi, afterEach } from 'vitest'
import { marked } from 'marked'
import { renderMarkdown, stripMarkdownArtifacts } from './markdown'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('stripMarkdownArtifacts —— MinerU/LaTeX 残留清理', () => {
  it('去掉删除线标记（保留内容）', () => {
    expect(stripMarkdownArtifacts('~~已废止~~')).toBe('已废止')
  })

  it('去掉行内与块级 LaTeX 的 $ 包裹（保留公式内容）', () => {
    expect(stripMarkdownArtifacts('承重 $F=ma$ 计算')).toBe('承重 F=ma 计算')
    expect(stripMarkdownArtifacts('$$E=mc^2$$')).toBe('E=mc^2')
  })

  // ★ 关键牙齿：中文规范里 `3~5米，7~9米` 若被单波浪号删除线规则命中，
  // 会被腐蚀成 `35米，79米` —— **数值被静默改坏**。本函数刻意不含该规则，
  // 此断言防止有人「顺手补齐」而引入数据腐蚀。
  it('★ 不得腐蚀波浪号区间数值（3~5米，7~9米 必须原样保留）', () => {
    const s = '风管边长 3~5米，层高 7~9米。'
    expect(stripMarkdownArtifacts(s)).toBe(s)
  })

  it('单个波浪号也不动（与区间数值同一形态，无法安全区分）', () => {
    expect(stripMarkdownArtifacts('约 10~20%')).toBe('约 10~20%')
  })

  it('纯文本原样返回', () => {
    expect(stripMarkdownArtifacts('普通正文，无残留。')).toBe('普通正文，无残留。')
  })
})

describe('renderMarkdown —— marked + 消毒（顺序由本模块锁定）', () => {
  it('渲染基本 Markdown 结构', () => {
    expect(renderMarkdown('# 标题')).toContain('<h1')
    expect(renderMarkdown('| a | b |\n| --- | --- |\n| 1 | 2 |')).toContain('<table>')
    expect(renderMarkdown('**粗**')).toContain('<strong>')
  })

  it('空输入返回空串（null / undefined / "" 都不炸）', () => {
    expect(renderMarkdown('')).toBe('')
    expect(renderMarkdown(null)).toBe('')
    expect(renderMarkdown(undefined)).toBe('')
  })

  // ★ 关键牙齿：证明「消毒固定在最后一步」真的生效。
  // 若有人把 renderMarkdown 改成直接返回 marked.parse 的结果（漏消毒），
  // 这条立刻变红 —— 这正是本模块要防的回归。
  it('★ 输出必须已消毒：原始 HTML 的属性注入面不得存活', () => {
    const out = renderMarkdown('<img src=x onerror="alert(1)">')
    // 危险属性与载荷必须被剥掉
    expect(out).not.toContain('onerror')
    expect(out).not.toContain('alert(1)')
    // 注意：回答正文链**刻意**允许 <img>（Markdown 的 ![alt](url) 需要正常显示图片），
    // 只有来源文本链才额外禁媒体（ResultCard.renderSourceText 的 forbidMedia: true）。
    // 本断言把这条契约钉住，防止有人「顺手」把正文链也禁掉导致规范图片消失。
    expect(out).toContain('<img')

    const out2 = renderMarkdown('<script>alert(1)</script>正文')
    expect(out2).not.toContain('<script')
    expect(out2).toContain('正文')
  })

  it('★ 消毒在最后：Markdown 链接里的 javascript: 协议不得存活', () => {
    const out = renderMarkdown('[点我](javascript:alert(1))')
    expect(out.toLowerCase()).not.toContain('javascript:')
  })

  it('合法内容不被过度消毒（真退化保护）', () => {
    const out = renderMarkdown('承重墙 **不得** 拆除，详见 [规范](https://example.com/a)')
    expect(out).toContain('<strong>不得</strong>')
    expect(out).toContain('href="https://example.com/a"')
    expect(out).toContain('承重墙')
  })

  // 降级路径：marked 抛错时退回纯文本，且换行转 <br>，内容不丢且仍然消毒
  it('解析抛错时降级为纯文本 + <br>，且仍然消毒', () => {
    vi.spyOn(marked, 'parse').mockImplementation(() => {
      throw new Error('parse boom')
    })
    const out = renderMarkdown('第一行\n第二行<script>alert(1)</script>')
    expect(out).toContain('<br>')
    expect(out).toContain('第一行')
    expect(out).not.toContain('<script')
  })
})
