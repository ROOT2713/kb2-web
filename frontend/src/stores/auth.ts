import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login as apiLogin } from '@/services/auth'

const TOKEN_KEY = 'kb2_token'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem(TOKEN_KEY) || '')
  const loading = ref(false)
  const error = ref<string | null>(null)

  const isAuthenticated = computed(() => !!token.value)

  async function login(username: string, password: string): Promise<boolean> {
    loading.value = true
    error.value = null
    try {
      const { data } = await apiLogin(username, password)
      token.value = data.access_token
      localStorage.setItem(TOKEN_KEY, data.access_token)
      return true
    } catch (e: any) {
      error.value = e.response?.data?.detail || '登录失败，请重试'
      return false
    } finally {
      loading.value = false
    }
  }

  function logout() {
    token.value = ''
    localStorage.removeItem(TOKEN_KEY)
  }

  return { token, loading, error, isAuthenticated, login, logout }
})
