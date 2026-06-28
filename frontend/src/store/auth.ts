import { create } from 'zustand'
import api from '../api/client'

interface AuthState {
  token: string | null
  uid: string | null
  displayName: string | null
  role: string | null
  setAuth: (token: string, uid: string, displayName: string, role: string) => void
  logout: () => void
  isAdmin: () => boolean
}

function applyToken(token: string | null) {
  if (token) {
    api.defaults.headers.common.Authorization = `Bearer ${token}`
    api.defaults.headers.common['X-Access-Token'] = token
  } else {
    delete api.defaults.headers.common.Authorization
    delete api.defaults.headers.common['X-Access-Token']
  }
}

const initialToken = localStorage.getItem('token')
if (initialToken) applyToken(initialToken)

export const useAuth = create<AuthState>((set, get) => ({
  token: initialToken,
  uid: localStorage.getItem('uid'),
  displayName: localStorage.getItem('displayName'),
  role: localStorage.getItem('role'),
  setAuth: (token, uid, displayName, role) => {
    localStorage.setItem('token', token)
    localStorage.setItem('uid', uid)
    localStorage.setItem('displayName', displayName)
    localStorage.setItem('role', role)
    applyToken(token)
    set({ token, uid, displayName, role })
  },
  logout: () => {
    localStorage.removeItem('token')
    localStorage.removeItem('uid')
    localStorage.removeItem('displayName')
    localStorage.removeItem('role')
    applyToken(null)
    set({ token: null, uid: null, displayName: null, role: null })
  },
  isAdmin: () => get().role === 'admin',
}))
