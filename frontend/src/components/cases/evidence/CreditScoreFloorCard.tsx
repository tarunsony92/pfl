'use client'
/**
 * CreditScoreFloorCard — `credit_score_floor` / `coapp_credit_score_floor`
 * (L1.5). Renders party + bureau score + a horizontal range with two
 * threshold ticks (critical / warning). Visual echoes
 * `AvgBalanceVsEmiCard`'s bar so the L1.5 grammar matches L2.
 */

import { cn } from '@/lib/cn'

const RANGE_MIN = 300
const RANGE_MAX = 900

export function CreditScoreFloorCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const party = (ev['party'] as string | undefined) ?? 'applicant'
  const score = ev['credit_score'] as number | null | undefined
  const tCritical =
    (ev['threshold_critical'] as number | undefined) ?? 680
  const tWarning =
    (ev['threshold_warning'] as number | undefined) ?? 700

  const tone =
    typeof score === 'number'
      ? score >= tWarning
        ? 'pass'
        : score >= tCritical
        ? 'warn'
        : 'fail'
      : 'unknown'
  const palette = {
    pass: { bar: 'bg-emerald-500', text: 'text-emerald-700' },
    warn: { bar: 'bg-amber-500', text: 'text-amber-700' },
    fail: { bar: 'bg-red-500', text: 'text-red-700' },
    unknown: { bar: 'bg-pfl-slate-400', text: 'text-pfl-slate-600' },
  }[tone]

  const pct = (n: number) =>
    Math.max(
      0,
      Math.min(100, ((n - RANGE_MIN) / (RANGE_MAX - RANGE_MIN)) * 100),
    )
  const scorePct = typeof score === 'number' ? pct(score) : 0
  const tCriticalPct = pct(tCritical)
  const tWarningPct = pct(tWarning)

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 text-[12px]">
        <PartyPill party={party} />
        <span className="text-pfl-slate-700">Bureau score:</span>
        <span
          className={cn('font-mono text-[14px] font-bold', palette.text)}
        >
          {typeof score === 'number' ? score : '—'}
        </span>
      </div>

      <div className="relative h-3 w-full rounded-full bg-pfl-slate-200 overflow-visible">
        {typeof score === 'number' && (
          <div
            className={cn('absolute top-0 left-0 h-full rounded-full', palette.bar)}
            style={{ width: `${scorePct}%` }}
          />
        )}
        <Tick pct={tCriticalPct} color="bg-red-600" label={`crit ${tCritical}`} />
        <Tick pct={tWarningPct} color="bg-amber-600" label={`warn ${tWarning}`} />
      </div>
      <div className="flex justify-between text-[10.5px] text-pfl-slate-500 font-mono">
        <span>{RANGE_MIN}</span>
        <span>{RANGE_MAX}</span>
      </div>
    </div>
  )
}

function PartyPill({ party }: { party: string }) {
  const label = party === 'co_applicant' ? 'Co-applicant' : 'Applicant'
  const cls =
    party === 'co_applicant'
      ? 'bg-indigo-50 text-indigo-700 border-indigo-200'
      : 'bg-pfl-slate-100 text-pfl-slate-700 border-pfl-slate-200'
  return (
    <span
      className={cn(
        'inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider',
        cls,
      )}
    >
      {label}
    </span>
  )
}

function Tick({
  pct,
  color,
  label,
}: {
  pct: number
  color: string
  label: string
}) {
  return (
    <div
      className="absolute top-0 h-full"
      style={{ left: `${pct}%`, width: 0 }}
      title={label}
    >
      <div
        className={cn(
          'h-full w-[2px] -translate-x-[1px]',
          color,
        )}
      />
    </div>
  )
}

export function creditScoreFloorHeadline(
  ev: Record<string, unknown>,
): string | undefined {
  const n = ev['credit_score']
  if (typeof n === 'number') return `score ${n}`
  return undefined
}
