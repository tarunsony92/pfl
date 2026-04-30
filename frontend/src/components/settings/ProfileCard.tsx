'use client'

/**
 * ProfileCard — displays read-only user profile info.
 */

import React from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { RoleBadge } from '@/components/layout/RoleBadge'
import type { UserRead } from '@/lib/types'

interface ProfileCardProps {
  user: UserRead
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 py-3 border-b border-pfl-slate-100 last:border-0">
      <span className="text-xs font-medium uppercase tracking-wide text-pfl-slate-500">{label}</span>
      <span className="text-sm text-pfl-slate-900">{children}</span>
    </div>
  )
}

function formatDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

export function ProfileCard({ user }: ProfileCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Profile</CardTitle>
      </CardHeader>
      <CardContent>
        <Row label="Email">
          <span className="font-mono text-pfl-slate-800">{user.email}</span>
        </Row>
        <Row label="Full name">{user.full_name || <span className="italic text-pfl-slate-400">—</span>}</Row>
        <Row label="Role">
          <RoleBadge role={user.role} />
        </Row>
        <Row label="Member since">{formatDateTime(user.created_at)}</Row>
        <Row label="Last login">
          {user.last_login_at ? formatDateTime(user.last_login_at) : (
            <span className="italic text-pfl-slate-400">Never</span>
          )}
        </Row>
        <Row label="Account status">
          <span className={user.is_active ? 'text-green-700 font-medium' : 'text-red-600 font-medium'}>
            {user.is_active ? 'Active' : 'Inactive'}
          </span>
        </Row>
      </CardContent>
    </Card>
  )
}
