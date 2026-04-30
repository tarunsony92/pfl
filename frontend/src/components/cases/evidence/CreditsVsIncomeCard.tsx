'use client'
/**
 * CreditsVsIncomeCard — `credits_vs_declared_income` (L2). Surfaces the
 * formula a credit officer wants spelled out: Σ credits 3m / (declared
 * monthly × 3) ≥ floor 0.5. If the ratio comes in below 0.5, the
 * declared income story isn't backed by actual deposits.
 */

import { cn } from '@/lib/cn'
import { formatInr } from '../l3/helpers'

export function CreditsVsIncomeCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const credits3m = ev['three_month_credit_sum_inr'] as number | undefined
  const declaredMonthly = ev['declared_monthly_income_inr'] as
    | number
    | undefined
  const floor = (ev['floor_ratio'] as number | undefined) ?? 0.5
  const ratio = ev['ratio'] as number | undefined
  const cleared = typeof ratio === 'number' && ratio >= floor

  return (
    <div className="flex flex-col gap-2">
      <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-2 text-[12px] text-pfl-slate-800 leading-relaxed">
        <span className="font-mono">Σ credits 3m</span> ÷ (
        <span className="font-mono">declared</span> × 3) ={' '}
        <span
          className={cn(
            'font-mono font-bold',
            cleared ? 'text-emerald-700' : 'text-red-700',
          )}
        >
          {typeof ratio === 'number' ? `${(ratio * 100).toFixed(0)}%` : '—'}
        </span>{' '}
        · floor <span className="font-mono">{(floor * 100).toFixed(0)}%</span>
      </div>
      <div className="grid grid-cols-[max-content,1fr] gap-x-3 gap-y-1 text-[12px]">
        <span className="font-medium text-pfl-slate-600">3-month credits</span>
        <span className="font-mono text-pfl-slate-900">{formatInr(credits3m ?? null)}</span>
        <span className="font-medium text-pfl-slate-600">Declared monthly income</span>
        <span className="font-mono text-pfl-slate-900">
          {formatInr(declaredMonthly ?? null)}
        </span>
        <span className="font-medium text-pfl-slate-600">Expected over 3m</span>
        <span className="font-mono text-pfl-slate-900">
          {formatInr(declaredMonthly != null ? declaredMonthly * 3 : null)}
        </span>
      </div>
    </div>
  )
}

export function creditsVsIncomeHeadline(
  ev: Record<string, unknown>,
): string | undefined {
  const r = ev['ratio']
  if (typeof r === 'number') return `${(r * 100).toFixed(0)}% of declared`
  return undefined
}
