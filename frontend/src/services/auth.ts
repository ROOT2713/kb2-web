import api from './api'

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
}

export function login(username: string, password: string) {
  return api.post<LoginResponse>('/auth/login', { username, password })
}
