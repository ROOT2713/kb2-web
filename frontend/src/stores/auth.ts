import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login as apiLogin } from '@/services/auth'

const TOKEN_KEY = 'kb2_token'
const ROLE_KEY = 'kb2_role'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem(TOKEN_KEY) || '')
  const role = ref<string>(localStorage.getItem(ROLE_KEY) || '')
  const loading = ref(false)
  const error = ref<string | null>(null)

  const isAuthenticated = computed(() => !!token.value)
  const isAdmin = computed(() => role.value === 'admin')

  async function login(username: string, password: string): Promise<boolean> {
    loading.value = true
    error.value = null
    try {
      const { data } = await apiLogin(username, password)
      token.value = data.access_token
      role.value = data.role
      localStorage.setItem(TOKEN_KEY, data.access_token)
      localStorage.setItem(ROLE_KEY, data.role)
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
    role.value = ''
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(ROLE_KEY)
  }

  return { token, role, loading, error, isAuthenticated, isAdmin, login, logout }
})
