'use client'
/**
 * AssetAnnexureCard — `asset_annexure_empty` (L4). When the annexure
 * exists but is empty (zero assets), the loan is effectively
 * unsecured. Card lays out the assets list when present and gives the
 * count headline.
 */

import { cn } from '@/lib/cn'

type Asset = {
  description?: string | null
  category?: string | null
  estimated_value_inr?: number | null
}

export function AssetAnnexureCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const count = (ev['asset_count'] as number | undefined) ?? 0
  const assets = (ev['assets'] as Asset[] | undefined) ?? []
  const populated = count > 0

  return (
    <div className="flex flex-col gap-2 text-[12px]">
      <div className="flex items-center gap-2">
        <span className="text-pfl-slate-700">Assets enumerated:</span>
        <span
          className={cn(
            'font-mono font-bold text-[14px]',
            populated ? 'text-emerald-700' : 'text-red-700',
          )}
        >
          {count}
        </span>
        <span
          className={cn(
            'ml-auto inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider',
            populated
              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
              : 'bg-red-50 text-red-700 border-red-200',
          )}
        >
          {populated ? 'enforceable' : 'unsecured'}
        </span>
      </div>
      {assets.length > 0 && (
        <div className="rounded border border-pfl-slate-200 bg-white overflow-hidden">
          <table className="w-full text-[11.5px]">
            <thead className="bg-pfl-slate-50 text-pfl-slate-600 uppercase text-[10px] tracking-wider">
              <tr>
                <th className="px-2 py-1 text-left">#</th>
                <th className="px-2 py-1 text-left">Description</th>
                <th className="px-2 py-1 text-left">Category</th>
              </tr>
            </thead>
            <tbody>
              {assets.map((a, i) => (
                <tr key={i} className="border-t border-pfl-slate-100">
                  <td className="px-2 py-1 font-mono text-pfl-slate-500">
                    {i + 1}
                  </td>
                  <td className="px-2 py-1 text-pfl-slate-800">
                    {a.description ?? '—'}
                  </td>
                  <td className="px-2 py-1 text-pfl-slate-600">
                    {a.category ?? '—'}
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

export function assetAnnexureHeadline(
  ev: Record<string, unknown>,
): string | undefined {
  const n = ev['asset_count']
  if (typeof n === 'number') return `${n} asset${n === 1 ? '' : 's'}`
  return undefined
}
