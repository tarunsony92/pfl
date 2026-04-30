'use client'

/**
 * /admin/dedupe-snapshots — Admin Dedupe Snapshots management page.
 *
 * Admin-only (useRequireAdmin guard).
 * Shows DedupeSnapshotsTable + UploadSnapshotDialog.
 */

import React, { useCallback, useEffect, useState } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { DedupeSnapshotsTable } from '@/components/admin/DedupeSnapshotsTable'
import { UploadSnapshotDialog } from '@/components/admin/UploadSnapshotDialog'
import { useRequireAdmin } from '@/lib/useRequireAdmin'
import { api } from '@/lib/api'
import type { DedupeSnapshotRead } from '@/lib/types'

export default function AdminDedupeSnapshotsPage() {
  const { ready } = useRequireAdmin()

  const [snapshots, setSnapshots] = useState<DedupeSnapshotRead[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadSnapshots = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.dedupeSnapshots.list()
      setSnapshots(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load snapshots')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (ready) loadSnapshots()
  }, [ready, loadSnapshots])

  if (!ready) {
    return (
      <div className="flex flex-col gap-4 py-8">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-pfl-slate-900">Dedupe Snapshots</h1>
        <UploadSnapshotDialog onUploaded={loadSnapshots} />
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
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : (
        <DedupeSnapshotsTable snapshots={snapshots} />
      )}
    </div>
  )
}
