'use client'

/**
 * NotificationsBell — Topbar alert centre.
 *
 * Polls GET /notifications every 60 s, shows the count in a red dot on the
 * bell, and opens a dropdown that lists every actionable issue: missing
 * documents, extractor failures, critical extraction warnings, CAM
 * discrepancies blocking Verification 2. Each notification carries a
 * `case_id` + `action_tab` so clicking jumps the user straight to the fix.
 *
 * Backend: backend/app/services/notifications.py
 * Route:   GET /notifications
 */

import React, { useState } from 'react'
import Link from 'next/link'
import {
  AlertCircleIcon,
  AlertTriangleIcon,
  BellIcon,
  FileWarningIcon,
  ScrollTextIcon,
  XIcon,
} from 'lucide-react'
import useSWR from 'swr'
import { api, type NotificationRead } from '@/lib/api'
import { cn } from '@/lib/cn'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

const POLL_MS = 60_000

function kindIcon(kind: NotificationRead['kind']) {
  const cls = 'h-4 w-4 shrink-0'
  switch (kind) {
    case 'MISSING_DOCS':
      return <FileWarningIcon className={cls} aria-hidden="true" />
    case 'EXTRACTOR_FAILED':
      return <AlertCircleIcon className={cls} aria-hidden="true" />
    case 'EXTRACTION_CRITICAL_WARNING':
      return <AlertTriangleIcon className={cls} aria-hidden="true" />
    case 'DISCREPANCY_BLOCKING':
      return <ScrollTextIcon className={cls} aria-hidden="true" />
    default:
      return <BellIcon className={cls} aria-hidden="true" />
  }
}

function relativeTime(iso: string): string {
  try {
    const t = new Date(iso).getTime()
    const diff = Date.now() - t
    if (diff < 60_000) return 'just now'
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
    if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
    return `${Math.floor(diff / 86_400_000)}d ago`
  } catch {
    return ''
  }
}

export function NotificationsBell() {
  const [open, setOpen] = useState(false)
  const { data, error, isLoading } = useSWR(
    '/notifications',
    () => api.notifications.list(),
    { refreshInterval: POLL_MS, revalidateOnFocus: true },
  )

  const critical = data?.critical ?? 0
  const warning = data?.warning ?? 0
  const total = data?.total ?? 0

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger
        className="relative inline-flex h-9 w-9 items-center justify-center rounded-full text-pfl-slate-600 hover:bg-pfl-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pfl-blue-600"
        aria-label={total > 0 ? `${total} notifications` : 'Notifications'}
        data-testid="notifications-bell"
      >
        <BellIcon className="h-5 w-5" aria-hidden="true" />
        {total > 0 && (
          <span
            className={cn(
              'absolute -top-0.5 -right-0.5 inline-flex min-w-[18px] items-center justify-center rounded-full px-1 text-[10px] font-bold text-white',
              critical > 0 ? 'bg-red-600' : 'bg-amber-500',
            )}
            data-testid="notifications-badge"
          >
            {total > 99 ? '99+' : total}
          </span>
        )}
      </DropdownMenuTrigger>

      <DropdownMenuContent
        align="end"
        className="w-[380px] max-h-[70vh] overflow-y-auto p-0"
        data-testid="notifications-menu"
      >
        <div className="sticky top-0 bg-white border-b border-pfl-slate-200 px-4 py-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-pfl-slate-900">Notifications</p>
            <p className="text-xs text-pfl-slate-500">
              {critical > 0 && (
                <span className="text-red-700 font-semibold">{critical} critical</span>
              )}
              {critical > 0 && warning > 0 && <span> · </span>}
              {warning > 0 && (
                <span className="text-amber-700 font-semibold">{warning} warning</span>
              )}
              {total === 0 && !isLoading && <span>All clear</span>}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setOpen(false)}
            aria-label="Close notifications"
            className="rounded p-1 hover:bg-pfl-slate-100"
          >
            <XIcon className="h-4 w-4 text-pfl-slate-500" />
          </button>
        </div>

        {isLoading && (
          <div className="px-4 py-6 text-xs text-pfl-slate-500 italic">Loading…</div>
        )}
        {error && (
          <div className="px-4 py-6 text-xs text-red-700">
            Failed to load notifications.
          </div>
        )}
        {!isLoading && !error && total === 0 && (
          <div
            className="px-4 py-8 text-xs text-pfl-slate-500 italic text-center"
            data-testid="notifications-empty"
          >
            No open issues across your cases. 🎉
          </div>
        )}

        {data?.notifications.map((n) => (
          <Link
            key={n.id}
            href={`/cases/${n.case_id}?tab=${n.action_tab}`}
            onClick={() => setOpen(false)}
            className={cn(
              'block px-4 py-3 text-left hover:bg-pfl-slate-50 border-b border-pfl-slate-100 last:border-0',
              n.severity === 'CRITICAL' ? 'bg-red-50/40' : 'bg-white',
            )}
            data-testid={`notification-${n.id}`}
          >
            <div className="flex items-start gap-2">
              <span
                className={cn(
                  'mt-0.5',
                  n.severity === 'CRITICAL' ? 'text-red-700' : 'text-amber-700',
                )}
              >
                {kindIcon(n.kind)}
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-pfl-slate-900 break-words">
                  {n.title}
                </p>
                <p className="mt-0.5 text-xs text-pfl-slate-600 line-clamp-3">
                  {n.description}
                </p>
                <div className="mt-1.5 flex items-center justify-between text-[10px] text-pfl-slate-500">
                  <span className="font-mono">
                    {n.applicant_name ?? n.loan_id}
                  </span>
                  <span>{relativeTime(n.created_at)}</span>
                </div>
                <p className="mt-1 text-[11px] font-semibold text-pfl-blue-700">
                  {n.action_label} →
                </p>
              </div>
            </div>
          </Link>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
