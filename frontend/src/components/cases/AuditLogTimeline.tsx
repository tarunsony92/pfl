'use client'

/**
 * AuditLogTimeline — most-recent-first timeline of audit log entries.
 *
 * Each entry: timestamp, actor, action, expandable before/after diff.
 */

import React, { useState } from 'react'
import { ScrollTextIcon, ChevronDownIcon, ChevronRightIcon } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import type { AuditLogRead } from '@/lib/types'

interface AuditLogTimelineProps {
  entries: AuditLogRead[]
  isLoading?: boolean
}

/** Make action keys readable */
function friendlyAction(action: string): string {
  return action
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function DiffSection({ label, data }: { label: string; data: Record<string, unknown> | null }) {
  if (!data) return null
  return (
    <div>
      <p className="text-xs font-semibold text-pfl-slate-500 mb-1">{label}</p>
      <pre className="text-xs bg-pfl-slate-50 rounded p-2 overflow-auto max-h-40 text-pfl-slate-700">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  )
}

function AuditEntry({ entry }: { entry: AuditLogRead }) {
  const [open, setOpen] = useState(false)
  const hasDiff = entry.before_json != null || entry.after_json != null
  const actor = entry.actor_user_id
    ? entry.actor_user_id.slice(0, 8) + '…'
    : 'system'

  return (
    <li className="relative pl-6 before:absolute before:left-2 before:top-2 before:h-2 before:w-2 before:rounded-full before:bg-pfl-blue-400 before:content-['']">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-pfl-slate-900">{friendlyAction(entry.action)}</p>
          <p className="text-xs text-pfl-slate-500 mt-0.5">
            {actor} &middot;{' '}
            {new Date(entry.created_at).toLocaleString(undefined, {
              dateStyle: 'medium',
              timeStyle: 'short',
            })}
          </p>
        </div>
        {hasDiff && (
          <button
            type="button"
            className="mt-0.5 flex items-center gap-1 text-xs text-pfl-blue-700 hover:underline shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pfl-blue-600 rounded"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-label={open ? 'Hide diff details' : 'Show diff details'}
          >
            {open
              ? <ChevronDownIcon className="h-3 w-3" aria-hidden="true" />
              : <ChevronRightIcon className="h-3 w-3" aria-hidden="true" />
            }
            Diff
          </button>
        )}
      </div>

      {open && hasDiff && (
        <div className="mt-2 flex flex-col gap-2">
          <DiffSection label="Before" data={entry.before_json} />
          <DiffSection label="After" data={entry.after_json} />
        </div>
      )}
    </li>
  )
}

export function AuditLogTimeline({ entries, isLoading }: AuditLogTimelineProps) {
  if (isLoading) {
    return (
      <div className="flex flex-col gap-3" data-testid="audit-skeleton">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    )
  }

  if (entries.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-pfl-slate-500">
        <ScrollTextIcon className="h-10 w-10 opacity-40" aria-hidden="true" />
        <p className="font-medium">No audit log entries found</p>
      </div>
    )
  }

  // Sort most recent first
  const sorted = [...entries].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  )

  return (
    <ul className="flex flex-col gap-4 border-l-2 border-pfl-slate-200 pl-2 ml-2">
      {sorted.map((entry) => (
        <AuditEntry key={entry.id} entry={entry} />
      ))}
    </ul>
  )
}
