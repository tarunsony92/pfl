'use client'

/**
 * AutoRunModal — popover-style modal showing the in-flight / completed
 * 7-level auto-run for a single case. Driven by AutoRunProvider.
 */

import React from 'react'
import Link from 'next/link'
import useSWR from 'swr'
import { AlertTriangleIcon } from 'lucide-react'
import { cn } from '@/lib/cn'
import { cases as casesApi } from '@/lib/api'
import { useAuth } from '@/components/auth/useAuth'
import { useAutoRun, type AutoRunStep } from './AutoRunProvider'

function StepCircle({ status }: { status: AutoRunStep['status'] }) {
  if (status === 'done') {
    return (
      <span
        className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-emerald-600 text-white"
        aria-label="done"
      >
        <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden>
          <path
            d="M3 8l3 3 7-7"
            stroke="currentColor"
            strokeWidth="2"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    )
  }
  if (status === 'failed') {
    return (
      <span
        className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-red-600 text-white text-xs font-bold"
        aria-label="failed"
      >
        ×
      </span>
    )
  }
  if (status === 'running') {
    return (
      <span
        className="inline-flex h-6 w-6 items-center justify-center rounded-full border-2 border-pfl-blue-500 border-t-transparent animate-spin"
        aria-label="running"
      />
    )
  }
  return (
    <span
      className="inline-flex h-6 w-6 items-center justify-center rounded-full border-2 border-pfl-slate-300"
      aria-label="pending"
    />
  )
}

