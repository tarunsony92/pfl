'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/components/auth/useAuth'

/**
 * Redirects non-admin users to /cases.
 * Returns `{ ready }` so the page can withhold rendering until the auth check is done.
 */
export function useRequireAdmin(): { ready: boolean } {
  const { user, loading } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (!loading && user && user.role !== 'admin') {
      router.push('/cases')
    }
  }, [loading, user, router])

  // ready = we've finished loading AND the user is actually an admin
  const ready = !loading && user?.role === 'admin'
  return { ready }
}
