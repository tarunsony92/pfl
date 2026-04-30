'use client'

import { cn } from '@/lib/cn'
import { TONE_PILL_CLASSES } from '../l3/helpers'

type JudgeVerdict = {
  severity?: string | null
  reason?: string | null
  confidence?: number | null
  model_used?: string | null
  cost_usd?: number | null
}

type Evidence = {
  travel_minutes?: number | null
  distance_km?: number | null
  dm_status?: 'ok' | 'zero_results' | 'error' | string | null
  threshold_min?: number | null
  judge_verdict?: JudgeVerdict | null
  judge_attempted?: boolean | null
}

/**
 * `CommuteCard` — smart-layout for L1's `house_business_commute` rule.
 * Row 1 surfaces travel time + distance + distance-matrix status; row 2
 * surfaces the judge verdict (severity + reason) when present.
 */
export function CommuteCard({ evidence }: { evidence: Evidence }) {
  const travelMinutes = numericOrNull(evidence.travel_minutes)
  const distanceKm = numericOrNull(evidence.distance_km)
  const threshold = numericOrNull(evidence.threshold_min) ?? 30.0
  const dmStatus = evidence.dm_status ?? null
  const dmTone =
    dmStatus === 'ok'
      ? 'emerald'
      : dmStatus === 'zero_results' || dmStatus === 'error'
        ? 'red'
        : 'amber'

  const verdict = evidence.judge_verdict ?? null
  const hasVerdict =
    !!verdict && (verdict.severity != null || verdict.reason != null)
  const verdictTone = severityToTone(verdict?.severity)

  return (
    <div className="border border-pfl-slate-200 rounded bg-pfl-slate-50 p-3 flex flex-col gap-2">
      <div className="flex items-center gap-3 text-[12px]">
        <div className="flex items-baseline gap-1">
          <span className="text-pfl-slate-500">Travel</span>
          <span className="text-pfl-slate-900 font-semibold">
            {travelMinutes != null ? `${travelMinutes.toFixed(0)} min` : '—'}
          </span>
        </div>
        <div className="flex items-baseline gap-1">
          <span className="text-pfl-slate-500">Distance</span>
          <span className="text-pfl-slate-900 font-semibold">
            {distanceKm != null ? `${distanceKm.toFixed(1)} km` : '—'}
          </span>
        </div>
        <span className="ml-auto text-[11px] text-pfl-slate-500">
          threshold {threshold.toFixed(0)} min
        </span>
        {dmStatus && (
          <span
            className={cn(
              'inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold',
              TONE_PILL_CLASSES[dmTone],
            )}
          >
            dm · {String(dmStatus)}
          </span>
        )}
      </div>
      {hasVerdict && (
        <div className="flex items-start gap-2 text-[12px]">
          {verdict?.severity && (
            <span
              className={cn(
                'inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider flex-shrink-0',
                TONE_PILL_CLASSES[verdictTone],
              )}
            >
              {String(verdict.severity)}
            </span>
          )}
          {verdict?.reason && (
            <span className="text-pfl-slate-700 leading-snug">
              {String(verdict.reason)}
            </span>
          )}
        </div>
      )}
      {!hasVerdict && evidence.judge_attempted === false && (
        <div className="text-[11px] text-pfl-slate-500 italic">
          Judge not invoked for this case.
        </div>
      )}
    </div>
  )
}

function numericOrNull(v: unknown): number | null {
  if (typeof v !== 'number' || !Number.isFinite(v)) return null
  return v
}

function severityToTone(
  severity: string | null | undefined,
): 'emerald' | 'amber' | 'red' {
  if (!severity) return 'amber'
  const s = severity.toLowerCase()
  if (s === 'critical' || s === 'high' || s === 'severe') return 'red'
  if (s === 'warning' || s === 'medium' || s === 'moderate') return 'amber'
  if (s === 'ok' || s === 'clean' || s === 'low' || s === 'none') return 'emerald'
  return 'amber'
}
