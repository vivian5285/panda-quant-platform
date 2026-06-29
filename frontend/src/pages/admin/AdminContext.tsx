import { createContext, useContext } from 'react'

/** Shared admin console state + actions (provided by Admin.tsx). */
export type AdminContextValue = Record<string, any>

const AdminContext = createContext<AdminContextValue | null>(null)

export function AdminProvider({ value, children }: { value: AdminContextValue; children: React.ReactNode }) {
  return <AdminContext.Provider value={value}>{children}</AdminContext.Provider>
}

export function useAdmin(): AdminContextValue {
  const ctx = useContext(AdminContext)
  if (!ctx) throw new Error('useAdmin must be used within AdminProvider')
  return ctx
}
