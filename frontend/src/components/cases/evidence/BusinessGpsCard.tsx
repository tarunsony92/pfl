'use client'
/**
 * BusinessGpsCard — `business_visit_gps` (L1).
 *
 * Did at least one business-premises photo yield usable GPS coordinates
 * (EXIF or watermark OCR)? On the pass path the rule fires only when
 * coords were recovered. Headline shows the photos-tried count so the
 * MD can tell "we tried 1 vs we tried 8" at a glance.
 */

import { formatEvidenceValue } from './_format'

export function BusinessGpsCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const coords = ev['business_gps_coords'] as
    | [number, number]
    | undefined
    | null
  const photosTried = ev['photos_tried_count'] as number | undefined

  return (
    <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-2 text-[12px]">
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1.5">
        Business-visit GPS recovery
      </div>
      <div className="grid grid-cols-[max-content,1fr] gap-x-3 gap-y-1">
        <span className="font-medium text-pfl-slate-600">GPS coords</span>
        <span className="font-mono text-pfl-slate-900">
          {coords && Array.isArray(coords) && coords.length === 2
            ? formatEvidenceValue(coords)
            : '—'}
        </span>
        {typeof photosTried === 'number' && (
          <>
            <span className="font-medium text-pfl-slate-600">Photos tried</span>
            <span className="text-pfl-slate-900">{photosTried}</span>
          </>
        )}
      </div>
    </div>
  )
}

export function businessGpsHeadline(
  ev: Record<string, unknown>,
): string | undefined {
  const n = ev['photos_tried_count']
  if (typeof n === 'number') return `${n} photo${n === 1 ? '' : 's'} tried`
  return undefined
}
