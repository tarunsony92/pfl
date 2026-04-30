'use client'
/**
 * SinglePayerConcentrationCard — `single_payer_concentration` (L2).
 * Concentration risk: when ≥X% of declared income lands from a single
 * source the income story is fragile. Card shows distinct payer count
 * vs the rule's threshold.
 */

import { cn } from '@/lib/cn'
import { formatInr } from '../l3/helpers'

export function SinglePayerConcentrationCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const distinct = ev['distinct_credit_payers'] as number | undefined
  const declared = ev['declared_monthly_income_inr'] as number | undefined
  const minIncome = ev['min_income_for_rule_inr'] as number | undefined
  const cleared = typeof distinct === 'number' && distinct >= 2

  return (
    <div className="flex flex-col gap-2 text-[12px]">
      <div className="flex items-center gap-2">
        <span className="text-pfl-slate-700">Distinct credit payers:</span>
        <span
          className={cn(
            'font-mono text-[14px] font-bold',
            cleared ? 'text-emerald-700' : 'text-amber-700',
          )}
        >
          {typeof distinct === 'number' ? distinct : '—'}
        </span>
        <span
          className={cn(
            'ml-auto inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider',
            cleared
              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
              : 'bg-amber-50 text-amber-800 border-amber-200',
          )}
        >
          {cleared ? 'diversified' : 'concentrated'}
        </span>
      </div>
      <div className="grid grid-cols-[max-content,1fr] gap-x-3 gap-y-1">
        <span className="font-medium text-pfl-slate-600">Declared monthly income</span>
        <span className="font-mono text-pfl-slate-900">{formatInr(declared ?? null)}</span>
        {typeof minIncome === 'number' && (
          <>
            <span className="font-medium text-pfl-slate-600">Rule applies above</span>
            <span className="font-mono text-pfl-slate-900">{formatInr(minIncome)}</span>
          </>
        )}
      </div>
    </div>
  )
}
