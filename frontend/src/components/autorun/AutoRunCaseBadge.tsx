'use client'

/**
 * AutoRunCaseBadge — tiny progress ring + tick to sit beside a case row's
 * "View" button in the cases table. Null when idle.
 */

import React from 'react'
import { useAutoRun } from './AutoRunProvider'
import { CircularRing } from './AutoRunDock'

export function AutoRunCaseBadge({ caseId }: { caseId: string }) {
  const { getStatus, getProgress, openModal, state } = useAutoRun()
  const status = getStatus(caseId)
  if (status === 'idle') return null
  const progress = getProgress(caseId) ?? 0
  const pct = Math.round(progress * 100)

  const label =
    status === 'running'
      ? `Auto-run ${pct}%`
      : status === 'done'
      ? 'Pipeline complete'
      : status === 'done_with_errors'
      ? 'Finished with errors'
      : status === 'blocked'
      ? 'Missing required documents'
      : 'All steps failed'

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    // Re-surface the modal for this case (even if it was minimized).
    const run = state.runs[caseId]
    if (run) openModal(caseId)
  }

  if (status === 'done') {
    return (
      <button
        type="button"
        onClick={handleClick}
        className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700 px-2 py-0.5 text-[10.5px] font-semibold hover:bg-emerald-100"
        title={label}
      >
        <svg width="10" height="10" viewBox="0 0 16 16" aria-hidden>
          <path
            d="M3 8l3 3 7-7"
            stroke="currentColor"
            strokeWidth="2.5"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        ready
      </button>
    )
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      className="inline-flex items-center"
      title={label}
    >
      <CircularRing pct={pct} status={status} size={24} />
    </button>
  )
}
