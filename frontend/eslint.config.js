/**
 * eslint.config.js —— ESLint 10 flat config（批次 E / 审计 A6）
 *
 * 修复前的问题
 * ----------
 * `package.json` 里 `"lint": "eslint . --ext .vue,.ts"` 引用了 eslint，
 * 但项目**既没有 eslint 依赖、也没有任何配置文件** ⇒ 实测 `npm run lint`
 * 输出 `sh: 1: eslint: not found`。lint 基建空转，等于没有。
 * 另有第二重失效：`--ext` 是 flat config 之前的旧语法，ESLint 9+ 已移除。
 *
 * 用法
 * ---
 *     npm run lint         # 检查
 *     npm run lint:fix     # 自动修可修项
 *
 * 设计取舍
 * ------
 * · **不做类型感知检查**（不用 `parserOptions.project`）—— 类型感知 lint 的首次
 *   运行会慢一个数量级，而本项目缺的是「基础规则守门」（未用变量、隐式 any、
 *   裸 v-html），不是深度类型推理。需要时再单独开 lint:type。
 * · `vue/no-v-html` 设为 **error**：`utils/sanitize.ts` 已是唯一消毒出口，
 *   裸用 v-html 应当是**需要显式豁免的例外**而非默认允许；现存 3 处链
 *   （ResultCard.vue:16/88/108）已在原处加 `eslint-disable-next-line` + 理由。
 */

import js from '@eslint/js'
import globals from 'globals'
import tseslint from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'

export default tseslint.config(
  {
    ignores: ['dist/**', 'node_modules/**', 'coverage/**', 'tmp/**', '*.config.js'],
  },

  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],

  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
        ecmaVersion: 'latest',
        sourceType: 'module',
      },
    },
    rules: {
      /** 裸 v-html 是 XSS 主入口；本项目已收敛出 utils/sanitize.ts 作为唯一出口 */
      'vue/no-v-html': 'error',
      'vue/no-unused-components': 'warn',
      'vue/no-unused-vars': 'warn',
      /** 单文件组件用文件名即组件名，无需多词 */
      'vue/multi-word-component-names': 'off',
      /** 纯风格项交给写作习惯，不引入 prettier 依赖 */
      'vue/attributes-order': 'off',
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/html-self-closing': 'off',
      'vue/html-indent': 'off',
      'vue/html-closing-bracket-newline': 'off',
      'vue/first-attribute-linebreak': 'off',
      'vue/html-closing-bracket-spacing': 'off',
      'vue/multiline-html-element-content-newline': 'off',
    },
  },

  {
    files: ['**/*.{ts,vue}'],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.es2021,
      },
    },
    rules: {
      /** 未用变量：允许 `_` 前缀显式忽略 */
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/no-explicit-any': 'warn',
      /** Vue 模板与 DOM 断言里常见，关掉 */
      '@typescript-eslint/no-non-null-assertion': 'off',
      /** 保留调试出口：允许 warn / error，禁 log */
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      /** `== null` 是同时覆盖 null/undefined 的惯用法，不能改成 ===（会漏 undefined） */
      eqeqeq: ['warn', 'always', { null: 'ignore' }],
      'prefer-const': 'warn',
      /** 空 catch 必须带注释说明（本项目多处「静默降级」是有意为之） */
      'no-empty': ['warn', { allowEmptyCatch: false }],
    },
  },

  {
    /** 单测里放宽 */
    files: ['**/__tests__/**/*.ts', '**/*.{test,spec}.ts'],
    languageOptions: {
      globals: { ...globals.node, ...globals.browser },
    },
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      'no-console': 'off',
      '@typescript-eslint/no-unused-vars': 'off',
    },
  },
)
