'use client'
/**
 * EvidenceTwoColumn — the foundation primitive for the verification UI
 * revamp. Every concern AND every passing rule on every level renders
 * inside one of these so a credit officer reads the same grammar
 * level-by-level: claim left, proof right.
 *
 * LEFT  · "What was checked" header + structured fields / smart card
 * RIGHT · the exact source artefact(s) for this rule — Open + Download
 *
 * Stacks vertically <md, 60/40 ≥md, 55/45 ≥xl (matches the existing L3
 * stock-analysis split). The right column never collapses on missing
 * sources — placeholder card keeps the grid stable.
 */

import React from 'react'
import { PaperclipIcon } from 'lucide-react'
import { cn } from '@/lib/cn'
import { Skeleton } from '@/components/ui/skeleton'
import {
  HIDDEN_EVIDENCE_KEYS,
  formatEvidenceValue,
  humanKey,
  useResolvedArtifacts,
  type EvidenceVerdict,
  type SourceArtifactRef,
} from './_format'
import { SourceArtifactCard } from './SourceArtifactCard'

// ---------------------------------------------------------------------------
// Verdict pill — the at-a-glance status badge a 30-year underwriter
// expects in the top-left of every row.
// ---------------------------------------------------------------------------

const VERDICT_STYLE: Record<
  EvidenceVerdict,
  { label: string; cls: string }
> = {
  pass: { label: 'PASS', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  warn: { label: 'WARN', cls: 'bg-amber-50 text-amber-800 border-amber-200' },
  fail: { label: 'FAIL', cls: 'bg-red-50 text-red-700 border-red-200' },
  skipped: {
    label: 'SKIPPED',
    cls: 'bg-pfl-slate-100 text-pfl-slate-600 border-pfl-slate-200',
  },
}

export function VerdictPill({ verdict }: { verdict: EvidenceVerdict }) {
  const v = VERDICT_STYLE[verdict]
  return (
    <span
      className={cn(
        'inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider',
        v.cls,
      )}
    >
      {v.label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Generic key/value fallback — used by the dispatcher when no smart card
// matches a rule. Hides the noise keys consumed elsewhere.
// ---------------------------------------------------------------------------

export function GenericEvidenceTable({
  evidence,
  hideKeys,
}: {
  evidence: Record<string, unknown>
  hideKeys?: ReadonlySet<string>
}) {
  const allHidden = new Set<string>(HIDDEN_EVIDENCE_KEYS)
  for (const k of hideKeys ?? []) allHidden.add(k)
  const keys = Object.keys(evidence).filter((k) => !allHidden.has(k))
  if (keys.length === 0) {
    return (
      <div className="text-[12px] text-pfl-slate-500 italic">
        No additional structured fields on this rule.
      </div>
    )
  }
  return (
    <div className="grid grid-cols-[max-content,1fr] gap-x-3 gap-y-1 text-[12px]">
      {keys.map((k) => (
        <React.Fragment key={k}>
          <span className="font-medium text-pfl-slate-600">{humanKey(k)}</span>
          <span className="text-pfl-slate-800 font-mono break-words">
            {formatEvidenceValue(evidence[k])}
          </span>
        </React.Fragment>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Right column — resolves refs into artefact cards. Loading + empty states
// kept stable so the grid never collapses on the user.
// ---------------------------------------------------------------------------

function SourceArtifactColumn({
  caseId,
  sources,
}: {
  caseId: string
  sources: SourceArtifactRef[]
}) {
  const { matched, isLoading } = useResolvedArtifacts(caseId, sources)

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-600">
        <PaperclipIcon className="h-3 w-3" />
        Source {sources.length === 1 ? 'file' : 'files'}
        {sources.length > 0 && <> ({sources.length})</>}
      </div>
      {isLoading && <Skeleton className="h-10 w-full" />}
      {!isLoading && matched.length === 0 && (
        <div className="rounded border border-dashed border-pfl-slate-200 bg-pfl-slate-50/40 p-3 text-[11.5px] italic text-pfl-slate-500">
          Source files not yet attached for this rule.
        </div>
      )}
      {!isLoading && matched.length > 0 && (
        <div className="flex flex-col gap-2">
          {matched.map(({ ref, artifact }, idx) => (
            <SourceArtifactCard
              key={`${ref.artifact_id}-${idx}`}
              ref_={ref}
              artifact={artifact}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// EvidenceTwoColumn — the primitive itself.
// ---------------------------------------------------------------------------

export function EvidenceTwoColumn({
  caseId,
  left,
  right,
  sources,
  header = 'What was checked',
  verdict,
  headline,
  description,
  scrollLeft = false,
}: {
  caseId: string
  left: React.ReactNode
  right?: React.ReactNode
  sources?: SourceArtifactRef[]
  header?: string
  verdict?: EvidenceVerdict | null
  headline?: string
  /** Issue narrative — when set, rendered as a "Description of issue"
   *  subsection at the top of the LEFT column. The right column is
   *  taller than the left in the new layout (inline source previews),
   *  so we use the spare LEFT space to bring the description into the
   *  panel instead of duplicating it above. */
  description?: string
  scrollLeft?: boolean
}) {
  const hasHeadline = typeof headline === 'string' && headline.length > 0
  const hasDescription = typeof description === 'string' && description.length > 0
  const rightContent =
    right ?? <SourceArtifactColumn caseId={caseId} sources={sources ?? []} />

  return (
    <div className="border border-pfl-slate-200 rounded-md bg-white overflow-hidden">
      <div className="px-3 py-1.5 border-b border-pfl-slate-100 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-600">
        <span>{header}</span>
        {verdict && <VerdictPill verdict={verdict} />}
        {hasHeadline && (
          <span className="ml-auto text-[11px] font-mono normal-case tracking-normal text-pfl-slate-700">
            {headline}
          </span>
        )}
      </div>
      <div className="grid grid-cols-1 gap-3 p-3 md:grid-cols-[60%_40%] xl:grid-cols-[55%_45%]">
        <div
          className={cn(
            'min-w-0 flex flex-col gap-3',
            scrollLeft && 'max-h-[28rem] overflow-y-auto pr-1',
          )}
        >
          {hasDescription && (
            <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50/60 p-2">
              <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
                Description of issue
              </div>
              <p className="text-[12.5px] text-pfl-slate-700 whitespace-pre-wrap leading-relaxed">
                {description}
              </p>
            </div>
          )}
          {left}
        </div>
        <div className="min-w-0">{rightContent}</div>
      </div>
    </div>
  )
}
