'use client'

/**
 * CaseFinalReportCard — "Download Final Verdict Report" on the Overview tab.
 *
 * Gate: the backend only emits the PDF when every LevelIssue on the case
 * is in a settled state (MD_APPROVED / MD_REJECTED — the AutoJustifier
 * counts). On 409 the endpoint returns a structured blocking list, which
 * we surface here so the user knows exactly what's holding the report.
 */

import React, { useState } from 'react'
import {
  FileTextIcon,
  DownloadIcon,
  AlertTriangleIcon,
  CheckCircleIcon,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cases as casesApi } from '@/lib/api'

interface Props {
  caseId: string
  loanId: string
}

type Blocker = {
  sub_step_id: string
  status: string
  severity: string
  description: string
}

export function CaseFinalReportCard({ caseId, loanId }: Props) {
  const [busy, setBusy] = useState(false)
  const [blockers, setBlockers] = useState<Blocker[] | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [lastDownloadedAt, setLastDownloadedAt] = useState<string | null>(null)

  async function handleDownload() {
    setBusy(true)
    setErrorMsg(null)
    try {
      const r = await casesApi.finalReport(caseId)
      if (r.ok) {
        // Force browser download
        const url = URL.createObjectURL(r.blob)
        const a = document.createElement('a')
        a.href = url
        a.download = r.filename
        document.body.appendChild(a)
        a.click()
        a.remove()
        URL.revokeObjectURL(url)
        setBlockers(null)
        setLastDownloadedAt(new Date().toLocaleString())
      } else {
        setBlockers(r.blocking ?? [])
        setErrorMsg(r.message || r.error)
      }
    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : 'Failed to fetch report')
    } finally {
      setBusy(false)
    }
  }

  const blocked = (blockers?.length ?? 0) > 0
  const criticalBlockers = (blockers ?? []).filter((b) => b.severity === 'CRITICAL')

  return (
    <Card className="mb-6">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-semibold text-pfl-slate-900 flex items-center gap-2">
            <FileTextIcon className="h-4 w-4 text-pfl-slate-500" />
            <span>Final Verdict Report</span>
          </CardTitle>
          {lastDownloadedAt && (
            <p className="text-xs text-emerald-700 italic flex items-center gap-1">
              <CheckCircleIcon className="h-3 w-3" /> last downloaded{' '}
              {lastDownloadedAt}
            </p>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-[13px] text-pfl-slate-600 leading-relaxed mb-3">
          A signed, auditor-grade PDF containing the 32-point score, the L1–L5
          level scorecard, every MD &amp; AI decision on file, and the final
          recommended verdict for loan <span className="font-mono">#{loanId}</span>.
          The report can only be generated once every open concern is
          resolved — either approved with a mitigation reason or rejected with
          a rejection reason, by the assessor, MD, or the AI auto-justifier.
        </p>

        <div className="flex items-center gap-3 flex-wrap">
          <button
            type="button"
            disabled={busy}
            onClick={handleDownload}
            className={
              'inline-flex items-center gap-2 rounded-md px-4 py-2 text-[13px] font-semibold transition-colors ' +
              (busy
                ? 'bg-pfl-slate-200 text-pfl-slate-500 cursor-wait'
                : 'bg-pfl-slate-900 text-white hover:bg-black')
            }
          >
            <DownloadIcon className="h-4 w-4" />
            {busy ? 'Generating…' : 'Download final report (PDF)'}
          </button>
          <span className="text-[11.5px] text-pfl-slate-500 italic">
            Server regenerates the PDF on every click — always reflects the latest
            decisions.
          </span>
        </div>

        {errorMsg && !blocked && (
          <div className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-[12.5px] text-red-800">
            {errorMsg}
          </div>
        )}

        {blocked && (
          <div className="mt-4 rounded border border-amber-200 bg-amber-50/60 px-3 py-2">
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangleIcon className="h-4 w-4 text-amber-700" />
              <span className="text-[12.5px] font-semibold text-amber-800">
                Report gate is open — {blockers?.length} concern(s) pending
                adjudication.
              </span>
            </div>
            <p className="text-[12px] text-amber-900/90 leading-snug mb-2">
              {errorMsg}
            </p>
            <ul className="text-[12px] leading-snug space-y-1 text-pfl-slate-800">
              {(blockers ?? []).slice(0, 8).map((b, i) => (
                <li key={`${b.sub_step_id}-${i}`} className="flex gap-2">
                  <span
                    className={
                      b.severity === 'CRITICAL'
                        ? 'text-[10px] font-semibold uppercase tracking-wider text-red-700 min-w-[60px]'
                        : 'text-[10px] font-semibold uppercase tracking-wider text-amber-700 min-w-[60px]'
                    }
                  >
                    {b.severity}
                  </span>
                  <span className="font-mono text-pfl-slate-600 text-[11px] min-w-[160px]">
                    {b.sub_step_id}
                  </span>
                  <span className="flex-1">{b.description}</span>
                </li>
              ))}
              {(blockers ?? []).length > 8 && (
                <li className="italic text-pfl-slate-500 text-[11px]">
                  + {(blockers ?? []).length - 8} more — open the Verification
                  tab to resolve.
                </li>
              )}
            </ul>
            {criticalBlockers.length > 0 && (
              <p className="mt-2 text-[11px] italic text-red-800">
                Note: any <strong>MITIGATION</strong> rationale you record on a
                critical concern trains the auto-justifier to clear the same
                pattern on future cases automatically.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
