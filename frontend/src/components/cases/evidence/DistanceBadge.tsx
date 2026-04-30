'use client'
/**
 * DistanceBadge — surfaces the great-circle distance between two addresses
 * (in km) inside an L1 issue evidence card. Computed by the backend in
 * `level_1_address.py` via google_maps.forward_geocode + haversine_km, and
 * stuffed into ``issue.evidence['distance_km']`` so the FE can colour-bucket
 * without re-geocoding.
 *
 * Buckets are tuned for rural-India microfinance:
 *   <  1 km   →  green     "within walking distance — likely a photo-angle / joint-family case"
 *   1-10 km  →  amber     "same town / district — possible photo from a relative's house"
 *   ≥ 10 km   →  red       "addresses are in different localities — substantive mismatch"
 *
 * Renders nothing when the geocoder failed (api key missing, ZERO_RESULTS,
 * etc) — the description text already says so. Don't fake green.
 */

import { cn } from '@/lib/cn'

export function DistanceBadge({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const raw = ev['distance_km']
  if (typeof raw !== 'number' || !Number.isFinite(raw)) return null
  const km = raw

  const tone = km < 1 ? 'green' : km < 10 ? 'amber' : 'red'
  const label =
    km < 1 ? `${Math.round(km * 1000)} m apart` : `${km.toFixed(2)} km apart`
  const hint =
    km < 1
      ? 'within walking distance — likely a photo-angle / joint-family case'
      : km < 10
      ? 'same town / district — possible photo from a relative’s house'
      : 'addresses are in different localities — substantive mismatch'

  return (
    <div
      className={cn(
        'rounded border px-3 py-2 flex items-center gap-3 flex-wrap',
        tone === 'green' && 'border-emerald-300 bg-emerald-50/70',
        tone === 'amber' && 'border-amber-300 bg-amber-50/70',
        tone === 'red' && 'border-red-300 bg-red-50/70',
      )}
    >
      <span
        className={cn(
          'text-[10.5px] font-semibold uppercase tracking-wider',
          tone === 'green' && 'text-emerald-800',
          tone === 'amber' && 'text-amber-800',
          tone === 'red' && 'text-red-800',
        )}
      >
        Distance between addresses
      </span>
      <span
        className={cn(
          'text-[14px] font-bold tabular-nums',
          tone === 'green' && 'text-emerald-900',
          tone === 'amber' && 'text-amber-900',
          tone === 'red' && 'text-red-900',
        )}
      >
        {label}
      </span>
      <span className="text-[11.5px] text-pfl-slate-700 italic">{hint}</span>
    </div>
  )
}
