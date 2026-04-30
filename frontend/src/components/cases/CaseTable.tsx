'use client'

/**
 * CaseTable — responsive table of cases with pagination.
 *
 * Props:
 *   cases        — rows to display
 *   isLoading    — show Skeleton rows
 *   total        — total count (for pagination)
 *   limit        — page size
 *   offset       — current offset
 *   onPageChange — called with new offset
 *   onClearFilters — called when "Clear filters" CTA in empty state is clicked
 */

import React from 'react'
import Link from 'next/link'
import { InboxIcon } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { StageBadge } from './StageBadge'
import { AutoRunCaseBadge } from '@/components/autorun/AutoRunCaseBadge'
import { DeletionRowAction } from '@/components/cases/actions/DeletionRowAction'
import { DownloadFinalReportButton } from '@/components/cases/actions/DownloadFinalReportButton'
import type { CaseRead } from '@/lib/types'
import type { CaseStage } from '@/lib/enums'

interface CaseTableProps {
  cases: CaseRead[]
  isLoading: boolean
  total: number
  limit: number
  offset: number
  onPageChange: (newOffset: number) => void
  onClearFilters?: () => void
  /** Map of user id → full_name for "Uploaded by" column. */
  userMap?: Record<string, string>
  /** Refetch the list after a row-level mutation (eg. delete approve). */
  onCaseChanged?: () => void
}

function formatDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    })
  } catch {
    return iso
  }
}

const SKELETON_ROWS = 5

export function CaseTable({
  cases,
  isLoading,
  total,
  limit,
  offset,
  onPageChange,
  onClearFilters,
  userMap = {},
  onCaseChanged,
}: CaseTableProps) {
  const currentPage = Math.floor(offset / limit) + 1
  const totalPages = Math.max(1, Math.ceil(total / limit))

  const hasPrev = offset > 0
  const hasNext = offset + limit < total

  return (
    <div className="flex flex-col gap-4">
      {/* Scrollable table wrapper */}
      <div className="overflow-x-auto rounded-lg border border-pfl-slate-200">
        <table className="min-w-full divide-y divide-pfl-slate-200 text-sm">
          <thead className="bg-pfl-slate-50">
            <tr>
              <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Loan ID</th>
              <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Applicant</th>
              <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Stage</th>
              <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Uploaded by</th>
              <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Uploaded at</th>
              <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Actions</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-pfl-slate-100 bg-white">
            {isLoading ? (
              // Loading skeleton rows
              Array.from({ length: SKELETON_ROWS }).map((_, i) => (
                <tr key={i}>
                  {Array.from({ length: 6 }).map((_, j) => (
                    <td key={j} className="px-4 py-3">
                      <Skeleton className="h-4 w-full" />
                    </td>
                  ))}
                </tr>
              ))
            ) : cases.length === 0 ? (
              // Empty state
              <tr>
                <td colSpan={6} className="px-4 py-16 text-center">
                  <div className="flex flex-col items-center gap-3 text-pfl-slate-500">
                    <InboxIcon className="h-10 w-10 opacity-40" aria-hidden="true" />
                    <p className="font-medium">No cases match your filters</p>
                    {onClearFilters && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={onClearFilters}
                        data-testid="empty-clear-filters"
                      >
                        Clear filters
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            ) : (
              cases.map((row) => (
                <tr key={row.id} className="hover:bg-pfl-blue-50 transition-colors">
                  <td className="px-4 py-3 font-mono text-xs font-medium text-pfl-slate-900">
                    {row.loan_id}
                  </td>
                  <td className="px-4 py-3 text-pfl-slate-700">
                    {row.applicant_name ?? <span className="italic text-pfl-slate-400">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    <StageBadge stage={row.current_stage as CaseStage} />
                  </td>
                  <td className="px-4 py-3 text-pfl-slate-600 text-xs">
                    {userMap[row.uploaded_by] ?? (
                      <span className="font-mono">{row.uploaded_by.slice(0, 8)}…</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-pfl-slate-600 text-xs whitespace-nowrap">
                    {formatDateTime(row.uploaded_at)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/cases/${row.id}`}
                        className="inline-flex items-center rounded px-3 py-1.5 text-xs font-semibold text-pfl-blue-700 border border-pfl-blue-700 hover:bg-pfl-blue-50 transition-colors"
                      >
                        View
                      </Link>
                      <AutoRunCaseBadge caseId={row.id} />
                      <DownloadFinalReportButton
                        caseId={row.id}
                        openIssueCount={row.open_issue_count ?? null}
                      />
                      <DeletionRowAction
                        caseData={row}
                        onChanged={onCaseChanged}
                      />
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {!isLoading && (cases.length > 0 || total > 0) && (
        <div className="flex items-center justify-between px-1">
          <span className="text-xs text-pfl-slate-500">
            {total === 0
              ? 'No results'
              : `Showing ${offset + 1}–${Math.min(offset + limit, total)} of ${total}`}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={!hasPrev}
              onClick={() => onPageChange(Math.max(0, offset - limit))}
              aria-label="Previous page"
            >
              Prev
            </Button>
            <span className="text-xs text-pfl-slate-600 tabular-nums">
              Page {currentPage} of {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={!hasNext}
              onClick={() => onPageChange(offset + limit)}
              aria-label="Next page"
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
