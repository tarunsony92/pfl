'use client'

/**
 * DedupeSnapshotsTable — shows list of dedupe snapshots.
 *
 * Columns: filename (from upload_key), uploaded_by, uploaded_at, row_count, is_active, download.
 */

import React from 'react'
import { DownloadIcon } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { DedupeSnapshotRead } from '@/lib/types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DedupeSnapshotsTableProps {
  snapshots: DedupeSnapshotRead[]
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

function shortId(id: string): string {
  return id.slice(0, 8) + '…'
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function DedupeSnapshotsTable({ snapshots }: DedupeSnapshotsTableProps) {
  if (snapshots.length === 0) {
    return (
      <div
        data-testid="empty-state"
        className="flex flex-col items-center justify-center py-16 gap-3 text-pfl-slate-400"
      >
        <p className="text-sm">No dedupe snapshots uploaded yet.</p>
        <p className="text-xs">Upload an xlsx file to get started.</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-pfl-slate-200">
      <table className="w-full text-sm">
        <thead className="bg-pfl-slate-50 border-b border-pfl-slate-200">
          <tr>
            <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Snapshot ID</th>
            <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Uploaded By</th>
            <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Uploaded At</th>
            <th scope="col" className="px-4 py-3 text-right font-semibold text-pfl-slate-700">Rows</th>
            <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Status</th>
            <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Download</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-pfl-slate-100">
          {snapshots.map((snap) => (
            <tr
              key={snap.id}
              className={`hover:bg-pfl-slate-50 transition-colors ${snap.is_active ? 'bg-green-50/40' : ''}`}
            >
              {/* Snapshot ID */}
              <td className="px-4 py-3 font-mono text-xs text-pfl-slate-700">
                {shortId(snap.id)}
              </td>

              {/* Uploaded by */}
              <td className="px-4 py-3 font-mono text-xs text-pfl-slate-500">
                {shortId(snap.uploaded_by)}
              </td>

              {/* Uploaded at */}
              <td className="px-4 py-3 text-pfl-slate-600 text-xs">
                {formatDateTime(snap.uploaded_at)}
              </td>

              {/* Row count */}
              <td className="px-4 py-3 text-right tabular-nums text-pfl-slate-700">
                {snap.row_count.toLocaleString()}
              </td>

              {/* Active status */}
              <td className="px-4 py-3">
                <Badge variant={snap.is_active ? 'success' : 'outline'}>
                  {snap.is_active ? 'Active' : 'Inactive'}
                </Badge>
              </td>

              {/* Download */}
              <td className="px-4 py-3">
                {snap.download_url ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    asChild
                  >
                    <a
                      href={snap.download_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`Download snapshot ${shortId(snap.id)}`}
                    >
                      <DownloadIcon className="h-3.5 w-3.5 mr-1" aria-hidden="true" />
                      Download
                    </a>
                  </Button>
                ) : (
                  <span className="text-xs text-pfl-slate-400">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
