'use client'
/**
 * NachBouncesCard — `nach_bounces` (L2). Each bounce is a hard fraud
 * signal so the card lists them one by one (date · description · amount)
 * along with the count headline.
 */

import { cn } from '@/lib/cn'
import { formatInr } from '../l3/helpers'

type Bounce = {
  date?: string | null
  description?: string | null
  amount?: number | null
  amount_inr?: number | null
}

export function NachBouncesCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const count = (ev['nach_bounce_count'] as number | undefined) ?? 0
  const bounces = (ev['nach_bounces'] as Bounce[] | undefined) ?? []

  const cleared = count === 0
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 text-[12px]">
        <span className="text-pfl-slate-700">Bounce count:</span>
        <span
          className={cn(
            'font-mono text-[14px] font-bold',
            cleared ? 'text-emerald-700' : 'text-red-700',
          )}
        >
          {count}
        </span>
        <span
          className={cn(
            'ml-2 inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider',
            cleared
              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
              : 'bg-red-50 text-red-700 border-red-200',
          )}
        >
          {cleared ? 'no bounces' : 'fraud signal'}
        </span>
      </div>
      {bounces.length > 0 && (
        <div className="rounded border border-pfl-slate-200 bg-white overflow-hidden">
          <table className="w-full text-[11.5px]">
            <thead className="bg-pfl-slate-50 text-pfl-slate-600 uppercase text-[10px] tracking-wider">
              <tr>
                <th className="px-2 py-1 text-left">Date</th>
                <th className="px-2 py-1 text-left">Description</th>
                <th className="px-2 py-1 text-right">Amount</th>
              </tr>
            </thead>
            <tbody>
              {bounces.map((b, i) => (
                <tr key={i} className="border-t border-pfl-slate-100">
                  <td className="px-2 py-1 font-mono text-pfl-slate-700">
                    {b.date ?? '—'}
                  </td>
                  <td className="px-2 py-1 text-pfl-slate-800">
                    {b.description ?? '—'}
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-pfl-slate-900">
                    {formatInr(b.amount ?? b.amount_inr ?? null)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export function nachBouncesHeadline(
  ev: Record<string, unknown>,
): string | undefined {
  const n = ev['nach_bounce_count']
  if (typeof n === 'number') return `${n} bounce${n === 1 ? '' : 's'}`
  return undefined
}
