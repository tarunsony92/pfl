'use client'

/**
 * AutoRunTrigger — header button that kicks off the 7-level client-side
 * auto-run for a case. Double duty: starts a new run, or re-opens the modal
 * / flags status when a run is already in flight / done.
 */

import React, { useState } from 'react'
import {
  PlayIcon,
  CheckCircleIcon,
  AlertTriangleIcon,
  RefreshCwIcon,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { useAutoRun } from './AutoRunProvider'
import { CircularRing } from './AutoRunDock'
import { AutorunGateModal } from './AutorunGateModal'
import { incompleteAutoruns, type MissingArtifact } from '@/lib/api'

export function AutoRunTrigger({
  caseId,
  loanId,
  applicantName,
}: {
  caseId: string
  loanId: string | null
  applicantName: string | null
}) {
  const { startAutoRun, rerunAll, openModal, getStatus, getProgress } = useAutoRun()
  const status = getStatus(caseId)
  const progress = getProgress(caseId) ?? 0
  const pct = Math.round(progress * 100)

  // Pre-auto-run completeness gate. When the user clicks Run on an idle
  // case, we first ask the backend which required artefacts are missing.
  // Empty list → run as before; non-empty → render AutorunGateModal so
  // the user can either upload the missing files or skip + log.
  const [gateMissing, setGateMissing] = useState<MissingArtifact[] | null>(null)
  const [gateChecking, setGateChecking] = useState(false)

  async function checkGateAndStart(forceRerun: boolean) {
    setGateChecking(true)
    try {
      const r = await incompleteAutoruns.missingArtifacts(caseId)
      if (r.is_complete || r.missing.length === 0) {
        if (forceRerun) {
          rerunAll({ caseId, loanId, applicantName })
        } else {
          startAutoRun({ caseId, loanId, applicantName })
        }
        return
      }
      setGateMissing(r.missing)
    } catch (_) {
      // Gate check failed (network, server) — fall back to starting the
      // auto-run rather than blocking the user.
      if (forceRerun) rerunAll({ caseId, loanId, applicantName })
      else startAutoRun({ caseId, loanId, applicantName })
    } finally {
      setGateChecking(false)
    }
  }

  function handleMainClick() {
    if (status === 'idle') {
      void checkGateAndStart(false)
    } else if (status === 'blocked') {
      // Re-trigger after the operator uploads the missing docs. Force-rerun
      // so we re-poll the case stage and walk every level cleanly — `idle`
      // path can't be reused because the run already exists in state.
      void checkGateAndStart(true)
    } else {
      openModal(caseId)
    }
  }

  function handleRerunAllClick() {
    // Force re-run every level from scratch — ignores prior "done" markers.
    // Useful after fixing upstream data (re-uploaded bureau, corrected ZIP)
    // so the operator can re-verify all seven levels (including L6) in one
    // click without waiting on the auto-run's "skip done steps" heuristic.
    void checkGateAndStart(true)
  }

  const label =
    status === 'idle'
      ? 'Auto-run all levels'
      : status === 'running'
      ? `Auto-run running ${pct}% — open`
      : status === 'done'
      ? 'Pipeline complete'
      : status === 'done_with_errors'
      ? `Finished with errors ${pct}% — view`
      : status === 'blocked'
      ? 'Upload missing docs, then click to retry'
      : 'Run failed — view'

  // Static icon for non-running states. When running we replace the icon
  // with a CircularRing that paints the actual % progress; this matches the
  // dock pill so the operator sees the same gauge in both places.
  const Icon =
    status === 'done'
      ? CheckCircleIcon
      : status === 'done_with_errors' ||
        status === 'failed' ||
        status === 'blocked'
      ? AlertTriangleIcon
      : PlayIcon

  return (
    <div className="inline-flex items-center gap-2">
      <button
        type="button"
        onClick={handleMainClick}
        className={cn(
          'inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-semibold border transition-colors',
          status === 'done' && 'border-emerald-600 text-emerald-700 hover:bg-emerald-50',
          status === 'done_with_errors' && 'border-amber-600 text-amber-700 hover:bg-amber-50',
          status === 'blocked' && 'border-amber-600 text-amber-700 hover:bg-amber-50',
          status === 'failed' && 'border-red-600 text-red-700 hover:bg-red-50',
          status === 'running' && 'border-pfl-blue-600 text-pfl-blue-700 hover:bg-pfl-blue-50',
          status === 'idle' && 'bg-pfl-blue-800 text-white hover:bg-pfl-blue-900 border-transparent',
        )}
        title={label}
      >
        {status === 'running' ? (
          <CircularRing pct={pct} status="running" size={18} />
        ) : (
          <Icon className="h-3.5 w-3.5" aria-hidden />
        )}
        {label}
      </button>
      {/*
        Secondary "Re-run all" — shown only once the pipeline has finished
        at least one pass (running / done / done_with_errors / failed).
        Hidden on 'idle' to keep the header uncluttered before the first
        run; the main button already handles the start path.
      */}
      {status !== 'idle' && (
        <button
          type="button"
          onClick={handleRerunAllClick}
          disabled={status === 'running' || gateChecking}
          className={cn(
            'inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-semibold border transition-colors',
            'border-slate-600 text-slate-700 hover:bg-slate-50',
            (status === 'running' || gateChecking) && 'opacity-50 cursor-not-allowed',
          )}
          title="Force re-run every level (L1 → L6) from scratch"
        >
          <RefreshCwIcon className="h-3.5 w-3.5" aria-hidden />
          Re-run all
        </button>
      )}
      {gateMissing && (
        <AutorunGateModal
          caseId={caseId}
          loanId={loanId}
          missing={gateMissing}
          onUploadNow={() => {
            setGateMissing(null)
            // Best-effort scroll to the upload area on the case page.
            const upload = document.querySelector('[data-testid="case-upload"]')
            if (upload) upload.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }}
          onSkip={() => {
            setGateMissing(null)
            startAutoRun({ caseId, loanId, applicantName })
          }}
          onClose={() => setGateMissing(null)}
        />
      )}
    </div>
  )
}
