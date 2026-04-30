'use client'
/**
 * CaNarrativeCard — `ca_narrative_concerns` (L2).
 *
 * The CA-grade Claude Haiku pass returns two freeform string lists:
 * `ca_concerns[]` (red bullets) and `ca_positives[]` (green bullets),
 * plus an `overall_verdict`. Card lays them out as two stacked tabular
 * blocks so a credit officer reads concerns first, positives second —
 * mirroring how the underwriter actually thinks about a CA narrative.
 */

import { cn } from '@/lib/cn'

export function CaNarrativeCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const concerns = (ev['ca_concerns'] as unknown[] | undefined)?.filter(
    (s): s is string => typeof s === 'string',
  ) ?? []
  const positives = (ev['ca_positives'] as unknown[] | undefined)?.filter(
    (s): s is string => typeof s === 'string',
  ) ?? []
  const verdict =
    typeof ev['overall_verdict'] === 'string'
      ? (ev['overall_verdict'] as string)
      : null

  const verdictTone = (() => {
    if (!verdict) return null
    const v = verdict.toLowerCase()
    if (v.includes('clean') || v.includes('clear')) return 'pass'
    if (v.includes('warn') || v.includes('caution')) return 'warn'
    return 'fail'
  })()

  return (
    <div className="flex flex-col gap-3">
      {verdict && (
        <div className="flex items-center gap-2 text-[12px]">
          <span className="text-pfl-slate-600">Overall CA verdict:</span>
          <span
            className={cn(
              'inline-flex items-center rounded border px-1.5 py-0.5 text-[10.5px] font-bold uppercase tracking-wider',
              verdictTone === 'pass' &&
                'bg-emerald-50 text-emerald-700 border-emerald-200',
              verdictTone === 'warn' &&
                'bg-amber-50 text-amber-800 border-amber-200',
              verdictTone === 'fail' &&
                'bg-red-50 text-red-700 border-red-200',
            )}
          >
            {verdict}
          </span>
        </div>
      )}
      <BulletBlock
        title={`Concerns (${concerns.length})`}
        items={concerns}
        tone="fail"
        empty="No concerns raised."
      />
      <BulletBlock
        title={`Positives (${positives.length})`}
        items={positives}
        tone="pass"
        empty="No positives noted."
      />
    </div>
  )
}

function BulletBlock({
  title,
  items,
  tone,
  empty,
}: {
  title: string
  items: string[]
  tone: 'pass' | 'fail'
  empty: string
}) {
  const palette =
    tone === 'pass'
      ? 'border-emerald-200 bg-emerald-50/40'
      : 'border-red-200 bg-red-50/40'
  const dot = tone === 'pass' ? 'bg-emerald-500' : 'bg-red-500'
  return (
    <div className={cn('rounded border p-2', palette)}>
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-600 mb-1.5">
        {title}
      </div>
      {items.length === 0 ? (
        <div className="text-[11.5px] italic text-pfl-slate-500">{empty}</div>
      ) : (
        <ul className="flex flex-col gap-1 text-[12px]">
          {items.map((item, i) => (
            <li key={i} className="flex gap-2 leading-snug">
              <span className={cn('mt-1.5 h-1.5 w-1.5 rounded-full shrink-0', dot)} />
              <span className="text-pfl-slate-800">{item}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function caNarrativeHeadline(
  ev: Record<string, unknown>,
): string | undefined {
  const c = ev['ca_concerns']
  const p = ev['ca_positives']
  const cn_ = Array.isArray(c) ? c.length : 0
  const pn = Array.isArray(p) ? p.length : 0
  if (cn_ === 0 && pn === 0) return undefined
  return `${cn_} concern${cn_ === 1 ? '' : 's'} · ${pn} positive${pn === 1 ? '' : 's'}`
}
