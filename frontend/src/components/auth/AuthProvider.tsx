'use client'

import React, { createContext, useCallback, useEffect, useState } from 'react'
import type { UserRead } from '@/lib/types'
import api from '@/lib/api'
import type { AuthState } from './types'

export const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserRead | null>(null)
  const [loading, setLoading] = useState(true)

  const refreshUser = useCallback(async () => {
    try {
      const u = await api.users.me()
      setUser(u)
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const initAuth = async () => {
      // Try to get current user first
      await refreshUser()
      
      // In development, auto-login if not already authenticated
      if (typeof window !== 'undefined' && !user) {
        const isDev = process.env.NODE_ENV === 'development'
        if (isDev) {
          try {
            await api.auth.login('admin@pfl.com', 'Pass123!')
            await refreshUser()
          } catch {
            // Auto-login failed; user will see login page
            setLoading(false)
          }
        }
      }
    }
    
    initAuth()
  }, [refreshUser, user])

  const login = useCallback(
    async (email: string, password: string, mfaCode?: string) => {
      const resp = await api.auth.login(email, password, mfaCode)
      if (resp.mfa_required) return { mfaRequired: true }
      if (resp.mfa_enrollment_required) return { mfaEnrollmentRequired: true }
      await refreshUser()
      return {}
    },
    [refreshUser],
  )

  const logout = useCallback(async () => {
    try {
      await api.auth.logout()
    } finally {
      setUser(null)
    }
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  )
}
