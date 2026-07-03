<template>
  <header class="app-header">
    <div class="header-brand">
      <span class="brand-mark">KB2</span>
      <span class="brand-sub">知识库</span>
    </div>
    <nav class="header-nav">
      <RouterLink to="/query" class="nav-link">查询</RouterLink>
      <RouterLink v-if="authStore.isAdmin" to="/upload" class="nav-link">上传</RouterLink>
      <RouterLink to="/documents" class="nav-link">文档</RouterLink>
      <RouterLink to="/banks" class="nav-link">知识库</RouterLink>
      <RouterLink to="/synonyms" class="nav-link">同义词</RouterLink>
      <RouterLink v-if="authStore.isAdmin" to="/admin" class="nav-link">管理</RouterLink>
      <RouterLink to="/wiki" class="nav-link">Wiki</RouterLink>
      <RouterLink to="/extract" class="nav-link">提取</RouterLink>
    </nav>
  </header>
</template>

<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
</script>

<style scoped>
.app-header {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: var(--header-h);
  background: white;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 1.5rem;
  z-index: 100;
  gap: 2rem;
}

.header-brand {
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
  min-width: calc(var(--sidebar-w) - 1.5rem);
}

.brand-mark {
  font-weight: 700;
  font-size: 1.1rem;
  color: var(--accent);
  letter-spacing: -0.02em;
}
</style>
