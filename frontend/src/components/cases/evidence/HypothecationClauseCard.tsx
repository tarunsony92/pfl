'use client'
/**
 * HypothecationClauseCard — `hypothecation_clause` (L4). The agreement
 * has to carry the hypothecation clause that lets the lender repossess
 * the named assets on default. Without it the loan is unsecured even if
 * the assets are listed.
 */

import { cn } from '@/lib/cn'

export function HypothecationClauseCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const present = !!ev['hypothecation_clause_present']
  return (
    <div className="flex flex-col gap-2 text-[12px]">
      <div className="flex items-center gap-2">
        <span className="text-pfl-slate-700">Hypothecation clause:</span>
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
      </div>
      <div className="text-[11px] text-pfl-slate-500">
        Lets the lender repossess the assets named in the annexure on
        default. Without it the loan effectively becomes unsecured.
      </div>
    </div>
  )
}
