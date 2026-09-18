/**
 * 统一错误处理 —— 消除跨文件重复（批次 E / 审计 A2/C3）
 *
 * 修复前的问题
 * ----------
 * · **错误消息提取两份实现**：`services/api.ts`（detail → message → error.message
 *   → '请求失败'）与 `stores/auth.ts`（detail → '登录失败，请重试'）。前者比后者多兜两层。
 * · **「用户主动取消」判定两份实现**：`stores/query.ts:76`（批次 D 为 C5 写的局部
 *   `isAbortError`，只看 `name`）与 `views/UploadView.vue:429`（内联同样两行）。
 *   判定不全会导致「主动取消」被当成错误弹给用户 —— 批次 D 的 C5 正是要消灭这类噪音。
 * · 后端所有业务错误都走 `HTTPException(detail="中文提示")`，若前端兜底用
 *   `e instanceof Error ? e.message : '...'`，用户看到的是
 *   `Request failed with status code 400` —— **中文报错全丢**。
 */

/** axios 错误的最小结构（不引入 axios 类型依赖）。 */
interface AxiosLikeError {
  response?: {
    status?: number
    data?: { detail?: unknown; message?: unknown }
  }
  message?: string
  code?: string
  name?: string
}

/** FastAPI 的 detail 可以是字符串，也可以是 422 校验错误数组，统一拍平。 */
function normalizeDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map(item => {
        if (item && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg: unknown }).msg)
        }
        return String(item)
      })
      .join('；')
  }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message: unknown }).message)
  }
  return ''
}

/**
 * 从任意异常中提取「可直接展示给用户」的中文消息。
 * 优先级：后端 detail > 后端 message > 超时/网络专用文案 > Error.message > 兜底。
 */
export function getErrorMessage(err: unknown, fallback = '请求失败，请重试'): string {
  if (!err) return fallback

  const e = err as AxiosLikeError

  const detail = normalizeDetail(e.response?.data?.detail)
  if (detail) return detail

  const msg = normalizeDetail(e.response?.data?.message)
  if (msg) return msg

  if (e.code === 'ECONNABORTED' || e.message?.includes('timeout')) {
    return '请求超时，请稍后重试或缩小检索范围'
  }
  if (e.message === 'Network Error') {
    return '网络异常，请检查连接后重试'
  }
  if (e.message) return e.message

  return fallback
}

/**
 * 是否为「用户主动取消」。**必须列全三种标记**：axios v1 取消时
 * `name === 'CanceledError'` 且 `code === 'ERR_CANCELED'`；原生 fetch/AbortController
 * 及 axios v0 兼容路径给 `name === 'AbortError'`（本仓库 `UploadView` 的 30s 预检超时
 * 走的正是这一支）。漏掉任一种都会把正常取消弹成错误。
 */
export function isAbortError(err: unknown): boolean {
  const e = (err ?? {}) as AxiosLikeError
  const name = e.name ?? ''
  return name === 'CanceledError' || name === 'AbortError' || e.code === 'ERR_CANCELED'
}

/** 是否为鉴权失效（由 api 拦截器统一跳转登录，业务层可据此静默）。 */
export function isAuthError(err: unknown): boolean {
  return (err as AxiosLikeError)?.response?.status === 401
}
