<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="login-title">知识库</h1>
      <p class="login-subtitle">请登录以继续访问</p>
      <form @submit.prevent="handleLogin" class="login-form">
        <div class="form-group">
          <label for="username">用户名</label>
          <input
            id="username"
            v-model="username"
            type="text"
            autocomplete="username"
            placeholder="请输入用户名"
            :disabled="authStore.loading"
          />
        </div>
        <div class="form-group">
          <label for="password">密码</label>
          <input
            id="password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            placeholder="请输入密码"
            :disabled="authStore.loading"
          />
        </div>
        <div v-if="authStore.error" class="login-error">
          {{ authStore.error }}
        </div>
        <button type="submit" class="login-btn" :disabled="authStore.loading || !username || !password">
          {{ authStore.loading ? '登录中...' : '登录' }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const username = ref('')
const password = ref('')

async function handleLogin() {
  const ok = await authStore.login(username.value, password.value)
  if (ok) {
    router.push('/query')
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg);
}

.login-card {
  width: 100%;
  max-width: 360px;
  padding: 2.5rem;
  border: 1px solid var(--border);
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
}

.login-title {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--fg);
  margin: 0 0 0.25rem;
  letter-spacing: -0.02em;
}

.login-subtitle {
  font-size: 0.875rem;
  color: var(--fg-secondary);
  margin: 0 0 1.75rem;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.form-group label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--fg);
}

.form-group input {
  padding: 0.625rem 0.75rem;
  border: 1px solid var(--border);
  background: var(--bg);
  font-size: 0.875rem;
  color: var(--fg);
  outline: none;
  transition: border-color 0.15s;
}

.form-group input:focus {
  border-color: var(--accent);
}

.login-error {
  font-size: 0.8125rem;
  color: var(--danger);
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--danger);
  background: var(--danger-bg);
}

.login-btn {
  padding: 0.625rem 1rem;
  border: none;
  background: var(--accent);
  color: var(--fg-on-accent);
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity var(--transition);
}

.login-btn:hover:not(:disabled) {
  opacity: 0.9;
}

.login-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
