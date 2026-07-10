# L01 响应式适配实施方案

> 项目: kb2-web/frontend  
> 日期: 2026-07-09  
> 当前状态: 仅 `main.css` 有一个 `@media (max-width: 768px)` 断点，隐藏 Sidebar 并清零 margin-left  
> 目标: 覆盖 **mobile (< 640px)** / **tablet (640–1024px)** / **desktop (> 1024px)** 三个断点

---

## 目录

1. [断点方案](#1-断点方案)
2. [Sidebar 折叠方案](#2-sidebar-折叠方案)
3. [逐组件评估与修改](#3-逐组件评估与修改)
4. [逐视图评估与修改](#4-逐视图评估与修改)
5. [移动端表格展示方案](#5-移动端表格展示方案)
6. [文件修改清单](#6-文件修改清单)
7. [工时估计](#7-工时估计)

---

## 1. 断点方案

### 1.1 断点定义（CSS 自定义属性 + 媒体查询）

```css
/* main.css 新增 */
/* 断点 tokens（供 JS 和 CSS 引用） */
:root {
  --bp-mobile:  640px;
  --bp-tablet:  1024px;
}

/* 三个断点层级 */
@media (max-width: 639px)  { /* mobile */ }
@media (min-width: 640px) and (max-width: 1023px) { /* tablet */ }
@media (min-width: 1024px) { /* desktop — 已经是当前默认行为 */ }
```

### 1.2 设计原则

| 断点 | 视口宽度 | 行为 |
|------|---------|------|
| **Desktop** | ≥ 1024px | **当前行为不变**：Sidebar 常开, Header nav 行内, 表格 grid 列展示 |
| **Tablet** | 640–1023px | Sidebar 可折叠（按钮切换, 覆盖层）, Header nav 可滚动, 表格列自适应 |
| **Mobile** | < 640px | Sidebar 全屏覆盖层, Header 汉堡菜单, 表格横向滚动 / 卡片化, 表单单列 |

### 1.3 当前 main.css 已有内容

```css
/* 仅有的响应式代码 — 过于简陋 */
@media (max-width: 768px) {
  :root { --sidebar-w: 0px; }
  .app-main { margin-left: 0; padding: 1rem; }
}
```

需要替换为更精确的三段式断点。

---

## 2. Sidebar 折叠方案

### 2.1 问题

- 当前 `< 768px` 时 Sidebar `display: none`，用户无法切换知识库
- 无切换按钮，Sidebar 内容完全不可达
- Sidebar 固定定位 `top: var(--header-h)`，与 Header 存在层叠关系

### 2.2 方案：Slide-over 抽屉（覆盖层）

#### 2.2.1 响应式行为

| 断点 | Sidebar 状态 | 触发方式 |
|------|-------------|---------|
| Desktop (≥ 1024px) | 常开, `position: fixed`, `width: var(--sidebar-w)` | 无切换 |
| Tablet (640–1023px) | 默认关闭, 打开时覆盖在主内容之上 | Header 中汉堡按钮切换 |
| Mobile (< 640px) | 默认关闭, 打开时全屏覆盖层 | 同上 |

#### 2.2.2 具体实现

**App.vue** 新增响应式 Sidebar 状态：

```ts
// 新增响应式状态
const sidebarOpen = ref(false)

// 监听路由变化，切换路由时自动关闭 Sidebar（移动端/平板）
watch(() => route.path, () => {
  if (window.innerWidth < 1024) sidebarOpen.value = false
})
```

**AppSidebar.vue** 改造：

```vue
<template>
  <!-- Tablet/Mobile: 遮罩层 -->
  <Transition name="sidebar-fade">
    <div
      v-if="isBelowTablet && open"
      class="sidebar-overlay"
      @click="$emit('close')"
    />
  </Transition>

  <!-- Sidebar 本体 -->
  <aside
    class="app-sidebar"
    :class="{
      'sidebar-open': open,
      'sidebar-collapsed': !open && isBelowTablet,
    }"
  >
    <!-- 内容不变 -->
  </aside>
</template>
```

新增 props/emits: `open: boolean`, `@close`

CSS 关键变更：

```css
/* Desktop 模式 — 不变 */
.app-sidebar {
  position: fixed;
  top: var(--header-h);
  left: 0;
  bottom: 0;
  width: var(--sidebar-w);
  z-index: 90;
}

/* Tablet/Mobile 关闭时移出视口 */
@media (max-width: 1023px) {
  .app-sidebar {
    transform: translateX(-100%);
    transition: transform 0.2s ease;
    z-index: 110; /* 高于 header */
  }
  .app-sidebar.sidebar-open {
    transform: translateX(0);
  }
}

/* 遮罩层 */
.sidebar-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.35);
  z-index: 105;
}

/* 过渡动画 */
.sidebar-fade-enter-active,
.sidebar-fade-leave-active { transition: opacity 0.2s; }
.sidebar-fade-enter-from,
.sidebar-fade-leave-to { opacity: 0; }
```

#### 2.2.3 Header 切换按钮

**AppHeader.vue** 新增：

```vue
<template>
  <header class="app-header">
    <!-- 汉堡菜单按钮 — 仅 tablet/mobile 可见 -->
    <button
      v-if="!isDesktop"
      class="header-menu-btn"
      @click="$emit('toggle-sidebar')"
      aria-label="切换侧边栏"
    >
      <span class="hamburger" :class="{ active: sidebarOpen }">
        <span class="hamburger-line" />
        <span class="hamburger-line" />
        <span class="hamburger-line" />
      </span>
    </button>

    <div class="header-brand">
      <span class="brand-mark">KB2</span>
      <span class="brand-sub">知识库</span>
    </div>
    <nav class="header-nav"><!-- 现有 nav links --></nav>
  </header>
</template>
```

新增 emits: `toggle-sidebar`

---

## 3. 逐组件评估与修改

### 3.1 AppHeader.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| 9 个 nav links 在 < 768px 时溢出换行 | 所有移动端页面 | 添加 `overflow-x: auto` + `flex-shrink: 0`；Brand 区 `min-width` 改为响应式 |
| 无汉堡菜单按钮 | Tablet/Mobile | 新增 toggle 按钮（见 2.2.3） |
| Brand 区 `min-width: calc(var(--sidebar-w) - 1.5rem)` | < 640px 时 sidebar-w=0 导致负值 | 改用固定值或断点内重写 |

```css
/* 修改 */
.header-brand {
  min-width: auto; /* 移除固定 min-width */
}

.header-nav {
  display: flex;
  align-items: center;
  gap: 0;
  overflow-x: auto;
  white-space: nowrap;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}

.header-nav::-webkit-scrollbar { display: none; }

.nav-link {
  flex-shrink: 0;
  padding: 0 0.6rem;
  font-size: 0.8rem;
}

@media (max-width: 639px) {
  .header-nav { gap: 0; }
  .nav-link { padding: 0 0.5rem; font-size: 0.75rem; }
}
```

### 3.2 AppSidebar.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| `< 768px` 时 `display: none`，完全不可用 | 所有移动端页面 | 替换为 slide-over 抽屉（见 §2） |
| 无响应式过渡动画 | Tablet/Mobile | 添加 CSS transition |
| 需要遮罩层 | Tablet/Mobile | 新增 `.sidebar-overlay` |

修改范围：
- 新增 `open` prop, `close` emit
- 新增 responsive CSS 块（取代现有 `display: none`）
- 新增 Transition 组件包裹遮罩层
- 新增 slot/class 控制

### 3.3 ConfirmDialog.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| 已用 `width: 90%; max-width: 400px` | — | 基本 OK |
| 按钮 `flex-end` 在小屏上可能溢出 | < 400px | 可选: 按钮改用 `flex-direction: column` 或 `flex-wrap: wrap` |

**修改量极小**，可选操作：

```css
@media (max-width: 400px) {
  .confirm-actions { flex-direction: column-reverse; }
  .confirm-actions button { width: 100%; }
}
```

### 3.4 LoadingSpinner.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| 无 | — | **无需修改** |

已有 `inline` 模式，`flex-direction` 自动适应，字体由 clamp 控制。

### 3.5 ResultCard.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| source-item `max-width: 400px` | < 640px 时仍为 400px 导致溢出 | 改为响应式 |
| source-text `word-break: break-all` | 中文换行点不当 | 改用 `word-break: break-word` + `overflow-wrap: break-word` |
| source-doc `max-width: 200px` | 移动端过宽 | 改为百分比 |
| suggestion-panel 内部布局 | 基本 OK | 仅微调 padding |

```css
@media (max-width: 639px) {
  .source-item { max-width: 100%; }
  .source-doc,
  .source-doc-link { max-width: 140px; }
  .source-text { word-break: break-word; overflow-wrap: break-word; }
  .suggestion-panel { padding: 0.5rem; }
}
```

### 3.6 Toast.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| `max-width: 360px`, `right: 1rem` | < 400px 时可能右侧溢出 | 改为 `left: 1rem; right: 1rem; max-width: none` |

```css
@media (max-width: 400px) {
  .toast {
    left: 0.5rem;
    right: 0.5rem;
    max-width: none;
    top: calc(var(--header-h) + 0.5rem);
  }
}
```

---

## 4. 逐视图评估与修改

### 4.1 QueryView.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| `query-options` flex 行包含多选框 + select + 按钮 | < 640px 时换行混乱 | 改用 grid 2列或 flex-wrap + 缩小 gap |
| 搜索按钮和联网搜索按钮并排 | < 400px 时按钮文字重叠 | 按钮 flex-grow+缩小 gap |
| 查询历史 item 三栏（文本+时间+删除） | < 480px 时时间列被挤压 | 移动端隐藏时间戳 |

```css
@media (max-width: 639px) {
  .query-options {
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  .option-label { font-size: 0.75rem; }
  .query-input-row button {
    flex: 1;
    font-size: 0.8rem;
    padding: 0.5rem 0.5rem;
  }
  .history-time { display: none; }
}
```

### 4.2 DocumentsView.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| 表格使用 grid 6列固定宽度 `1fr 100px 60px 50px 100px 130px` | 所有 < 800px 视口完全破碎 | 参见 §5 表格方案 |
| 工具栏三栏（搜索 + select + 按钮） | < 500px 时溢出 | 移动端垂直堆叠 |

```css
@media (max-width: 639px) {
  .toolbar { flex-direction: column; }
  .search-input, .bank-filter { width: 100%; }
}
```

### 4.3 AdminView.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| 审计表格 `1fr 100px 60px 1fr` | < 700px 时溢出 | 参见 §5 |
| 成本表格 `1fr 80px 100px 100px 100px` | < 800px 时溢出 | 参见 §5 |
| `stats-grid` flex 布局 | 基本 OK（自动换行） | 仅调整 gap |
| `health-row` `max-width: 400px` | < 480px 时 OK | 可选改为 100% |

```css
@media (max-width: 639px) {
  .stats-grid, .audit-summary {
    flex-wrap: wrap;
    gap: 0.75rem;
  }
  .stat-value { font-size: 1.2rem; }  /* 缩小数值字号 */
  .health-row { max-width: 100%; }
}
```

### 4.4 UploadView.vue

| 问题 | 影响范围 | 修改内容 |
|------|---------|---------|
| drop-zone `padding: 2.5rem` | < 480px 时浪费空间 | 缩小 padding |
| 上传结果行 `justify-content: space-between` | < 500px 时 label/value 换行错位 | 改为列布局 |
| 批量结果 `batch-summary` flex 行 | 基本 OK | 仅微调 |

```css
@media (max-width: 639px) {
  .drop-zone { padding: 1.5rem 1rem; }
  .drop-text { font-size: 0.8rem; }
  .result-row { flex-direction: column; gap: 0.2rem; }
  .batch-result-item { flex-direction: column; align-items: flex-start; gap: 0.2rem; }
}
```

### 4.5 DocumentsView.vue, AdminView.vue, SynonymsView.vue — 额外视图

| 视图 | 问题 | 修改 |
|------|------|------|
| **BanksView.vue** | 已用 `auto-fill, minmax(260px, 1fr)` — **无需修改** | — |
| **SynonymsView.vue** | 表格 `1fr 1fr 120px 130px` | 参见 §5 |
| **DocumentDetail.vue** | `info-grid` 2列在 < 500px 太挤 | 改为单列 |
| **WikiView.vue** | 树形结构已响应式 | 仅微调 padding |
| **LoginView.vue** | `padding: 2.5rem` 在小屏过大 | 缩小 padding |

**DocumentDetail.vue 修改**：

```css
@media (max-width: 480px) {
  .info-grid { grid-template-columns: 1fr; }
}
```

**LoginView.vue 修改**：

```css
@media (max-width: 400px) {
  .login-card { padding: 1.5rem; }
}
```

---

## 5. 移动端表格展示方案

### 5.1 涉及的表格

| 视图 | CSS Grid 列定义 | 问题 |
|------|----------------|------|
| DocumentsView | `1fr 100px 60px 50px 100px 130px` | 6列，320px 视口下每列仅 ~50px |
| AdminView (audit) | `1fr 100px 60px 1fr` | 4列，列宽不足 |
| AdminView (costs) | `1fr 80px 100px 100px 100px` | 5列，严重不足 |
| SynonymsView | `1fr 1fr 120px 130px` | 4列，操作列溢出 |

### 5.2 方案 A：横向滚动表格（推荐，改动最小）

保持 grid 布局不变，在 < 640px 时外层容器添加横向滚动。

```css
@media (max-width: 639px) {
  .doc-table, .syn-table, .audit-table, .costs-table {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
  .table-header, .table-row {
    /* 保持原有 grid-template-columns，但父容器可滚动 */
    min-width: 600px; /* 保证所有列可见 */
  }
}
```

**优点**：改动最小，仅需在每个 table 容器加 overflow-x + min-width  
**缺点**：用户需要横向滚动，体验略差但功能完整

### 5.3 方案 B：卡片式列表（推荐，体验最佳）

在 < 480px 时表格行转为卡片式布局。

**DocumentsView 示例**：

```css
@media (max-width: 480px) {
  .table-header { display: none; }  /* 隐藏表头 */
  
  .doc-table .table-row {
    display: flex;
    flex-direction: column;
    padding: 0.75rem;
    gap: 0.3rem;
    border-bottom: 1px solid var(--border);
  }
  
  .table-row .col-title { font-size: 0.9rem; font-weight: 600; }
  .table-row .col-bank { order: -1; }
  .table-row .col-chunks::before { content: "分块: "; color: var(--fg-muted); }
  .table-row .col-date::before { content: "日期: "; color: var(--fg-muted); }
  .table-row .col-actions { margin-top: 0.3rem; }
}
```

**SynonymsView 示例**：

```css
@media (max-width: 480px) {
  .syn-table .table-header { display: none; }
  .syn-table .table-row {
    display: flex;
    flex-direction: column;
    padding: 0.75rem;
    gap: 0.3rem;
  }
  .table-row .col-term { font-size: 0.9rem; font-weight: 600; }
  .table-row .col-category { order: -1; }
  .table-row .col-actions { margin-top: 0.3rem; }
}
```

**AdminView audit/costs 示例**：

```css
@media (max-width: 480px) {
  .audit-table .table-header { display: none; }
  .audit-table .table-row {
    display: flex;
    flex-direction: column;
    padding: 0.75rem;
    gap: 0.3rem;
  }
  .table-row .col-doc { font-size: 0.9rem; font-weight: 600; }
  .table-row .col-issues { margin-top: 0.2rem; }
}
```

### 5.4 方案选择

| 断点 | 方案 |
|------|------|
| 640–1023px (Tablet) | **方案 A** — 横向滚动。保留列布局但容器可滚动 |
| < 480px (Mobile) | **方案 B** — 卡片式。隐藏表头，行内用 `::before` 伪元素展示标签 |

实际实现时，两个方案通过两个媒体查询并存。

---

## 6. 文件修改清单

### 6.1 修改列表

| 序号 | 文件 | 修改范围 | 预期变更行数 |
|------|------|---------|-------------|
| 1 | `src/assets/main.css` | 替换现有 `@media (max-width: 768px)` 为三段式断点；新增全局 app-layout 响应式规则 | ~30 行 |
| 2 | `src/App.vue` | 新增 `sidebarOpen` 响应式状态、路由变化自动关闭的逻辑；向 AppHeader 传递 `toggle-sidebar` 事件 | ~10 行 |
| 3 | `src/components/AppHeader.vue` | 新增汉堡菜单按钮（tablet/mobile 可见）；nav 添加横向滚动；brand min-width 修正 | ~25 行 |
| 4 | `src/components/AppSidebar.vue` | 替换 `display: none` 为 slide-over + transition + 遮罩层；新增 `open` prop / `close` emit | ~30 行 |
| 5 | `src/components/ConfirmDialog.vue` | 按钮区小屏垂直堆叠 | ~5 行 |
| 6 | `src/components/Toast.vue` | 小屏下左右撑满 | ~5 行 |
| 7 | `src/components/ResultCard.vue` | 移动端 source-item / source-doc / suggestion-panel 响应式调整 | ~15 行 |
| 8 | `src/views/QueryView.vue` | query-options flex-wrap；按钮移动端缩放；history-time 小屏隐藏 | ~15 行 |
| 9 | `src/views/DocumentsView.vue` | toolbar 垂直堆叠；表格响应式（方案 A+B 两段 media query） | ~30 行 |
| 10 | `src/views/AdminView.vue` | stats-grid 间距调整；audit/costs 表格响应式 | ~25 行 |
| 11 | `src/views/UploadView.vue` | drop-zone 小屏 padding；result-row 列布局；batch-item 自适应 | ~15 行 |
| 12 | `src/views/SynonymsView.vue` | 表格响应式（方案 A+B）；与 DocumentsView 相同模式 | ~20 行 |
| 13 | `src/views/DocumentDetail.vue` | info-grid 小屏单列 | ~5 行 |
| 14 | `src/views/LoginView.vue` | card padding 小屏缩小 | ~3 行 |

### 6.2 无需修改的文件

| 文件 | 原因 |
|------|------|
| `LoadingSpinner.vue` | 已自适应 |
| `BanksView.vue` | CSS Grid `auto-fill` 已天然响应式 |
| `WikiView.vue` | 树形结构已全宽自适应 |

### 6.3 修改预览（总行数）

| 类别 | 文件数 | 总新增/修改行数 |
|------|--------|---------------|
| 基础样式 (main.css) | 1 | ~30 |
| 布局/壳 (App.vue) | 1 | ~10 |
| 组件 (5 个) | 5 | ~80 |
| 视图 (6 个) | 6 | ~113 |
| **合计** | **13** | **~233** |

---

## 7. 工时估计

| 阶段 | 工时 | 说明 |
|------|------|------|
| **基础样式与断点** | 0.5h | main.css 断点定义 + app-layout 全局适配 |
| **App.vue 改造** | 0.5h | 新增 sidebar 状态管理 + 路由监听 |
| **AppHeader 改造** | 1.0h | 汉堡按钮 + nav 滚动 + brand 修正 |
| **AppSidebar 抽屉改造** | 1.5h | slide-over 动画 + 遮罩层 + transition |
| **表格响应式（4 个视图）** | 2.0h | DocumentsView + SynonymsView + AdminView(audit/costs) |
| **其他视图微调** | 1.5h | QueryView + UploadView + DocumentDetail + LoginView |
| **组件微调** | 0.5h | ConfirmDialog + Toast + ResultCard |
| **测试与调试** | 1.0h | 3 个断点逐页验证 + 交互检查 |
| **总计** | **8.5h** | — |

### 7.1 依赖关系

```
main.css (基础断点)
  ├── App.vue (sidebar 状态)
  │   ├── AppHeader.vue (汉堡按钮 + nav 滚动)
  │   └── AppSidebar.vue (抽屉 + 遮罩)
  ├── ConfirmDialog.vue, Toast.vue, ResultCard.vue (组件微调 — 可并行)
  ├── QueryView.vue, UploadView.vue, DocumentDetail.vue, LoginView.vue (视图微调 — 可并行)
  └── DocumentsView.vue, SynonymsView.vue, AdminView.vue (表格响应式 — 可并行)
```

### 7.2 并行路径

- **路径 A**（核心骨架）：main.css → App.vue → AppHeader + AppSidebar（~3.5h, 阻塞后续）
- **路径 B**（可并行于 A 之后）：组件微调（0.5h）
- **路径 C**（可并行于 A 之后）：视图微调（2.5h）
- **路径 D**（可并行于 A 之后）：表格响应式（2.0h）
- **路径 E**（收尾）：全流程测试（1.0h）

**最短工期（2 人并行）**：**~5h**  
**单人顺序工期**：**~8.5h**
