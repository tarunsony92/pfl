'use client'

/**
 * UsersTable — admin table for managing users.
 *
 * Columns: email, full_name, role (inline Select), is_active (toggle), mfa_enabled, created_at, actions.
 * Role cell is disabled if userRow.id === currentUser.id.
 * Active toggle cannot disable self.
 */

import React, { useState } from 'react'
import { RoleBadge } from '@/components/layout/RoleBadge'
import { Badge } from '@/components/ui/badge'
import { toast } from '@/components/ui/use-toast'
import { api } from '@/lib/api'
import { UserRoles } from '@/lib/enums'
import type { UserRead } from '@/lib/types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface UsersTableProps {
  users: UserRead[]
  currentUserId: string
  onMutate: () => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' })
  } catch {
    return iso
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function UsersTable({ users, currentUserId, onMutate }: UsersTableProps) {
  const [pendingRole, setPendingRole] = useState<string | null>(null)
  const [pendingActive, setPendingActive] = useState<string | null>(null)

  async function handleRoleChange(user: UserRead, newRole: string) {
    if (user.id === currentUserId) return
    setPendingRole(user.id)
    try {
      await api.users.updateRole(user.id, newRole)
      toast({ title: 'Role updated', description: `${user.email} is now ${newRole}.` })
      onMutate()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to update role'
      toast({ title: 'Error', description: msg, variant: 'destructive' })
    } finally {
      setPendingRole(null)
    }
  }

  async function handleActiveToggle(user: UserRead) {
    if (user.id === currentUserId) return
    const newActive = !user.is_active
    setPendingActive(user.id)
    try {
      await api.users.updateActive(user.id, newActive)
      toast({
        title: newActive ? 'User activated' : 'User deactivated',
        description: `${user.email} is now ${newActive ? 'active' : 'inactive'}.`,
      })
      onMutate()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to update status'
      toast({ title: 'Error', description: msg, variant: 'destructive' })
    } finally {
      setPendingActive(null)
    }
  }

  if (users.length === 0) {
    return (
      <div className="flex items-center justify-center py-16 text-pfl-slate-400 text-sm">
        No users found.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-pfl-slate-200">
      <table className="w-full text-sm">
        <thead className="bg-pfl-slate-50 border-b border-pfl-slate-200">
          <tr>
            <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Email</th>
            <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Full Name</th>
            <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Role</th>
            <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Active</th>
            <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">MFA</th>
            <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Created</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-pfl-slate-100">
          {users.map((user) => {
            const isSelf = user.id === currentUserId
            const roleUpdating = pendingRole === user.id
            const activeUpdating = pendingActive === user.id

            return (
              <tr
                key={user.id}
                className={`hover:bg-pfl-slate-50 transition-colors ${isSelf ? 'bg-pfl-blue-50/30' : ''}`}
              >
                {/* Email */}
                <td className="px-4 py-3 font-mono text-pfl-slate-800 text-xs">
                  {user.email}
                  {isSelf && (
                    <span className="ml-2 text-pfl-blue-600 text-xs font-normal">(you)</span>
                  )}
                </td>

                {/* Full Name */}
                <td className="px-4 py-3 text-pfl-slate-700">{user.full_name}</td>

                {/* Role — inline select (disabled for self) */}
                <td className="px-4 py-3">
                  {isSelf ? (
                    <RoleBadge role={user.role} />
                  ) : (
                    <select
                      aria-label={`Change role for ${user.email}`}
                      value={user.role}
                      disabled={roleUpdating}
                      onChange={(e) => handleRoleChange(user, e.target.value)}
                      className="rounded border border-pfl-slate-300 bg-white px-2 py-1 text-xs text-pfl-slate-900 focus:outline-none focus:ring-2 focus:ring-pfl-blue-600 disabled:opacity-50"
                    >
                      {UserRoles.map((r) => (
                        <option key={r} value={r}>
                          {r.replace(/_/g, ' ')}
                        </option>
                      ))}
                    </select>
                  )}
                </td>

                {/* Active toggle */}
                <td className="px-4 py-3">
                  <button
                    role="switch"
                    aria-checked={user.is_active}
                    aria-label={`Toggle active for ${user.email}`}
                    disabled={isSelf || activeUpdating}
                    onClick={() => handleActiveToggle(user)}
                    className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pfl-blue-600 disabled:opacity-40 disabled:cursor-not-allowed ${user.is_active ? 'bg-green-500' : 'bg-pfl-slate-300'}`}
                  >
                    <span
                      className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${user.is_active ? 'translate-x-4' : 'translate-x-1'}`}
                    />
                  </button>
                </td>

                {/* MFA */}
                <td className="px-4 py-3">
                  <Badge variant={user.mfa_enabled ? 'success' : 'outline'}>
                    {user.mfa_enabled ? 'Enabled' : 'Disabled'}
                  </Badge>
                </td>

                {/* Created at */}
                <td className="px-4 py-3 text-pfl-slate-500 text-xs">{formatDate(user.created_at)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
