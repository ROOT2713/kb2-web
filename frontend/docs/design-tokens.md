# L02 设计规范实施方案

> 项目: kb2-web 前端  
> 当前版本: CSS Variables + Vue SFC scoped styles  
> 无 UI 框架  
> 日期: 2026-07-09

---

## 目录

1. [现有 CSS Tokens 审核](#1-现有-css-tokens-审核)
2. [建议新增 Tokens](#2-建议新增-tokens)
3. [组件规范清单](#3-组件规范清单)
4. [迁移步骤](#4-迁移步骤)
5. [工时估计](#5-工时估计)
6. [交付物清单](#6-交付物清单)

---

## 1. 现有 CSS Tokens 审核

### 1.1 现状总览 (`frontend/src/assets/main.css` — 18 个 tokens)

| 类别 | 现有 Token | 值 | 审核结论 |
|---|---|---|---|
| **背景色** | `--bg` | `hsl(220,20%,98%)` | ✅ 正确 |
| | `--bg-alt` | `hsl(220,18%,95%)` | ✅ 正确 |
| **前景色** | `--fg` | `hsl(220,25%,12%)` | ✅ 正确 |
| | `--fg-muted` | `hsl(220,15%,45%)` | ✅ 正确 |
| **强调色** | `--accent` | `hsl(210,70%,48%)` | ✅ 正确 |
| | `--accent-hover` | `hsl(210,70%,40%)` | ✅ 正确 |
| | `--accent-light` | `hsl(210,60%,95%)` | ✅ 正确 |
| **边框** | `--border` | `hsl(220,15%,88%)` | ✅ 正确 |
| **语义色** | `--danger` | `hsl(0,65%,52%)` | ✅ 正确 |
| | `--danger-hover` | `hsl(0,65%,44%)` | ✅ 正确 |
| | `--success` | `hsl(145,55%,42%)` | ✅ 正确 |
| | `--warning` | `hsl(38,85%,50%)` | ✅ 正确 |
| **圆角** | `--radius` | `0px` | ⚠️ 值为 0，但多处组件使用硬编码非零圆角 → 实际设计意图并非直角 |
| **布局** | `--sidebar-w` | `220px` | ✅ 正确 |
| | `--header-h` | `52px` | ✅ 正确 |
| **字体** | `--font-sans` | `'Inter', ...` | ✅ 正确 |
| | `--font-mono` | `'JetBrains Mono', ...` | ✅ 正确 |

### 1.2 缺失大类（8 个类别缺失）

| 缺失类别 | 严重程度 | 证据 |
|---|---|---|
| **字号尺度** | 🔴 高 | 所有组件使用硬编码 `font-size: 0.7rem ~ 1.5rem`，无层级统一 |
| **字重** | 🟡 中 | 硬编码 `font-weight: 500/600/700` 散落各处 |
| **行高** | 🟡 中 | 硬编码 `line-height: 1.5/1.6` |
| **间距尺度** | 🔴 高 | `padding: 0.5rem/1rem/1.5rem/2rem` 散落各处，无复用 |
| **阴影** | 🔴 高 | 完全无阴影 token — 对话框、卡片需要 |
| **层级 (z-index)** | 🔴 高 | 硬编码 `100, 90, 200, 300, 1000` 散落在 5+ 组件中 |
| **过渡动画** | 🟡 中 | 硬编码 `0.15s, 0.1s, 0.2s` |
| **断点** | 🟡 中 | `768px` 唯一断点，硬编码在 main.css 和 AppSidebar |

### 1.3 已使用但未定义的 Tokens（运行时错误风险）

| 被引用的 Token | 使用位置 | 影响 |
|---|---|---|
| `--card` | `LoginView.vue:72` | 页面背景无效果 |
| `--accent-fg` | `LoginView.vue:133` | 按钮文字颜色无效果 |
| `--fg2` | `LoginView.vue:86` | 副标题文字颜色无效果 |
| `--bg-elevated` | `UploadView.vue:648` | 存在硬编码 fallback |
| `--bg-hover` | `UploadView.vue:658` | 存在硬编码 fallback |

### 1.4 硬编码颜色实例

```css
/* AppSidebar.vue:78 — hover 背景 */
background: hsl(220, 15%, 92%);

/* UploadView.vue:648-658 — 次级按钮 */
background: var(--bg-elevated, #f3f3f3);
color: var(--fg, #333);
border: 1px solid var(--border, #d0d0d0);
&:hover { background: var(--bg-hover, #e8e8e8); }

/* ResultCard.vue:651-665 — 标签徽章 */
.fee-badge  { background: #fff3e0; color: #e65100; border-color: #ffe0b2; }
.kw-badge   { background: #e3f2fd; color: #1565c0; border-color: #bbdefb; }
mark.kw-highlight { background: #fff176; color: #333; }

/* LoginView.vue:123-127 — 错误提示 */
.login-error { color: #c0392b; border-color: #e8c4c0; background: #fdf2f1; }

/* ConfirmDialog.vue:32 — 遮罩层 */
background: rgba(0, 0, 0, 0.4);

/* SynonymsView.vue:258 — 遮罩层 */
background: rgba(0, 0, 0, 0.25);
```

### 1.5 硬编码圆角实例（既然 `--radius: 0px`）

| 位置 | 值 | 与 `--radius` 矛盾 |
|---|---|---|
| `WikiView.vue:128, DocumentDetail.vue:265` | `6px` | 是 |
| `AdminView.vue:437` | `6px` | 是 |
| `UploadView.vue:652` | `6px` | 是 |
| `DocumentDetail.vue:302` | `8px` | 是 |
| `DocumentDetail.vue:333` | `4px` | 是 |
| `UploadView.vue:715` | `4px` | 是 |
| `ResultCard.vue:514, 646` | `3px` | 是 |
| `ResultCard.vue:530` (suggestion chip) | `1rem` | 是 |

### 1.6 重复样式（提取到 main.css 会显著瘦身）

| 重复块 | 出现次数 | 影响行数 |
|---|---|---|
| `.page-title` (完全一致) | 8 次 | ~40 行 |
| `.toolbar` (高度相似) | 4 次 | ~20 行 |
| `.table-header` + `.table-row` (高度相似) | 3 次 | ~60 行 |
| `.section-title` | 3 次 | ~12 行 |
| `.form-row` + `.form-label` + `.form-actions` | 3 次 | ~30 行 |
| `.btn-sm` | 3 次 | ~12 行 |
| `.empty-state` | 3 次 | ~12 行 |
| `.error-msg` | 2 次 | ~8 行 |
| `.badge` (部分覆盖) | 2 次 | ~12 行 |

---

## 2. 建议新增 Tokens

### 2.1 新增原则

1. **不破坏现有 token 名称** — 只追加、不改名
2. **按功能模块分组** — 清晰的命名空间
3. **值从现有设计推导** — 取现有硬编码值的中位数/众数，保持一致
4. **渐进式采用** — 新增 token 定义后，组件逐步迁移而非一次性重写

### 2.2 新增 Tokens 完整列表

#### 2.2.1 Surface / 背景层 (新增 3 个)

```css
/* ── Surface / 背景层 ── */
--surface:          hsl(0, 0%, 100%);       /* 卡片/弹窗背景，替代 white */
--surface-hover:    hsl(220, 15%, 92%);     /* hover 状态背景，替换硬编码 */
--surface-elevated: hsl(0, 0%, 95%);         /* 次级按钮背景，替换硬编码 */
```

**来源**: `white` 出现最多作为卡片背景；`hsl(220,15%,92%)` 出现在 `AppSidebar:hover`；`#f3f3f3` 在 `UploadView`

#### 2.2.2 语义色补全 (新增 2 个)

```css
/* ── 语义色补全 ── */
--danger-bg:   hsl(0, 80%, 96%);            /* 错误背景，替换硬编码 #fdf2f1 */
--warning-bg:  hsl(38, 80%, 96%);           /* 警告背景 */
--success-bg:  hsl(145, 50%, 95%);          /* 成功背景 */
--info-bg:     hsl(210, 60%, 96%);          /* 信息背景 — Toast 缺 info 类型 */
```

#### 2.2.3 文字色补全 (新增 2 个)

```css
/* ── 文字色层级 ── */
--fg-secondary: hsl(220, 15%, 35%);         /* 次要文字（比 muted 重一点） */
--fg-on-accent: hsl(0, 0%, 100%);           /* 强调色上的文字，替代 white */
--fg-on-danger: hsl(0, 0%, 100%);           /* 危险色上的文字 */
```

**来源**: `color: white` 用于 primary/danger 按钮；`--accent-fg` 和 `--fg2` 在 LoginView 未定义

#### 2.2.4 字号尺度 (新增 8 个)

```css
/* ── 字号尺度 ── */
--text-xs:    0.7rem;    /* 徽章、统计标签、辅助信息 */
--text-sm:    0.75rem;   /* 日期、计数、次要元数据 */
--text-base:  0.825rem;  /* 正文（现有组件使用最密集的尺寸） */
--text-md:    0.875rem;  /* 按钮、输入框 */
--text-lg:    0.95rem;   /* 卡片标题 */
--text-xl:    1.1rem;    /* 页面标题 base */
--text-2xl:   1.4rem;    /* 页面标题 large (配合 clamp) */
--text-3xl:   1.5rem;    /* 登录页标题 */
```

#### 2.2.5 字重 (新增 3 个)

```css
/* ── 字重 ── */
--weight-medium: 500;
--weight-semibold: 600;
--weight-bold: 700;
```

#### 2.2.6 行高 (新增 2 个)

```css
/* ── 行高 ── */
--leading-tight:   1.4;
--leading-normal:  1.6;
```

#### 2.2.7 间距尺度 (新增 6 个)

```css
/* ── 间距尺度 (4/8/12/16/24/32) ── */
--space-1:   0.25rem;  /* 4px 基准 */
--space-2:   0.5rem;   /* 8px — 组件内间距 */
--space-3:   0.75rem;  /* 12px */
--space-4:   1rem;     /* 16px — 卡片内边距 */
--space-5:   1.5rem;   /* 24px — 页面边距 */
--space-6:   2rem;     /* 32px — 大间距 */
```

#### 2.2.8 圆角 (新增 3 个 — 修正当前 contradictions)

```css
/* ── 圆角 (调整 radius 为合理值) ── */
--radius-sm:  3px;     /* 徽章、小标签 */
--radius:     6px;     /* 默认圆角（重要：从 0px→6px 对齐实际使用） */
--radius-lg:  8px;     /* 大卡片、代码块 */
--radius-full: 9999px; /* 圆形胶囊 */
```

**⚠️ 注意**: 这是 breaking change — `--radius` 从 `0px` 改为 `6px`。需与团队确认。也可保留 `--radius: 0px` 并新增 `--radius-md: 6px` 让组件自行选择。**建议方案**：保留 `--radius: 0px` 作为兼容别名，新增 `--radius-sm/md/lg/full` 供新组件和迁移使用。

#### 2.2.9 阴影 (新增 3 个)

```css
/* ── 阴影 ── */
--shadow-sm:  0 1px 2px rgba(0,0,0,0.06);
--shadow:     0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
--shadow-lg:  0 4px 12px rgba(0,0,0,0.1);
```

#### 2.2.10 Z-index 层级 (新增 5 个)

```css
/* ── Z-index 层级 ── */
--z-sidebar:    90;
--z-header:     100;
--z-toast:      200;
--z-dialog:     300;
--z-modal:      1000;
```

#### 2.2.11 过渡动画 (新增 2 个)

```css
/* ── 过渡动画 ── */
--transition-fast: 0.1s ease;
--transition:      0.15s ease;
--transition-slow: 0.2s ease;
```

#### 2.2.12 响应式断点 (新增 1 个)

```css
/* ── 响应式断点 (仅供 @media 使用，无 var()) ── */
/* 已在 main.css 底部使用 */
```

### 2.3 完整 `:root` 区块（增量版本）

参见 [tokens/_index.css](./tokens/_index.css) — 或直接追加到 `main.css` `:root` 块内。

### 2.4 Token 命名规范

| 规范 | 示例 |
|---|---|
| 颜色语义: `--{用途}` | `--bg`, `--fg`, `--accent` |
| 状态变体: `--{base}-{state}` | `--accent-hover`, `--danger-bg` |
| 字号: `--text-{size}` | `--text-xs`, `--text-lg` |
| 间距: `--space-{n}` | `--space-1` ~ `--space-6` |
| 圆角: `--radius-{variant}` | `--radius-sm`, `--radius-lg` |
| 阴影: `--shadow-{variant}` | `--shadow-sm`, `--shadow-lg` |
| 层级: `--z-{layer}` | `--z-header`, `--z-dialog` |

---

## 3. 组件规范清单

### 3.1 组件与 View 一览

| # | 文件 | 类型 | 行数 | scoped CSS | 不规范项 |
|---|---|---|---|---|---|
| 1 | `AppHeader.vue` | 组件 | 56 | ✅ | — |
| 2 | `AppSidebar.vue` | 组件 | 107 | ✅ | 1 处硬编码色值 |
| 3 | `LoadingSpinner.vue` | 组件 | 63 | ✅ | — |
| 4 | `Toast.vue` | 组件 | 103 | ✅ | — |
| 5 | `ResultCard.vue` | 组件 | 670 | ✅ | 5+ 硬编码色值/圆角 |
| 6 | `ConfirmDialog.vue` | 组件 | 57 | ✅ | 硬编码遮罩色值 |
| 7 | `QueryView.vue` | View | 410 | ✅ | — |
| 8 | `BanksView.vue` | View | 207 | ✅ | 重复结构样式 |
| 9 | `DocumentsView.vue` | View | 242 | ✅ | 重复结构样式 |
| 10 | `DocumentDetail.vue` | View | 345 | ✅ | 硬编码圆角/色值 |
| 11 | `LoginView.vue` | View | 148 | ✅ | **使用未定义 tokens** |
| 12 | `UploadView.vue` | View | 865 | ✅ | 硬编码色值/fallback |
| 13 | `SynonymsView.vue` | View | 300 | ✅ | 重复结构样式 |
| 14 | `AdminView.vue` | View | 473 | ✅ | 重复结构样式 |
| 15 | `WikiView.vue` | View | 241 | ✅ | 硬编码圆角 |

### 3.2 按迁移优先级分组的组件规范

#### P0 — 紧急修复（未定义 token 引用，运行时可能无效果）

| 文件 | 行号 | 当前代码 | 替换为 |
|---|---|---|---|
| `LoginView.vue` | 72 | `background: var(--card)` | `background: var(--surface)` |
| `LoginView.vue` | 86 | `color: var(--fg2)` | `color: var(--fg-muted)` |
| `LoginView.vue` | 133 | `color: var(--accent-fg)` | `color: var(--fg-on-accent)` |

#### P1 — 硬编码色值 → token

| 文件 | 行号 | 当前值 | 替换为 |
|---|---|---|---|
| `AppSidebar.vue` | 78 | `hsl(220,15%,92%)` | `var(--surface-hover)` |
| `ResultCard.vue` | 651-659 | `#fff3e0/#e65100/#ffe0b2` / `#e3f2fd/#1565c0/#bbdefb` | CSS 变量引导类别色或保持 badge 硬编码（功能色，可接受） |
| `ResultCard.vue` | 661 | `#fff176/#333` | token 化或保持（功能高亮色，可接受） |
| `LoginView.vue` | 123-127 | `#c0392b/#e8c4c0/#fdf2f1` | `var(--danger)` / `var(--danger)` / `var(--danger-bg)` |
| `ConfirmDialog.vue` | 32 | `rgba(0,0,0,0.4)` | `var(--z-modal)` 无关，改用 named 或保持 |
| `SynonymsView.vue` | 258 | `rgba(0,0,0,0.25)` | 同上，统一为 `var(--overlay)` (建议新增) |
| `UploadView.vue` | 648-658 | 含 fallback 的色值 | `var(--surface-elevated)` / `var(--fg)` / `var(--border)` |

**新增** `--overlay: rgba(0,0,0,0.35)` — 统一对话框遮罩颜色

#### P2 — 硬编码圆角 → token

| 文件 | 位置 | 当前值 | 替换为 |
|---|---|---|---|
| `WikiView.vue` | 128 | `border-radius: 6px` | `var(--radius-md)` |
| `DocumentDetail.vue` | 193, 265, 302, 333 | `6px / 8px / 8px / 4px` | `var(--radius-md/lg/lg/sm)` |
| `UploadView.vue` | 652, 715 | `6px / 4px` | `var(--radius-md) / var(--radius-sm)` |
| `ResultCard.vue` | 514, 530, 646 | `3px / 1rem / 3px` | `var(--radius-sm) / var(--radius-full) / var(--radius-sm)` |
| `AdminView.vue` | 437 | `6px` | `var(--radius-md)` |

#### P3 — 重复样式提取为全局 utility

| 目标类 | 来源文件 | 提取到 | 预计瘦身 |
|---|---|---|---|
| `.page-title` | 8 个 View 文件 | `main.css` 公共区 | -40 行 scoped |
| `.toolbar` | 4 个 View | `main.css` | -20 行 |
| `.table-header` + `.table-row` | 3 个 View | `main.css` | -60 行 |
| `.section-title` | 3 个 View | `main.css` | -12 行 |
| `.form-row` / `.form-label` / `.form-actions` | 3 个 View | `main.css` | -30 行 |
| `.btn-sm` | 3 个 View | `main.css` | -12 行 |
| `.empty-state` | 3 个 View | `main.css` | -12 行 |
| `.error-msg` / `.error-state` | 2-3 个 View | `main.css` | -10 行 |
| `.badge` (二次定义覆盖) | 2 个文件 | `main.css` 增强 | -8 行 |

#### P4 — 字号/间距/字重 token 化

**所有 View 和组件**中的以下样式替换：

```css
/* Before */
font-size: 0.7rem;    →  var(--text-xs)
font-size: 0.75rem;   →  var(--text-sm)
font-size: 0.825rem;  →  var(--text-base)
font-size: 0.875rem;  →  var(--text-md)
font-size: 0.95rem;   →  var(--text-lg)
font-size: 1.1rem;    →  var(--text-xl)
font-weight: 600;     →  var(--weight-semibold)
font-weight: 700;     →  var(--weight-bold)
padding: 0.5rem 1rem; →  padding: var(--space-2) var(--space-4)
padding: 1rem;        →  padding: var(--space-4)
padding: 1.5rem;      →  padding: var(--space-5)
gap: 0.5rem;          →  gap: var(--space-2)
gap: 0.75rem;         →  gap: var(--space-3)
gap: 1rem;            →  gap: var(--space-4)
```

**注意**: P4 是纯纯的机械替换，建议最后做或用全局搜索替换。

---

## 4. 迁移步骤

### Phase 0 — 准备 (0.5 天)

1. 创建 docs/ 目录结构
2. 编写 `design-tokens.md`（本文档）
3. 编写 `tokens/_index.css` — 新 token 定义文件（供引用和审查）

### Phase 1 — 修复 Bug (0.5 天)

1. **修复 `LoginView.vue` 三个未定义 token** → 替换为实际存在的变量
2. **新增 `--overlay`** 并统一 ConfirmDialog + SynonymsView 遮罩色
3. **更新 `main.css`**: 追加 token 增量块（不修改现有 token）

### Phase 2 — 核心样式提取 (1 天)

1. 在 `main.css` 新增公共 utility 样式区
2. 从各 View 迁移 `.page-title` 到公共区（删除 scoped 中的副本）
3. 迁移 `.toolbar`、`.section-title`、`.empty-state`、`.error-msg`
4. 统一 `.table-header` + `.table-row` 布局模式
5. 统一 `.form-row` + `.form-label` + `.form-actions` 布局模式
6. 统一 `.btn-sm` 到公共区

### Phase 3 — 语义化 token 迁移 (1.5 天)

1. **颜色替换**: AppSidebar, UploadView, LoginView, DocumentDetail
2. **圆角替换**: WikiView, DocumentDetail, UploadView, ResultCard, AdminView
3. **阴影引入**: Card 组件加 `var(--shadow-sm)`，Dialog 加 `var(--shadow-lg)`
4. **z-index 替换**: 所有组件中的硬编码 z-index → `var(--z-*)`

### Phase 4 — 字号/间距 token 化 (1 天)

1. 机械替换 font-size → var(--text-*)
2. 机械替换 font-weight → var(--weight-*)
3. 机械替换 padding/gap → var(--space-*)
4. 机械替换 line-height → var(--leading-*)

### Phase 5 — ResultCard 专项 (0.5 天)

1. 功能标签色 token 化或确认保留硬编码
2. 圆角统一
3. `.badge` scoped 覆盖移除，使用全局增强版

### Phase 6 — 验证与回归 (0.5 天)

1. 全局无未定义 CSS 变量引用
2. 全局无硬编码色值（功能色除外）
3. 所有 View scoped CSS 至少减少 30% 体积
4. 视觉对比：前后截图对比

---

## 5. 工时估计

| Phase | 工作内容 | 预估工时 | 依赖 |
|---|---|---|---|
| P0 | 准备文档 | 0.5 天 | — |
| P1 | 修复 Bug | 0.5 天 | P0 |
| P2 | 核心样式提取 | 1 天 | P1 |
| P3 | 语义化 token 迁移 | 1.5 天 | P2 |
| P4 | 字号/间距 token 化 | 1 天 | P3 |
| P5 | ResultCard 专项 | 0.5 天 | P3 |
| P6 | 验证与回归 | 0.5 天 | P4-P5 |
| **合计** | | **5.5 天** | |

### 按角色分配

| 角色 | 工作内容 | 工时 |
|---|---|---|
| 前端工程师 | P1-P6 代码修改 | 4.5 天 |
| 设计师/审校 | P0 规范评审 + P6 视觉回归 | 1 天 |
| **总计** | | **5.5 天** |

---

## 6. 交付物清单

| # | 交付物 | 文件路径 | 状态 |
|---|---|---|---|
| 1 | 设计规范文档（本文） | `frontend/docs/design-tokens.md` | ✅ 完成 |
| 2 | 新增 Tokens CSS 定义 | `frontend/src/assets/tokens/_index.css` | 📝 待创建 |
| 3 | 更新后的 `main.css` | `frontend/src/assets/main.css` | 📝 Phase 1-2 |
| 4 | 组件 scoped CSS 修改 | 14 个 .vue 文件 | 📝 Phase 1-5 |
| 5 | 验证报告 | `frontend/docs/variation-report.md` | 📝 Phase 6 |

---

## 附录 A: Tokens 新增 CSS 代码块

```css
/* === 新增 Tokens 块 — 追加到 :root 末尾 === */

/* Surface / 背景层 */
--surface:          hsl(0, 0%, 100%);
--surface-hover:    hsl(220, 15%, 92%);
--surface-elevated: hsl(0, 0%, 95%);
--overlay:          rgba(0, 0, 0, 0.35);

/* 文字色层级 */
--fg-secondary: hsl(220, 15%, 35%);
--fg-on-accent: hsl(0, 0%, 100%);
--fg-on-danger: hsl(0, 0%, 100%);

/* 语义色背景 */
--danger-bg:  hsl(0, 80%, 96%);
--warning-bg: hsl(38, 80%, 96%);
--success-bg: hsl(145, 50%, 95%);
--info-bg:    hsl(210, 60%, 96%);

/* 字号 */
--text-xs:    0.7rem;
--text-sm:    0.75rem;
--text-base:  0.825rem;
--text-md:    0.875rem;
--text-lg:    0.95rem;
--text-xl:    1.1rem;
--text-2xl:   1.4rem;
--text-3xl:   1.5rem;

/* 字重 */
--weight-medium:   500;
--weight-semibold: 600;
--weight-bold:     700;

/* 行高 */
--leading-tight:  1.4;
--leading-normal: 1.6;

/* 间距 (4/8/12/16/24/32) */
--space-1: 0.25rem;
--space-2: 0.5rem;
--space-3: 0.75rem;
--space-4: 1rem;
--space-5: 1.5rem;
--space-6: 2rem;

/* 圆角 */
--radius-sm:   3px;
--radius-md:   6px;
--radius-lg:   8px;
--radius-full: 9999px;

/* 阴影 */
--shadow-sm: 0 1px 2px rgba(0,0,0,0.06);
--shadow-md: 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
--shadow-lg: 0 4px 12px rgba(0,0,0,0.1);

/* Z-index */
--z-sidebar: 90;
--z-header:  100;
--z-toast:   200;
--z-dialog:  300;
--z-modal:   1000;

/* 过渡 */
--transition-fast: 0.1s ease;
--transition:      0.15s ease;
--transition-slow: 0.2s ease;
```

---

## 附录 B: 现有 token → 新增 token 映射

| 现有 Token | 建议保留？ | 备注 |
|---|---|---|
| `--bg` | ✅ 保留 | 全局背景 |
| `--bg-alt` | ✅ 保留 | 次要背景 |
| `--fg` | ✅ 保留 | 主文字 |
| `--fg-muted` | ✅ 保留 | 弱化文字 |
| `--accent` | ✅ 保留 | 强调色 |
| `--accent-hover` | ✅ 保留 | 强调 hover |
| `--accent-light` | ✅ 保留 | 强调背景 |
| `--border` | ✅ 保留 | 边框 |
| `--danger` / `--danger-hover` | ✅ 保留 | 危险色 |
| `--success` | ✅ 保留 | 成功色 |
| `--warning` | ✅ 保留 | 警告色 |
| `--radius` | ⚠️ 保留但建议弃用 | 新增 `--radius-sm/md/lg/full` |
| `--sidebar-w` | ✅ 保留 | 布局 |
| `--header-h` | ✅ 保留 | 布局 |
| `--font-sans` / `--font-mono` | ✅ 保留 | 字体 |

---

*文档版本: v1.0  
*最后更新: 2026-07-09  
*作者: Hermes Agent (L02 实施方案自动生成)*
