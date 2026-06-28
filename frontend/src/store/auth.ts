import { create } from 'zustand'

interface AuthState {
  token: string | null
  uid: string | null
  displayName: string | null
  role: string | null
  setAuth: (token: string, uid: string, displayName: string, role: string) => void
  logout: () => void
  isAdmin: () => boolean
}

export const useAuth = create<AuthState>((set, get) => ({
  token: localStorage.getItem('token'),
  uid: localStorage.getItem('uid'),
  displayName: localStorage.getItem('displayName'),
  role: localStorage.getItem('role'),
  setAuth: (token, uid, displayName, role) => {
    localStorage.setItem('token', token)
    localStorage.setItem('uid', uid)
    localStorage.setItem('displayName', displayName)
    localStorage.setItem('role', role)
    set({ token, uid, displayName, role })
  },
  logout: () => {
    localStorage.clear()
    set({ token: null, uid: null, displayName: null, role: null })
  },
  isAdmin: () => get().role === 'admin',
}))
