'use client'
/**
 * ImpulsiveDebitCard — `impulsive_debit_overspend` (L2). Discretionary
 * debit total vs declared income — flags lifestyle creep that erodes
 * repayment capacity.
 */

import { cn } from '@/lib/cn'
import { formatInr } from '../l3/helpers'

export function ImpulsiveDebitCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const total = ev['impulsive_debit_total_inr'] as number | undefined
  const declared = ev['declared_monthly_income_inr'] as number | undefined
  const ratio =
    typeof total === 'number' && typeof declared === 'number' && declared > 0
      ? total / declared
      : null
  const cleared = ratio != null && ratio <= 1

  return (
    <div className="flex flex-col gap-2 text-[12px]">
      <div className="flex items-center gap-2">
        <span className="text-pfl-slate-700">Impulsive debits:</span>
        <span className="font-mono font-semibold text-pfl-slate-900">
          {formatInr(total ?? null)}
        </span>
        <span className="text-pfl-slate-500">vs declared</span>
        <span className="font-mono text-pfl-slate-900">
          {formatInr(declared ?? null)}
        </span>
        <span
          className={cn(
            'ml-auto inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider',
            cleared
              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
              : 'bg-red-50 text-red-700 border-red-200',
          )}
        >
          {ratio != null ? `${(ratio * 100).toFixed(0)}% of income` : '—'}
        </span>
      </div>
      <div className="text-[11px] text-pfl-slate-500">
        Threshold: impulsive debits should not exceed one month of declared
        income.
      </div>
    </div>
  )
}

export function impulsiveDebitHeadline(
  ev: Record<string, unknown>,
): string | undefined {
  const t = ev['impulsive_debit_total_inr']
  const d = ev['declared_monthly_income_inr']
  if (typeof t === 'number' && typeof d === 'number' && d > 0) {
    return `${((t / d) * 100).toFixed(0)}% of declared`
  }
  return undefined
}