export function AutoRunModal() {
  const { state, closeModal, minimize, dismiss, resume, getStatus } = useAutoRun()
  const run = state.modalCaseId ? state.runs[state.modalCaseId] : null
  if (!run) return null

  const total = run.steps.length
  const completed = run.steps.filter(
    (s) => s.status === 'done' || s.status === 'failed',
  ).length
  const pct = total === 0 ? 0 : Math.round((completed / total) * 100)
  const anyFailed = run.steps.some((s) => s.status === 'failed')
  const isDone = !!run.completedAt
  const status = getStatus(run.caseId)
  const isBlocked = status === 'blocked'
  const anyPausedStep = run.steps.find(
    (s) =>
      s.status === 'failed' &&
      (s.errorMessage?.includes('Interrupted') ?? false),
  )

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="autorun-title"
    >
      <div
        className="w-[92%] max-w-md rounded-lg border border-pfl-slate-200 bg-white shadow-2xl"
        data-testid="autorun-modal"
      >
        {/* Header */}
        <div className="px-5 py-4 border-b border-pfl-slate-200">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2
                id="autorun-title"
                className="text-base font-semibold text-pfl-slate-900"
              >
                Auto-running credit pipeline
              </h2>
              <p className="text-xs text-pfl-slate-500 mt-0.5 truncate">
                {run.applicantName ?? 'Unknown applicant'}
                {run.loanId && <span className="font-mono"> · #{run.loanId}</span>}
              </p>
            </div>
            <button
              type="button"
              onClick={closeModal}
              className="text-pfl-slate-400 hover:text-pfl-slate-700 text-lg leading-none"
              aria-label="Close"
            >
              ×
            </button>
          </div>

          {/* Overall progress bar */}
          <div className="mt-3">
            <div className="flex items-center justify-between text-xs text-pfl-slate-600 mb-1">
              <span className="font-semibold">
                {isBlocked
                  ? 'Paused — waiting on required documents'
                  : isDone
                  ? anyFailed
                    ? 'Finished with errors'
                    : 'All steps complete'
                  : `${completed} of ${total} steps`}
              </span>
              <span className="font-mono tabular-nums">
                {isBlocked ? '—' : `${pct}%`}
              </span>
            </div>
            <div className="h-2 rounded-full bg-pfl-slate-100 overflow-hidden">
              <div
                className={cn(
                  'h-full transition-all',
                  isBlocked
                    ? 'bg-amber-500'
                    : isDone
                    ? anyFailed
                      ? 'bg-amber-500'
                      : 'bg-emerald-600'
                    : 'bg-pfl-blue-600',
                )}
                style={{ width: isBlocked ? '100%' : `${pct}%` }}
                aria-valuenow={pct}
                aria-valuemin={0}
                aria-valuemax={100}
                role="progressbar"
              />
            </div>
          </div>
        </div>

        {/* Blocked-by-missing-docs banner. Replaces the per-step list because
            none of the levels actually ran; surfacing them as "Queued" on top
            of an error banner would be noise. */}
        {isBlocked ? (
          <MissingDocsBanner caseId={run.caseId} message={run.blockMessage} />
        ) : (
          <ul className="px-5 py-4 flex flex-col gap-2.5">
            {run.steps.map((s) => (
              <li key={s.key} className="flex items-start gap-3">
                <StepCircle status={s.status} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-pfl-slate-900">
                    {s.label}
                  </div>
                  <div className="text-[11.5px] text-pfl-slate-500">
                    {s.status === 'pending' && 'Queued'}
                    {s.status === 'running' && 'Running…'}
                    {s.status === 'done' && 'Completed'}
                    {s.status === 'failed' && (s.errorMessage || 'Failed')}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}

        {/* Footer actions */}
        <div className="px-5 py-3 border-t border-pfl-slate-200 flex items-center gap-2 justify-end">
          {!isDone && anyPausedStep && (
            <button
              type="button"
              onClick={() => resume(run.caseId)}
              className="rounded bg-amber-600 hover:bg-amber-700 text-white px-3 py-1.5 text-xs font-semibold"
            >
              Resume
            </button>
          )}
          {!isDone && (
            <button
              type="button"
              onClick={() => minimize(run.caseId)}
              className="rounded border border-pfl-slate-300 text-pfl-slate-700 hover:bg-pfl-slate-50 px-3 py-1.5 text-xs font-semibold"
            >
              Minimize — keep running
            </button>
          )}
          {isDone && (
            <button
              type="button"
              onClick={() => dismiss(run.caseId)}
              className="rounded bg-pfl-slate-900 hover:bg-pfl-slate-800 text-white px-3 py-1.5 text-xs font-semibold"
            >
              Dismiss
            </button>
          )}
          {isDone && (
            <button
              type="button"
              onClick={() => minimize(run.caseId)}
              className="rounded border border-pfl-slate-300 text-pfl-slate-700 hover:bg-pfl-slate-50 px-3 py-1.5 text-xs font-semibold"
            >
              Keep in dock
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * Pulls the case's checklist validation result and lists the missing docs in
 * the modal body. The auto-run runner already detected the same condition and
 * marked the run blocked; this component is purely presentation + remediation
 * CTA. Errors fall back to the generic block message rather than blanking
 * the whole modal.
 */
function MissingDocsBanner({
  caseId,
  message,
}: {
  caseId: string
  message?: string
}) {
  const { user } = useAuth()
  const isMD = user?.role === 'admin' || user?.role === 'ceo'
  const { data, isLoading, mutate } = useSWR(
    ['autorun-blocked-checklist', caseId],
    () => casesApi.checklistValidation(caseId),
    { revalidateOnFocus: false },
  )

  const missing = data?.missing_docs ?? []

  return (
    <div className="px-5 py-4">
      <div className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3">
        <div className="flex items-start gap-2">
          <AlertTriangleIcon
            className="h-4 w-4 text-amber-700 shrink-0 mt-0.5"
            aria-hidden
          />
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-amber-900">
              Auto-run is paused — required documents missing
            </p>
            <p className="text-[12px] text-amber-900/90 mt-0.5">
              {message ??
                'Upload the documents listed below from the case page, then click "Auto-run all levels" again.'}
              {isMD && (
                <>
                  {' '}As MD you can also waive a requirement with a written
                  justification.
                </>
              )}
            </p>
          </div>
        </div>

        {isLoading ? (
          <p className="mt-3 text-[12px] text-amber-900/80 italic">
            Loading checklist…
          </p>
        ) : missing.length === 0 ? (
          <p className="mt-3 text-[12px] text-amber-900/80 italic">
            Checklist looks clean now — try the auto-run again.
          </p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2 text-[12px] text-amber-950">
            {missing.map((m, i) => {
              const docType = String(m.doc_type ?? `doc-${i}`)
              const reason = String(m.reason ?? '')
              return (
                <MissingDocRow
                  key={docType}
                  caseId={caseId}
                  docType={docType}
                  reason={reason}
                  isMD={isMD}
                  onWaived={() => mutate()}
                />
              )
            })}
          </ul>
        )}

        <div className="mt-3 flex items-center gap-3">
          <Link
            href={`/cases/${caseId}#artifacts`}
            className="inline-flex items-center rounded bg-amber-600 hover:bg-amber-700 text-white px-3 py-1.5 text-[12px] font-semibold"
          >
            Open case to upload docs
          </Link>
          <span className="text-[11px] text-amber-900/70">
            Once uploaded, click <b>Auto-run all levels</b> on the case page to
            retry.
          </span>
        </div>
      </div>
    </div>
  )
}

function MissingDocRow({
  caseId,
  docType,
  reason,
  isMD,
  onWaived,
}: {
  caseId: string
  docType: string
  reason: string
  isMD: boolean
  onWaived: () => void
}) {
  const [editing, setEditing] = React.useState(false)
  const [justification, setJustification] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  async function submit() {
    if (justification.trim().length < 4) {
      setError('Justification must be at least 4 characters.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await casesApi.checklistWaive(caseId, docType, justification.trim())
      setEditing(false)
      setJustification('')
      onWaived()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Waive failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="flex flex-col gap-1.5 leading-snug">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-[10.5px] uppercase tracking-wide text-amber-800 min-w-[120px]">
          {docType}
        </span>
        <span className="flex-1">{reason}</span>
        {isMD && !editing && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="text-[11px] font-semibold text-amber-800 hover:text-amber-900 underline shrink-0"
          >
            Waive
          </button>
        )}
      </div>
      {editing && (
        <div className="ml-[128px] flex flex-col gap-1.5 rounded border border-amber-300 bg-white/60 px-2.5 py-2">
          <label className="text-[10.5px] uppercase tracking-wide font-semibold text-amber-800">
            MD waiver justification
          </label>
          <textarea
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
            placeholder="Why is it acceptable to proceed without this document?"
            rows={2}
            disabled={busy}
            className="resize-none rounded border border-amber-300 bg-white px-2 py-1 text-[12px] text-pfl-slate-900 focus:outline-none focus:ring-1 focus:ring-amber-500"
          />
          {error && (
            <p className="text-[11px] text-red-700">{error}</p>
          )}
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={submit}
              className="rounded bg-amber-700 hover:bg-amber-800 disabled:opacity-50 text-white px-2.5 py-1 text-[11px] font-semibold"
            >
              {busy ? 'Waiving…' : 'Confirm waiver'}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setEditing(false)
                setJustification('')
                setError(null)
              }}
              className="text-[11px] text-amber-800 hover:text-amber-900"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </li>
  )
}
