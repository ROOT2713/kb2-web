import { describe, it, expect } from 'vitest'
import { formatFileSize, formatCharCount, formatCompactNumber, formatDate } from './format'

describe('formatFileSize —— 字节量（File.size / 上传总量）', () => {
  it('小于 1KB 给整数 + 空格 + 单位', () => {
    expect(formatFileSize(0)).toBe('0 B')
    expect(formatFileSize(1)).toBe('1 B')
    expect(formatFileSize(1023)).toBe('1023 B')
  })

  it('KB / MB / GB 边界与一位小数', () => {
    expect(formatFileSize(1024)).toBe('1.0 KB')
    expect(formatFileSize(1536)).toBe('1.5 KB')
    expect(formatFileSize(1024 * 1024)).toBe('1.0 MB')
    expect(formatFileSize(1024 * 1024 * 1024)).toBe('1.0 GB')
  })

  it('非法输入给占位符而不是 NaN', () => {
    expect(formatFileSize(-1)).toBe('—')
    expect(formatFileSize(NaN)).toBe('—')
    expect(formatFileSize(Infinity)).toBe('—')
  })

  // 【契约】数字与单位之间必须有空格 —— 这正是修复前 ResultCard/UploadView 漂移的那一点
  it('数字与单位之间恒有空格（防与旧 ResultCard 的 "1.0KB" 写法回退）', () => {
    for (const n of [1024, 2048, 1024 * 1024]) {
      expect(formatFileSize(n)).toMatch(/^\d+(\.\d)? (B|KB|MB|GB)$/)
    }
  })
})

describe('formatCharCount —— 字符数（标准原文字数）', () => {
  it('一万字以下给精确值（带千分位）+ 「字」', () => {
    expect(formatCharCount(0)).toBe('0 字')
    expect(formatCharCount(512)).toBe('512 字')
    expect(formatCharCount(9999)).toBe('9,999 字')
  })

  it('一万字及以上换算「万字」', () => {
    expect(formatCharCount(10000)).toBe('1.0 万字')
    expect(formatCharCount(12600)).toBe('1.3 万字')
    expect(formatCharCount(125000)).toBe('12.5 万字')
  })

  it('非法输入给占位符', () => {
    expect(formatCharCount(-1)).toBe('—')
    expect(formatCharCount(NaN)).toBe('—')
  })

  // 【修掉的缺陷】原实现把字符数按 1024 进制当字节显示（"12.3KB"），
  // 既错标单位又错用进制。此断言锁死「字数不得出现 B/KB/MB」。
  it('字数单位不得出现字节记号 B / KB / MB', () => {
    for (const n of [100, 2048, 12600, 5_000_000]) {
      expect(formatCharCount(n)).not.toMatch(/\d\s?(B|KB|MB)\b/)
      expect(formatCharCount(n)).toMatch(/字/)
    }
  })
})

describe('formatCompactNumber', () => {
  it('按 1000 进制压缩', () => {
    expect(formatCompactNumber(999)).toBe('999')
    expect(formatCompactNumber(1500)).toBe('1.5K')
    expect(formatCompactNumber(2_500_000)).toBe('2.5M')
  })
  it('非法输入给占位符', () => {
    expect(formatCompactNumber(NaN)).toBe('—')
  })
})

describe('formatDate', () => {
  it('ISO 串截到日期部分', () => {
    expect(formatDate('2026-09-05T12:00:00Z')).toBe('2026-09-05')
  })
  // 【修掉的缺陷】原来各处裸写 `entry.updated_at?.slice(0,10)`，
  // 空值会渲染出字符串 "undefined"；此处锁死空值必须给占位符。
  it('空值给占位符，绝不渲染出 "undefined"', () => {
    for (const v of [null, undefined, '']) {
      expect(formatDate(v)).toBe('—')
      expect(formatDate(v)).not.toContain('undefined')
    }
  })
})
