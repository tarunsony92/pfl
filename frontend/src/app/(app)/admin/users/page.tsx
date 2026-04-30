'use client'

/**
 * /admin/users — Admin Users management page.
 *
 * Admin-only (useRequireAdmin guard).
 * Shows UsersTable + NewUserDialog.
 */

import React, { useCallback, useEffect, useState } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { UsersTable } from '@/components/admin/UsersTable'
import { NewUserDialog } from '@/components/admin/NewUserDialog'
import { useRequireAdmin } from '@/lib/useRequireAdmin'
import { useAuth } from '@/components/auth/useAuth'
import { api } from '@/lib/api'
import type { UserRead } from '@/lib/types'

export default function AdminUsersPage() {
  const { ready } = useRequireAdmin()
  const { user: currentUser } = useAuth()

  const [users, setUsers] = useState<UserRead[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadUsers = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.users.list()
      setUsers(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load users')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (ready) loadUsers()
  }, [ready, loadUsers])

  if (!ready) {
    return (
      <div className="flex flex-col gap-4 py-8">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-pfl-slate-900">Users</h1>
        <NewUserDialog onCreated={loadUsers} />
      </div>

      {/* Error */}
      {error && (
        <div
          role="alert"
          className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : (
        <UsersTable
          users={users}
          currentUserId={currentUser?.id ?? ''}
          onMutate={loadUsers}
        />
      )}
    </div>
  )
}
