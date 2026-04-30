'use client'
/**
 * ChronicLowBalanceCard — `chronic_low_balance` (L2). Average balance
 * against an absolute floor (₹1,000 by default). A chronically empty
 * bank account is a hard signal that the case is not bankable.
 */

import { cn } from '@/lib/cn'
import { formatInr } from '../l3/helpers'

export function ChronicLowBalanceCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const avg = ev['avg_monthly_balance_inr'] as number | undefined
  const floor = (ev['min_floor_inr'] as number | undefined) ?? 1000
  const cleared = typeof avg === 'number' && avg >= floor

  return (
    <div className="flex flex-col gap-2 text-[12px]">
      <div className="flex items-center gap-2">
        <span className="text-pfl-slate-700">Avg monthly balance:</span>
        <span
          className={cn(
            'font-mono font-bold text-[14px]',
            cleared ? 'text-emerald-700' : 'text-red-700',
          )}
        >
          {formatInr(avg ?? null)}
        </span>
        <span
          className={cn(
            'ml-auto inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider',
            cleared
              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
              : 'bg-red-50 text-red-700 border-red-200',
          )}
        >
          floor {formatInr(floor)}
        </span>
      </div>
    </div>
  )
}
