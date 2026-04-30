'use client'
/**
 * GpsVsAadhaarCard — `gps_vs_aadhaar` (L1).
 *
 * The headline question for a credit officer is "do the GPS coords on
 * the house-visit photo land where the applicant's Aadhaar says they
 * live?". Card shows the two addresses side-by-side, the structured
 * Nominatim match verdict + score (when available), and the raw GPS
 * coords for triangulation.
 *
 * Used on both the fire path (concern) and the pass path. Identical
 * evidence shape on both — see `build_pass_evidence_l1` in
 * level_1_address.py.
 */

import { cn } from '@/lib/cn'
import { formatEvidenceValue } from './_format'
import { DistanceBadge } from './DistanceBadge'

type GpsMatch = {
  verdict?: string
  score?: number
  reason?: string
}

export function GpsVsAadhaarCard({ evidence }: { evidence: Record<string, unknown> }) {
  const aadhaar =
    (evidence['applicant_aadhaar_address'] as string | undefined) ??
    (evidence['aadhaar_address'] as string | undefined) ??
    ''
  const gps = (evidence['gps_derived_address'] as string | undefined) ?? ''
  const coords = evidence['gps_coords'] as [number, number] | undefined
  const match = evidence['gps_match'] as GpsMatch | undefined
  const verdict =
    typeof match?.verdict === 'string' ? match.verdict.toUpperCase() : null

  const verdictCls = (() => {
    if (!verdict) return 'text-pfl-slate-700'
    if (verdict.includes('MATCH') && !verdict.includes('NO')) {
      return 'text-emerald-700'
    }
    if (verdict === 'PARTIAL' || verdict === 'WEAK') return 'text-amber-700'
    return 'text-red-700'
  })()

  return (
    <div className="flex flex-col gap-3">
      <DistanceBadge evidence={evidence} />
      {/* Two-address comparison */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <AddressBlock label="Aadhaar address" value={aadhaar} />
        <AddressBlock label="GPS-derived address" value={gps} />
      </div>

      {/* Structured match verdict (Nominatim path) */}
      {match && typeof match === 'object' && (
        <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-2 text-[12px]">
          <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
            Aadhaar ↔ GPS structured match
          </div>
          <div className="text-pfl-slate-900">
            Verdict:{' '}
            <span className={cn('font-bold', verdictCls)}>{verdict ?? '—'}</span>
            {typeof match.score === 'number' && (
              <>
                {' '}
                · Score{' '}
                <span className="font-mono">{match.score}/100</span>
              </>
            )}
          </div>
          {match.reason && (
            <div className="mt-1 text-pfl-slate-600 italic">{match.reason}</div>
          )}
        </div>
      )}

      {/* GPS coords */}
      {coords && Array.isArray(coords) && coords.length === 2 && (
        <div className="text-[11.5px] text-pfl-slate-600">
          <span className="font-medium">GPS coords:</span>{' '}
          <span className="font-mono">{formatEvidenceValue(coords)}</span>
        </div>
      )}
    </div>
  )
}

function AddressBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-2">
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
        {label}
      </div>
      <div className="text-[12px] text-pfl-slate-800 whitespace-pre-wrap break-words">
        {value || '—'}
      </div>
    </div>
  )
}

/** Eyebrow for the EvidenceTwoColumn header. Returns the structured
 *  match score when the Nominatim path ran, else null so the wrapper
 *  drops the eyebrow. */
export function gpsVsAadhaarHeadline(
  ev: Record<string, unknown>,
): string | undefined {
  const match = ev['gps_match'] as GpsMatch | undefined
  if (match && typeof match.score === 'number') {
    return `score ${match.score}/100`
  }
  return undefined
}
