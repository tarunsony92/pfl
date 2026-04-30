'use client'
/**
 * OpusCreditVerdictCard — `opus_credit_verdict` (L1.5). The L1.5 Opus
 * pass returns an unstructured analyst narrative plus per-party
 * verdicts. This card surfaces those + falls through cleanly when a
 * field is missing — `opus_evidence` is the least typed L1.5 output, so
 * defensive rendering matters.
 */

import { cn } from '@/lib/cn'

export function OpusCreditVerdictCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const applicantVerdict = ev['applicant_verdict'] as string | undefined
  const coappVerdict = ev['coapp_verdict'] as string | undefined
  const reason =
    (ev['reason'] as string | undefined) ??
    (ev['narrative'] as string | undefined) ??
    (ev['summary'] as string | undefined)

  return (
    <div className="flex flex-col gap-2 text-[12px]">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <VerdictBlock label="Applicant" verdict={applicantVerdict} />
        <VerdictBlock label="Co-applicant" verdict={coappVerdict} />
      </div>
      {reason && (
        <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-2 text-pfl-slate-700 italic whitespace-pre-wrap">
          {reason}
        </div>
      )}
    </div>
  )
}

function VerdictBlock({
  label,
  verdict,
}: {
  label: string
  verdict: string | undefined
}) {
  const v = (verdict ?? '').toLowerCase()
  const tone = v.includes('clean') || v.includes('clear')
    ? 'pass'
    : v.includes('warn') || v.includes('partial')
    ? 'warn'
    : v.length === 0
    ? 'unknown'
    : 'fail'
  const palette = {
    pass: 'border-emerald-200 bg-emerald-50/40 text-emerald-800',
    warn: 'border-amber-200 bg-amber-50/40 text-amber-800',
    fail: 'border-red-200 bg-red-50/40 text-red-800',
    unknown: 'border-pfl-slate-200 bg-pfl-slate-50 text-pfl-slate-700',
  }[tone]
  return (
    <div className={cn('rounded border p-2', palette)}>
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
        {label}
      </div>
      <div className="text-[13px] font-bold uppercase">
        {verdict ?? '—'}
      </div>
    </div>
  )
}
