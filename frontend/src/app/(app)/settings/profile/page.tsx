'use client'

/**
 * /settings/profile — User settings page.
 *
 * Sections:
 *   - Profile card (read-only info)
 *   - Change Password card
 *   - Two-Factor Authentication card
 */

import React from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { ProfileCard } from '@/components/settings/ProfileCard'
import { ChangePasswordCard } from '@/components/settings/ChangePasswordCard'
import { MFACard } from '@/components/settings/MFACard'
import { useAuth } from '@/components/auth/useAuth'

export default function ProfilePage() {
  const { user, loading, refreshUser } = useAuth()

  if (loading) {
    return (
      <div className="mx-auto max-w-2xl py-8 flex flex-col gap-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-36 w-full" />
      </div>
    )
  }

  if (!user) {
    return (
      <div
        role="alert"
        className="mx-auto max-w-2xl mt-8 rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        Unable to load user profile. Please refresh the page.
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-2xl py-8">
      <h1 className="text-2xl font-bold text-pfl-slate-900 mb-6">Settings</h1>

      <div className="flex flex-col gap-6">
        <ProfileCard user={user} />
        <ChangePasswordCard />
        <MFACard user={user} onRefresh={refreshUser} />
      </div>
    </div>
  )
}
