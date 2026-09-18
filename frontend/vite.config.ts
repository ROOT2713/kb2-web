import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

/**
 * vite.config.ts —— 批次 E / 审计 A5
 *
 * 修复前的问题
 * ----------
 * · `server.proxy['/api'].target` 硬编码 `http://localhost:3002` —— 那是 **v1
 *   （kb-web，已冻结）** 的端口。kb2-web 生产跑在 **:3027**，故 `npm run dev`
 *   下所有 `/api` 请求都打到**冻结的旧后端**（数据不同、契约不同，症状是
 *   「本地开发页面行为跟线上完全对不上」）。现改为环境变量可覆盖、默认 :3027。
 * · 未显式关闭 sourcemap —— 显式声明防止有人排查问题时打开后忘记还原。
 * · 无 manualChunks 分包 —— vue/marked/dompurify 全进单一 chunk，首屏大且
 *   任一依赖更新即整包缓存失效。
 *
 * 未采纳交付包的一项
 * ----------
 * 它给的 `test.server.deps.inline: ['vue-router']`（为消 router-link 未注册告警）
 * **本仓库不需要** —— 批次 D 已在测试里用 Pascal `RouterLink` 正确打桩，
 * 实测告警归零。多加 `inline` 只会引入 vite 依赖预打包的额外复杂度。
 */
export default defineConfig(({ mode }) => ({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  server: {
    port: 5173,
    proxy: {
      '/api': {
        // 【修正】默认指向 kb2-web 生产端口；需要时可 VITE_API_TARGET 覆盖
        target: process.env.VITE_API_TARGET || 'http://localhost:3027',
        changeOrigin: true,
      },
    },
  },

  build: {
    /** 生产显式关闭 —— 源码不外泄 */
    sourcemap: mode !== 'production',
    /** 单 chunk 超 800KB 才告警（默认 500KB 对本项目偏严） */
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        /** 按依赖稳定性分包：框架/工具库分开，缓存命中率提升 */
        manualChunks: {
          vue: ['vue', 'vue-router', 'pinia'],
          markdown: ['marked'],
          sanitize: ['dompurify'],
        },
      },
    },
  },

  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.{test,spec}.ts'],
  },
}))
