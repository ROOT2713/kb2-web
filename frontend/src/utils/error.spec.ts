import { describe, it, expect } from 'vitest'
import { getErrorMessage, isAbortError, isAuthError } from './error'

describe('getErrorMessage —— 后端中文 detail 必须活到用户眼前', () => {
  // 【修掉的缺陷】原各处用 `e instanceof Error ? e.message : '...'`
  // ⇒ 用户看到 "Request failed with status code 400"，后端中文提示全丢。
  it('axios 400 带字符串 detail 时，返回后端原文（而非 "Request failed..."）', () => {
    const err = {
      response: { status: 400, data: { detail: '分类不能为空' } },
      message: 'Request failed with status code 400',
    }
    expect(getErrorMessage(err)).toBe('分类不能为空')
  })

  it('FastAPI 422 的 detail 数组被拍平成中文并合并', () => {
    const err = {
      response: {
        status: 422,
        data: { detail: [{ loc: ['body', 'q'], msg: '字段必填' }, { msg: '长度超限' }] },
      },
    }
    expect(getErrorMessage(err)).toBe('字段必填；长度超限')
  })

  it('detail 缺失时退到后端 message', () => {
    const err = { response: { status: 500, data: { message: '服务端异常' } } }
    expect(getErrorMessage(err)).toBe('服务端异常')
  })

  it('超时给专用文案', () => {
    expect(getErrorMessage({ code: 'ECONNABORTED' })).toContain('超时')
    expect(getErrorMessage({ message: 'timeout of 600000ms exceeded' })).toContain('超时')
  })

  it('网络错误给专用文案（而不是裸的 "Network Error"）', () => {
    expect(getErrorMessage({ message: 'Network Error' })).toContain('网络异常')
  })

  it('普通 Error 退回 message', () => {
    expect(getErrorMessage(new Error('boom'))).toBe('boom')
  })

  it('空值/无信息时给兜底文案，且兜底可定制', () => {
    expect(getErrorMessage(null)).toBe('请求失败，请重试')
    expect(getErrorMessage(undefined, '加载失败')).toBe('加载失败')
    expect(getErrorMessage({}, '加载失败')).toBe('加载失败')
  })

  it('优先级：detail > message > 超时/网络 > Error.message > 兜底', () => {
    const err = {
      response: { data: { detail: '后端说的', message: '后端message' } },
      code: 'ECONNABORTED',
      message: 'Network Error',
    }
    expect(getErrorMessage(err, '兜底')).toBe('后端说的')
  })
})

describe('isAbortError —— 三种取消标记必须都认', () => {
  // 【修掉的缺陷】修复前两份实现各只看 name（漏 code），UploadView 的
  // 30s 预检超时与 axios v0 兼容路径给的是 AbortError 名 —— 漏判会把
  // 「用户主动取消」当成错误弹给用户（批次 D 的 C5 正是要消灭这类噪音）。
  it('CanceledError / AbortError / ERR_CANCELED 三者任一即为 true', () => {
    expect(isAbortError({ name: 'CanceledError' })).toBe(true)
    expect(isAbortError({ name: 'AbortError' })).toBe(true)
    expect(isAbortError({ code: 'ERR_CANCELED' })).toBe(true)
  })

  it('真实取消错误的完整形态（axios v1 同时给 name 与 code）', () => {
    expect(isAbortError({ name: 'CanceledError', code: 'ERR_CANCELED', message: 'canceled' })).toBe(true)
  })

  it('普通错误与非对象输入不得误判为取消', () => {
    expect(isAbortError(new Error('boom'))).toBe(false)
    expect(isAbortError({ name: 'AxiosError', code: 'ERR_BAD_REQUEST' })).toBe(false)
    expect(isAbortError(null)).toBe(false)
    expect(isAbortError(undefined)).toBe(false)
    expect(isAbortError('CanceledError')).toBe(false)
    expect(isAbortError({})).toBe(false)
  })
})

describe('isAuthError', () => {
  it('仅 401 为真', () => {
    expect(isAuthError({ response: { status: 401 } })).toBe(true)
    expect(isAuthError({ response: { status: 403 } })).toBe(false)
    expect(isAuthError({ response: { status: 500 } })).toBe(false)
    expect(isAuthError(null)).toBe(false)
  })
})
