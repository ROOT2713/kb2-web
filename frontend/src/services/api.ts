import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 600000,
})

// Request interceptor: inject JWT token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('kb2_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Response interceptor: handle errors + auto-logout on 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Token expired or invalid — clear and redirect to login
      const currentPath = window.location.pathname
      localStorage.removeItem('kb2_token')
      if (currentPath !== '/login') {
        window.location.href = '/login?redirect=' + encodeURIComponent(currentPath)
      }
    }
    const message =
      error.response?.data?.detail ||
      error.response?.data?.message ||
      error.message ||
      '请求失败'
    console.error('[API Error]', message)
    return Promise.reject(error)
  },
)

export default api
