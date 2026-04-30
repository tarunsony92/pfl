'use client'
/**
 * BureauWorstCaseStrip — credit-officer roll-up for L1.5. The 12
 * bureau-status rules fire as separate rows; without a summary at the
 * top the assessor reads a wall of similar-looking entries before they
 * realise the case is clean. This strip leads with the worst-case
 * one-liner per party so triage happens in <2 seconds:
 *
 *   Applicant: 1 settled · 2 SMA · others clean
 *   Co-applicant: clean
 */

import { cn } from '@/lib/cn'
import type { LevelIssueRead } from '@/lib/types'

type Party = 'applicant' | 'co_applicant'

const STAGES: Array<{ stage: string; label: string }> = [
  { stage: 'write_off', label: 'write-off' },
  { stage: 'loss', label: 'loss' },
  { stage: 'settled', label: 'settled' },
  { stage: 'substandard', label: 'substandard' },
  { stage: 'doubtful', label: 'doubtful' },
  { stage: 'sma', label: 'SMA' },
]

function ruleIdFor(party: Party, stage: string): string {
  return party === 'co_applicant' ? `coapp_credit_${stage}` : `credit_${stage}`
}

function countForRule(
  issues: LevelIssueRead[],
  ruleId: string,
): number {
  const issue = issues.find((i) => i.sub_step_id === ruleId)
  if (!issue) return 0
  const ev = (issue.evidence ?? {}) as Record<string, unknown>
  const matched = ev['accounts_matched']
  if (typeof matched === 'number' && matched >= 0) return matched
  // Fallback — if accounts_matched isn't carried, the issue itself
  // signals at least one account.
  return 1
}

export function BureauWorstCaseStrip({
  issues,
}: {
  issues: LevelIssueRead[]
}) {
  const summarise = (party: Party): { hits: Array<[string, number]>; clean: boolean } => {
    const hits: Array<[string, number]> = []
    for (const { stage, label } of STAGES) {
      const n = countForRule(issues, ruleIdFor(party, stage))
      if (n > 0) hits.push([label, n])
    }
    return { hits, clean: hits.length === 0 }
  }

  const applicant = summarise('applicant')
  const coapp = summarise('co_applicant')
  // Only render when this is actually L1.5 — the L1.5 LevelCard
  // body decides when to mount this strip.
  return (
    <div className="rounded border border-pfl-slate-200 bg-white p-3">
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-2">
        Bureau worst-case roll-up
      </div>
      <div className="flex flex-col gap-1.5 text-[12.5px]">
        <PartyLine label="Applicant" hits={applicant.hits} clean={applicant.clean} />
        <PartyLine label="Co-applicant" hits={coapp.hits} clean={coapp.clean} />
      </div>
    </div>
  )
}

function PartyLine({
  label,
  hits,
  clean,
}: {
  label: string
  hits: Array<[string, number]>
  clean: boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className="inline-flex items-center rounded border border-pfl-slate-200 bg-pfl-slate-50 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-pfl-slate-700">
        {label}
      </span>
      {clean ? (
        <span className="text-emerald-700 font-semibold">clean</span>
      ) : (
        <>
          {hits.map(([stageLabel, n], i) => (
            <span
              key={stageLabel}
              className={cn(
                'rounded border px-1.5 py-0.5 text-[11px] font-semibold',
                stageLabel === 'write-off' || stageLabel === 'loss'
                  ? 'border-red-200 bg-red-50 text-red-700'
                  : stageLabel === 'settled' ||
                    stageLabel === 'doubtful' ||
                    stageLabel === 'substandard'
                  ? 'border-amber-200 bg-amber-50 text-amber-800'
                  : 'border-pfl-slate-200 bg-pfl-slate-50 text-pfl-slate-700',
              )}
            >
              {n} {stageLabel}
              {n === 1 ? '' : 's'}
            </span>
          ))}
          <span className="text-pfl-slate-500 text-[11.5px]">
            · others clean
          </span>
        </>
      )}
    </div>
  )
}
