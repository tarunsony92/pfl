'use client'

import { cn } from '@/lib/cn'
import {
  formatInr,
  TONE_PILL_CLASSES,
  type CoverageTone,
} from '../l3/helpers'

type Evidence = {
  avg_monthly_balance_inr?: number | null
  proposed_emi_inr?: number | null
  multiplier?: number | null
  ratio?: number | null
}

/**
 * `AvgBalanceVsEmiCard` — smart-layout for the L2 `avg_balance_vs_emi`
 * rule. Renders a compact horizontal bar comparing the account's average
 * monthly balance to the `proposed_emi × multiplier` floor. Tinted
 * emerald when the balance clears the full floor, amber when it only
 * clears the raw EMI, red otherwise.
 */
export function AvgBalanceVsEmiCard({
  evidence,
}: {
  evidence: Evidence
}) {
  const avgBalance = numericOrNull(evidence.avg_monthly_balance_inr)
  const emi = numericOrNull(evidence.proposed_emi_inr)
  const multiplier = numericOrNull(evidence.multiplier) ?? 1.5
  const required = emi != null ? emi * multiplier : null

  let tone: CoverageTone = 'red'
  if (avgBalance != null && required != null && avgBalance >= required) {
    tone = 'emerald'
  } else if (avgBalance != null && emi != null && avgBalance >= emi) {
    tone = 'amber'
  }

  // The bar's fill goes from 0 to max(avgBalance, required) so both
  // markers always fit on the axis. Defensive: if both values are null
  // we render a placeholder, not a 0-wide bar.
  const axisMax =
    avgBalance != null && required != null
      ? Math.max(avgBalance, required)
      : avgBalance ?? required ?? 0

  const balancePct =
    axisMax > 0 && avgBalance != null
      ? Math.min(100, (avgBalance / axisMax) * 100)
      : 0
  const requiredPct =
    axisMax > 0 && required != null
      ? Math.min(100, (required / axisMax) * 100)
      : 0

  const ratio = numericOrNull(evidence.ratio)

  return (
    <div className="border border-pfl-slate-200 rounded bg-pfl-slate-50 p-3 flex flex-col gap-2">
      <div className="flex items-center gap-2 text-[12px]">
        <span className="text-pfl-slate-600">Average balance</span>
        <span className="text-pfl-slate-900 font-semibold">
          {formatInr(avgBalance)}
        </span>
        <span className="mx-1 text-pfl-slate-400">vs</span>
        <span className="text-pfl-slate-600">Required</span>
        <span className="text-pfl-slate-900 font-semibold">
          {formatInr(required)}
        </span>
        <span
          className={cn(
            'ml-auto inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold',
            TONE_PILL_CLASSES[tone],
          )}
        >
          {tone === 'emerald'
            ? 'clears floor'
            : tone === 'amber'
              ? 'partial cover'
              : 'below EMI'}
        </span>
      </div>
      {axisMax > 0 ? (
        <div className="relative h-3 w-full rounded bg-pfl-slate-200/70 overflow-hidden">
          <div
            className={cn(
              'absolute inset-y-0 left-0 rounded',
              tone === 'emerald'
                ? 'bg-emerald-400/80'
                : tone === 'amber'
                  ? 'bg-amber-400/80'
                  : 'bg-red-400/80',
            )}
            style={{ width: `${balancePct}%` }}
          />
          {required != null && (
            <div
              className="absolute inset-y-0 w-[2px] bg-pfl-slate-900/70"
              style={{ left: `calc(${requiredPct}% - 1px)` }}
              aria-label="required floor"
            />
          )}
        </div>
      ) : (
        <div className="text-[11.5px] text-pfl-slate-500 italic">
          Not enough data to draw the balance vs EMI bar.
        </div>
      )}
      <div className="flex items-center gap-2 text-[11px] text-pfl-slate-600">
        <span className="inline-flex items-center rounded-md border border-pfl-slate-300 bg-white px-1.5 py-0.5 font-medium">
          multiplier {multiplier}×
        </span>
        {emi != null && (
          <span>
            EMI{' '}
            <span className="font-medium text-pfl-slate-800">
              {formatInr(emi)}
            </span>
          </span>
        )}
        {ratio != null && (
          <span className="ml-auto">
            ratio{' '}
            <span className="font-mono text-pfl-slate-800">
              {ratio.toFixed(2)}×
            </span>
          </span>
        )}
      </div>
    </div>
  )
}

function numericOrNull(v: unknown): number | null {
  if (typeof v !== 'number' || !Number.isFinite(v)) return null
  return v
}
