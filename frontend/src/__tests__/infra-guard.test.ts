/**
 * 基建守卫测试（批次 E）—— 防止「配置再次静默空转」。
 *
 * 为什么需要：本批修的两条缺陷都是**配置层面无报错但功能失效**：
 *   · `vite.config.ts` 的 dev proxy 指向 :3002（v1，已冻结）⇒ 本地开发连错后端，
 *     页面行为跟线上完全对不上，但**构建/运行全都不报错**；
 *   · `package.json` 声明 `lint` 脚本却**无 eslint 依赖、无配置文件**，
 *     且用了 flat config 已移除的 `--ext` ⇒ `npm run lint` 直接 `eslint: not found`。
 * 两者都不会被任何单测发现，只能靠「读配置文件断言」把它钉住。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'

// ⚠️ 不要用 `new URL('../..', import.meta.url)` —— vitest 转换后 import.meta.url
// 不是 file: 协议，会抛 `The URL must be of scheme file`。vitest 的 root 即本目录。
const FE = process.cwd()
const read = (rel: string) => readFileSync(resolve(FE, rel), 'utf8')
const exists = (rel: string) => existsSync(resolve(FE, rel))

describe('vite dev proxy —— 必须指向 kb2-web 生产端口', () => {
  const cfg = read('vite.config.ts')

  it('★ 默认 target 是 :3027，且代码中不得出现已冻结的 v1 端口 :3002', () => {
    expect(cfg).toContain("'http://localhost:3027'")
    // 注释里允许提及旧端口（用于说明缺陷），**代码行**不允许出现
    const code = cfg
      .split('\n')
      .filter(l => {
        const t = l.trim()
        return !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('/*')
      })
      .join('\n')
    expect(code).not.toContain('3002')
  })

  it('允许用环境变量覆盖（便于临时切后端）', () => {
    expect(cfg).toContain('VITE_API_TARGET')
  })

  it('生产构建关闭 sourcemap（源码不外泄）', () => {
    expect(cfg).toMatch(/sourcemap:\s*mode\s*!==\s*'production'/)
  })
})

describe('ESLint 基建 —— 必须真实可跑，不能是空转声明', () => {
  it('★ 配置文件存在', () => {
    expect(exists('eslint.config.js')).toBe(true)
  })

  it('★ 依赖真实存在于 package.json（修复前只有脚本、没有依赖）', () => {
    const pkg = JSON.parse(read('package.json'))
    const dev = Object.keys(pkg.devDependencies || {})
    for (const dep of ['eslint', '@eslint/js', 'typescript-eslint', 'eslint-plugin-vue']) {
      expect(dev, `缺少 lint 依赖 ${dep}`).toContain(dep)
    }
  })

  it('★ lint 脚本不得再使用 flat config 已移除的 --ext', () => {
    const pkg = JSON.parse(read('package.json'))
    expect(pkg.scripts.lint).toBe('eslint .')
    expect(pkg.scripts['lint:fix']).toBe('eslint . --fix')
  })

  it('★ 裸 v-html 设为 error 级（消毒应是需要豁免的例外）', () => {
    const cfg = read('eslint.config.js')
    expect(cfg).toMatch(/'vue\/no-v-html':\s*'error'/)
  })

  it('★ eqeqeq 必须放行 `== null`（AdminView.fmtMineru 依赖该惯用法）', () => {
    const cfg = read('eslint.config.js')
    expect(cfg).toMatch(/null:\s*'ignore'/)
  })
})
