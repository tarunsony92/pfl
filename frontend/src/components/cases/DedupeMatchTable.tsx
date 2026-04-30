'use client'

/**
 * DedupeMatchTable — table of dedupe match results.
 *
 * Columns: match_type badge, match_score (colored), matched_customer_id, expandable details
 * Score thresholds: >= 0.9 → red, >= 0.7 → amber, < 0.7 → gray
 */

import React, { useState } from 'react'
import Link from 'next/link'
import { ChevronDownIcon, ChevronRightIcon, ShieldCheckIcon, UploadCloudIcon } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/cn'
import type { DedupeMatchRead } from '@/lib/types'

interface DedupeMatchTableProps {
  matches: DedupeMatchRead[]
  /** True when the dedupe extraction reported warnings=["no_active_snapshot"]. */
  noActiveSnapshot?: boolean
  /** Whether the current user is admin — gates the "Upload snapshot" CTA. */
  isAdmin?: boolean
}

function scoreColor(score: number): string {
  if (score >= 0.9) return 'text-red-600 font-bold'
  if (score >= 0.7) return 'text-amber-600 font-semibold'
  return 'text-pfl-slate-400'
}

function matchTypeBadgeVariant(matchType: string): 'destructive' | 'warning' | 'default' {
  switch (matchType) {
    case 'AADHAAR':
    case 'PAN':
      return 'destructive'
    case 'MOBILE':
      return 'warning'
    default:
      return 'default'
  }
}

function ExpandableDetails({ details }: { details: Record<string, unknown> }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button
        type="button"
        className="flex items-center gap-1 text-xs text-pfl-blue-700 hover:underline"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open
          ? <ChevronDownIcon className="h-3 w-3" aria-hidden="true" />
          : <ChevronRightIcon className="h-3 w-3" aria-hidden="true" />
        }
        {open ? 'Hide' : 'View'} details
      </button>
      {open && (
        <pre className="mt-2 text-xs bg-pfl-slate-50 rounded p-2 overflow-auto max-h-48 text-pfl-slate-700">
          {JSON.stringify(details, null, 2)}
        </pre>
      )}
    </div>
  )
}

export function DedupeMatchTable({
  matches,
  noActiveSnapshot = false,
  isAdmin = false,
}: DedupeMatchTableProps) {
  if (matches.length === 0) {
    if (noActiveSnapshot) {
      return (
        <div className="flex flex-col items-center gap-3 py-16 text-pfl-slate-500 text-center max-w-md mx-auto">
          <UploadCloudIcon className="h-10 w-10 text-amber-500" aria-hidden="true" />
          <p className="font-medium text-pfl-slate-700">No active dedupe snapshot</p>
          <p className="text-xs text-pfl-slate-500">
            Dedupe matching needs an active Customer_Dedupe snapshot. Without one,
            this case can&apos;t be checked against the existing customer book.
          </p>
          {isAdmin ? (
            <Link
              href="/admin/dedupe-snapshots"
              className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-pfl-blue-700 hover:underline"
            >
              Upload snapshot → /admin/dedupe-snapshots
            </Link>
          ) : (
            <p className="text-xs italic text-pfl-slate-400">
              Ask an admin to upload a snapshot.
            </p>
          )}
        </div>
      )
    }
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-pfl-slate-500">
        <ShieldCheckIcon className="h-10 w-10 opacity-40" aria-hidden="true" />
        <p className="font-medium">No dedupe matches found</p>
        <p className="text-xs text-pfl-slate-400">This applicant appears unique in the system.</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-pfl-slate-200">
      <table className="min-w-full divide-y divide-pfl-slate-200 text-sm">
        <thead className="bg-pfl-slate-50">
          <tr>
            <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Match Type</th>
            <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Score</th>
            <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Matched Customer</th>
            <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Details</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-pfl-slate-100 bg-white">
          {matches.map((match) => (
            <tr key={match.id} className="hover:bg-pfl-slate-50 transition-colors">
              <td className="px-4 py-3">
                <Badge variant={matchTypeBadgeVariant(match.match_type)}>
                  {match.match_type}
                </Badge>
              </td>
              <td className="px-4 py-3">
                <span className={cn('tabular-nums', scoreColor(match.match_score))}>
                  {(match.match_score * 100).toFixed(1)}%
                </span>
              </td>
              <td className="px-4 py-3 text-pfl-slate-700 font-mono text-xs">
                {match.matched_customer_id ?? (
                  <span className="italic text-pfl-slate-400">—</span>
                )}
              </td>
              <td className="px-4 py-3">
                <ExpandableDetails details={match.matched_details_json} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
