'use client'
/**
 * AnnexurePresenceCard — `loan_agreement_annexure` (L4). Says whether
 * the asset annexure is in the agreement and (when known) the page hint
 * that the EvidenceTwoColumn right column deep-links to via #page=N.
 */

import { cn } from '@/lib/cn'

export function AnnexurePresenceCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const present = !!ev['annexure_present']
  const pageHint = ev['annexure_page_hint'] as number | undefined

  return (
    <div className="flex flex-col gap-2 text-[12px]">
      <div className="flex items-center gap-2">
        <span className="text-pfl-slate-700">Asset annexure:</span>
        <span
          className={cn(
            'inline-flex items-center rounded border px-1.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wider',
            present
              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
              : 'bg-red-50 text-red-700 border-red-200',
          )}
        >
          {present ? 'present' : 'missing'}
        </span>
        {typeof pageHint === 'number' && (
          <span className="ml-auto font-mono text-[11px] text-pfl-slate-600">
            page hint {pageHint}
          </span>
        )}
      </div>
      <div className="text-[11px] text-pfl-slate-500">
        Without an enumerated annexure the hypothecated assets aren't
        contractually defined — the agreement can't be enforced.
      </div>
    </div>
  )
}

export function annexurePresenceHeadline(
  ev: Record<string, unknown>,
): string | undefined {
  const p = ev['annexure_page_hint']
  if (typeof p === 'number') return `page ${p}`
  return undefined
}
