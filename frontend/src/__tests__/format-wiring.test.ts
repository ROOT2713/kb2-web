/**
 * 渲染级测试（批次 E）—— 钉住「命中规范原文」那条的用户可见文案。
 *
 * 为什么必须单独写：`format.spec.ts` 只能证明 formatCharCount/formatFileSize
 * 各自正确，**证明不了 ResultCard 用的是哪一个**。原来这里传的是 `total_chars`
 * （字符数）却按字节显示成 `12.3KB` —— 若有人把调用改回 formatFileSize，
 * utils 的单测依然全绿，而用户又会看到错的单位。故断言真实 DOM 文本。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ResultCard from '@/components/ResultCard.vue'

function mountCard(over: Record<string, unknown> = {}) {
  return mount(ResultCard, {
    props: {
      content: '',
      sources: [],
      standardContents: [],
      ...over,
    },
    global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

describe('ResultCard —— 命中规范原文的字数单位', () => {
  it('★ 字符数按「字」显示，绝不再标成字节 B/KB/MB', () => {
    const w = mountCard({
      standardContents: [
        { title: 'GB 50016 建筑设计防火规范', doc_id: 'd1', total_chars: 12600, sections_count: 3, preview: '' },
      ],
    })
    const meta = w.find('.standard-meta').text()

    expect(meta).toContain('1.3 万字')
    expect(meta).toContain('3章节')
    // 回归保护：修复前这里渲染的是 "12.3KB"
    expect(meta).not.toMatch(/\d\s?(B|KB|MB)\b/)
  })

  it('小字数给精确值 + 「字」', () => {
    const w = mountCard({
      standardContents: [
        { title: '小规范', doc_id: 'd2', total_chars: 512, sections_count: 1, preview: '' },
      ],
    })
    expect(w.find('.standard-meta').text()).toContain('512 字')
  })

  it('空 standardContents 不渲染该区块（且不炸）', () => {
    const w = mountCard()
    expect(w.find('.standard-contents').exists()).toBe(false)
  })
})

describe('ResultCard —— 回答正文渲染链（markdown + 消毒）', () => {
  it('Markdown 正常渲染', () => {
    const w = mountCard({ content: '# 标题\n\n**要点**' })
    expect(w.find('.result-body').html()).toContain('<h1')
    expect(w.find('.result-body').html()).toContain('<strong>')
  })

  it('★ 注入面被消毒（onerror 不得出现在 DOM 属性里）', () => {
    const w = mountCard({ content: '<img src=x onerror="alert(1)">正文' })
    const html = w.find('.result-body').html()
    expect(html).not.toContain('onerror')
    expect(html).toContain('正文')
  })
})
