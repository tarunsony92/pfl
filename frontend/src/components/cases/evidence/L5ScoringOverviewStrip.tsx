'use client'
/**
 * L5ScoringOverviewStrip — credit-officer roll-up for L5. The 32-rubric
 * audit lands as a wall of issues; without a top tile the analyst has
 * to read every row before they know whether the case is an A or a D.
 * This strip leads with the grade pill, overall pct, EB verdict, and a
 * compact per-section bar so triage happens in <2 seconds before the
 * issues + passes lists below.
 *
 * Reads from `result.sub_step_results.scoring`. PR3 wires this into
 * the L5 LevelCard body the same way BureauWorstCaseStrip wires into
 * L1.5.
 */

import { cn } from '@/lib/cn'
import type { VerificationResultRead } from '@/lib/types'

type Section = {
  section_id?: string
  title?: string
  pct?: number
  earned?: number
  max_score?: number
}

type Scoring = {
  earned_score?: number
  max_score?: number
  overall_pct?: number
  grade?: string
  eb_verdict?: string
  sections?: Section[]
}

function gradeTone(grade: string | undefined): {
  cls: string
  label: string
} {
  if (!grade) return { cls: 'bg-slate-100 text-slate-600 border-slate-200', label: '—' }
  if (grade === 'A+' || grade === 'A')
    return {
      cls: 'bg-emerald-100 text-emerald-800 border-emerald-300',
      label: grade,
    }
  if (grade === 'B')
    return {
      cls: 'bg-amber-100 text-amber-800 border-amber-300',
      label: grade,
    }
  return { cls: 'bg-red-100 text-red-700 border-red-300', label: grade }
}

function pctTone(pct: number): { bar: string; text: string } {
  if (pct >= 80) return { bar: 'bg-emerald-500', text: 'text-emerald-700' }
  if (pct >= 60) return { bar: 'bg-amber-500', text: 'text-amber-700' }
  return { bar: 'bg-red-500', text: 'text-red-700' }
}

export function L5ScoringOverviewStrip({
  result,
}: {
  result: VerificationResultRead | undefined
}) {
  const ssr = (result?.sub_step_results ?? {}) as Record<string, unknown>
  const scoring = (ssr['scoring'] ?? {}) as Scoring
  const earned =
    typeof scoring.earned_score === 'number' ? scoring.earned_score : null
  const max = typeof scoring.max_score === 'number' ? scoring.max_score : null
  const pct =
    typeof scoring.overall_pct === 'number' ? scoring.overall_pct : null
  const grade = typeof scoring.grade === 'string' ? scoring.grade : undefined
  const ebVerdict =
    typeof scoring.eb_verdict === 'string' ? scoring.eb_verdict : undefined
  const sections = Array.isArray(scoring.sections) ? scoring.sections : []

  if (earned == null && max == null && grade == null && sections.length === 0) {
    return null
  }

  const gt = gradeTone(grade)
  const overallTone = pct != null ? pctTone(pct) : null

  return (
    <div className="rounded border border-pfl-slate-200 bg-white p-3 flex flex-col gap-3">
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500">
        Scoring overview
      </div>

      {/* Hero: grade + overall % + EB verdict */}
      <div className="flex flex-wrap items-center gap-3 text-[12.5px]">
        <span
          className={cn(
            'inline-flex items-center justify-center rounded border px-2.5 py-1 text-[16px] font-bold tracking-wider min-w-[3rem]',
            gt.cls,
          )}
        >
          {gt.label}
        </span>
        <div className="flex flex-col">
          <span className="text-[10px] uppercase tracking-wider text-pfl-slate-500">
            Overall score
          </span>
          <span
            className={cn(
              'font-mono font-bold text-[14px]',
              overallTone?.text ?? 'text-pfl-slate-700',
            )}
          >
            {earned ?? '—'} / {max ?? '—'}{' '}
            <span className="text-pfl-slate-400 font-normal">·</span>{' '}
            {pct != null ? `${pct.toFixed(1)}%` : '—'}
          </span>
        </div>
        {ebVerdict && (
          <div className="flex flex-col">
            <span className="text-[10px] uppercase tracking-wider text-pfl-slate-500">
              EB verdict
            </span>
            <span
              className={cn(
                'font-bold uppercase text-[12px]',
                ebVerdict === 'PASS'
                  ? 'text-emerald-700'
                  : ebVerdict === 'CONCERN'
                  ? 'text-amber-700'
                  : ebVerdict === 'FAIL'
                  ? 'text-red-700'
                  : 'text-pfl-slate-600',
              )}
            >
              {ebVerdict}
            </span>
          </div>
        )}
      </div>

      {/* Per-section breakdown */}
      {sections.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="text-[10px] uppercase tracking-wider text-pfl-slate-500">
            By section
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {sections.map((s, i) => {
              const sid = s.section_id ?? '?'
              const title = s.title ?? '—'
              const spct = typeof s.pct === 'number' ? s.pct : 0
              const sEarned = s.earned ?? 0
              const sMax = s.max_score ?? 0
              const tone = pctTone(spct)
              return (
                <div
                  key={i}
                  className="rounded border border-pfl-slate-200 bg-pfl-slate-50 px-2 py-1.5 text-[11.5px]"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-semibold text-pfl-slate-800 truncate">
                      {sid}: {title}
                    </span>
                    <span
                      className={cn(
                        'ml-auto font-mono tabular-nums shrink-0',
                        tone.text,
                      )}
                    >
                      {sEarned}/{sMax} · {spct.toFixed(0)}%
                    </span>
                  </div>
                  <div className="h-1.5 w-full rounded-full bg-pfl-slate-200 overflow-hidden">
                    <div
                      className={cn('h-full rounded-full', tone.bar)}
                      style={{ width: `${Math.max(0, Math.min(100, spct))}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
