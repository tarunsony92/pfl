'use client'

/**
 * AutorunGateModal — pre-auto-run completeness check.
 *
 * Shown when the user clicks "Auto-run all levels" on a case that is
 * missing one or more required artefacts. Two paths:
 *
 *   • Upload now — closes the modal and scrolls to the upload area; the
 *     auto-run is NOT started, so the user can drop the missing files
 *     and re-click the trigger when ready.
 *
 *   • Skip and continue — POSTs an `IncompleteAutorunLog` row capturing
 *     {user, case, missing_subtypes, optional reason}, THEN starts the
 *     auto-run. The defaulter row surfaces in /admin/incomplete-autoruns
 *     so admins can see who is bypassing the gate.
 */

import React, { useState } from 'react'
import { AlertTriangleIcon, UploadIcon, XIcon } from 'lucide-react'
import { cn } from '@/lib/cn'
import { incompleteAutoruns, type MissingArtifact } from '@/lib/api'

interface Props {
  caseId: string
  loanId: string | null
  missing: MissingArtifact[]
  onUploadNow: () => void
  onSkip: () => void
  onClose: () => void
}

export function AutorunGateModal({
  caseId,
  loanId,
  missing,
  onUploadNow,
  onSkip,
  onClose,
}: Props) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSkip() {
    setBusy(true)
    setError(null)
    try {
      await incompleteAutoruns.recordIncompleteAutorun(caseId, {
        missing_subtypes: missing.map((m) => m.subtype),
        reason: reason.trim() || null,
      })
      onSkip()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to record log entry')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose()
      }}
    >
      <div className="relative w-[min(560px,92vw)] rounded-lg bg-white shadow-xl border border-pfl-slate-200">
        <div className="flex items-start gap-3 border-b border-pfl-slate-200 px-5 py-4">
          <AlertTriangleIcon className="h-5 w-5 text-amber-700 mt-0.5 flex-shrink-0" />
          <div className="flex-1">
            <h2 className="text-base font-semibold text-pfl-slate-900">
              {missing.length} required file{missing.length === 1 ? '' : 's'} missing
            </h2>
            <p className="mt-0.5 text-[12.5px] text-pfl-slate-600">
              Loan{' '}
              <span className="font-mono font-semibold">
                {loanId || caseId.slice(0, 8) + '…'}
              </span>{' '}
              has not yet been uploaded with the canonical PFL bundle. Upload the
              files below, or skip and proceed — your name will be logged in the
              admin "Incomplete Auto-Runs" tab.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded p-1 text-pfl-slate-500 hover:bg-pfl-slate-100"
            aria-label="Close"
          >
            <XIcon className="h-4 w-4" />
          </button>
        </div>

        <div className="px-5 py-4 max-h-[40vh] overflow-y-auto">
          <ul className="flex flex-col gap-2 text-[13px]">
            {missing.map((m) => (
              <li
                key={m.subtype}
                className="flex items-start gap-2 rounded border border-amber-200 bg-amber-50/60 px-2.5 py-2"
              >
                <span className="mt-0.5 inline-block h-1.5 w-1.5 rounded-full bg-amber-600 flex-shrink-0" />
                <div className="flex-1">
                  <div className="font-medium text-pfl-slate-900">{m.label}</div>
                  <div className="font-mono text-[10.5px] text-pfl-slate-500">
                    {m.subtype}
                    {m.optional_alternatives && m.optional_alternatives.length > 0 && (
                      <span> — accepts: {m.optional_alternatives.join(' / ')}</span>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>

          <label className="mt-4 block">
            <span className="block text-[12px] font-medium text-pfl-slate-700">
              Reason for skipping (optional, recorded in the audit log)
            </span>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              disabled={busy}
              rows={2}
              maxLength={500}
              placeholder="e.g. files will follow on email, customer is offline, …"
              className="mt-1 w-full rounded border border-pfl-slate-300 bg-white px-2.5 py-1.5 text-[12.5px] text-pfl-slate-800 placeholder:text-pfl-slate-400 focus:outline-none focus:ring-2 focus:ring-pfl-blue-500"
            />
          </label>

          {error && (
            <div className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-800">
              {error}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-pfl-slate-200 px-5 py-3">
          <button
            type="button"
            onClick={onUploadNow}
            disabled={busy}
            className={cn(
              'inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-semibold border transition-colors',
              'bg-pfl-blue-800 text-white hover:bg-pfl-blue-900 border-transparent',
              busy && 'opacity-60 cursor-not-allowed',
            )}
          >
            <UploadIcon className="h-3.5 w-3.5" aria-hidden />
            Upload missing files
          </button>
          <button
            type="button"
            onClick={handleSkip}
            disabled={busy}
            className={cn(
              'inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-semibold border transition-colors',
              'border-amber-600 text-amber-700 hover:bg-amber-50',
              busy && 'opacity-60 cursor-not-allowed',
            )}
          >
            {busy ? 'Logging…' : 'Skip and continue auto-run'}
          </button>
        </div>
      </div>
    </div>
  )
}
