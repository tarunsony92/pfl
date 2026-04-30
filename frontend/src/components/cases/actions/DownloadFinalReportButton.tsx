'use client'

/**
 * DownloadFinalReportButton — row-level "Download Report" action on the
 * Cases list page. Hits the same endpoint as the Final Report card on the
 * case detail page (GET /cases/:id/final-report); the server regenerates
 * the PDF on every click. When `openIssueCount === 0` the button shows in
 * a green "ready" state with a tick — every concern on the case has been
 * settled and the report is downloadable.
 */

import React, { useState } from 'react'
import {
  CheckIcon,
  DownloadIcon,
  Loader2Icon,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { cases as casesApi } from '@/lib/api'

interface Props {
  caseId: string
  openIssueCount: number | null
}

export function DownloadFinalReportButton({ caseId, openIssueCount }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const ready = openIssueCount === 0

  async function handleClick() {
    setBusy(true)
    setError(null)
    try {
      const r = await casesApi.finalReport(caseId)
      if (r.ok) {
        const url = URL.createObjectURL(r.blob)
        const a = document.createElement('a')
        a.href = url
        a.download = r.filename
        document.body.appendChild(a)
        a.click()
        a.remove()
        URL.revokeObjectURL(url)
      } else if (r.status === 409) {
        const n = r.blocking?.length ?? 0
        setError(
          n > 0
            ? `${n} issue${n === 1 ? '' : 's'} still open`
            : r.message || 'Report gate is not clear',
        )
      } else {
        setError(r.message || `HTTP ${r.status}`)
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Download failed')
    } finally {
      setBusy(false)
    }
  }

  const title = ready
    ? 'All issues resolved — download final report (PDF)'
    : openIssueCount && openIssueCount > 0
      ? `${openIssueCount} open issue(s) — report not yet ready`
      : 'Download final report (PDF)'

  return (
    <div className="inline-flex flex-col items-end gap-0.5">
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        title={title}
        aria-label={title}
        className={cn(
          'inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-semibold border transition-colors',
          ready
            ? 'border-emerald-600 text-emerald-700 hover:bg-emerald-50'
            : 'border-pfl-slate-300 text-pfl-slate-700 hover:bg-pfl-slate-50',
          busy && 'opacity-60 cursor-wait',
        )}
        data-ready={ready ? 'true' : 'false'}
      >
        {busy ? (
          <Loader2Icon className="h-3.5 w-3.5 animate-spin" aria-hidden />
        ) : ready ? (
          <CheckIcon className="h-3.5 w-3.5" aria-hidden />
        ) : (
          <DownloadIcon className="h-3.5 w-3.5" aria-hidden />
        )}
        {busy ? 'Generating…' : 'Download report'}
      </button>
      {error && (
        <span className="text-[10.5px] text-red-700 max-w-[260px] text-right truncate">
          {error}
        </span>
      )}
    </div>
  )
}
