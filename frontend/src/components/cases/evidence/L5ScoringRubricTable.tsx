'use client'
/**
 * L5ScoringRubricTable — the 32-rubric audit rendered as one table
 * grouped by section. Replaces IssuesStrip + PassingRulesPanel for L5
 * only (other levels keep the catalog/issues split). Each row is
 * clickable; expanding shows the resolver evidence on the left and any
 * cited source artefacts on the right inside the standard
 * EvidenceTwoColumn shell — same grammar as every other level.
 *
 * Suppressed rows (admin-suppressed rules in
 * `sub_step_results.suppressed_rules`) render with strikethrough and a
 * "suppressed by admin" caption so the audit trail stays visible — never
 * silently dropped.
 *
 * Reads from `result.sub_step_results.scoring.sections[].rows[]`. No
 * backend change.
 */

import React, { useState } from 'react'
import { cn } from '@/lib/cn'
import type { LevelIssueRead, VerificationResultRead } from '@/lib/types'
import { EvidenceTwoColumn } from './EvidenceTwoColumn'
import { extractIssueSourceRefs, extractSourceArtifactRefs } from './_format'

type RubricRow = {
  sno?: number
  parameter?: string
  expected?: string | null
  evidence?: string | null
  remarks?: string | null
  weight?: number
  score?: number
  status?: string
  role?: string | null
  section?: string
  // Populated by L5 orchestrator for rows that pass on artifact-subtype
  // presence (#16, #17, #19, #21, #27, #28). Same shape as issue.evidence.source_artifacts.
  source_artifacts?: Array<{
    artifact_id: string
    filename?: string
    relevance?: string
    page?: number
    highlight_field?: string
  }>
}

type Section = {
  section_id?: string
  title?: string
  pct?: number
  earned?: number
  max_score?: number
  rows?: RubricRow[]
}

const STATUS_TONE: Record<
  string,
  { label: string; cls: string; rowCls: string }
> = {
  PASS: {
    label: 'PASS',
    cls: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    rowCls: 'bg-white hover:bg-emerald-50/30',
  },
  FAIL: {
    label: 'FAIL',
    cls: 'bg-red-50 text-red-700 border-red-200',
    rowCls: 'bg-red-50/40 hover:bg-red-50/70',
  },
  PENDING: {
    label: 'PENDING',
    cls: 'bg-amber-50 text-amber-800 border-amber-200',
    rowCls: 'bg-amber-50/40 hover:bg-amber-50/70',
  },
  WARN: {
    label: 'WARN',
    cls: 'bg-amber-50 text-amber-800 border-amber-200',
    rowCls: 'bg-amber-50/40 hover:bg-amber-50/70',
  },
  WARNING: {
    label: 'WARN',
    cls: 'bg-amber-50 text-amber-800 border-amber-200',
    rowCls: 'bg-amber-50/40 hover:bg-amber-50/70',
  },
}

function statusTone(status: string | undefined) {
  return (
    STATUS_TONE[(status ?? '').toUpperCase()] ?? {
      label: (status ?? '—').toUpperCase(),
      cls: 'bg-pfl-slate-100 text-pfl-slate-700 border-pfl-slate-200',
      rowCls: 'bg-white',
    }
  )
}

function pctBarTone(pct: number) {
  if (pct >= 80) return 'bg-emerald-500'
  if (pct >= 60) return 'bg-amber-500'
  return 'bg-red-500'
}

export function L5ScoringRubricTable({
  caseId,
  result,
  issues,
}: {
  caseId: string
  result: VerificationResultRead | undefined
  issues: LevelIssueRead[]
}) {
  const ssr = (result?.sub_step_results ?? {}) as Record<string, unknown>
  const scoring = (ssr['scoring'] ?? {}) as { sections?: Section[] }
  const sections = scoring.sections ?? []
  const suppressedRules = new Set<string>(
    (ssr['suppressed_rules'] as string[] | undefined) ?? [],
  )

  // Build a rubric_id → issue map so a row can find its corresponding
  // LevelIssue (carrying source_artifacts + assessor/MD state).
  const issueByRubric = new Map<string, LevelIssueRead>()
  for (const iss of issues) {
    const m = iss.sub_step_id.match(/^scoring_(\d{2})/)
    if (m) issueByRubric.set(m[1], iss)
  }

  if (sections.length === 0) {
    return (
      <div className="rounded border border-dashed border-pfl-slate-200 bg-pfl-slate-50/40 p-3 text-[12px] italic text-pfl-slate-500">
        Scoring rubric not yet populated. Trigger L5 to refresh.
      </div>
    )
  }

  const totalRows = sections.reduce((acc, s) => acc + (s.rows?.length ?? 0), 0)
  const passCount = sections.reduce(
    (acc, s) =>
      acc + (s.rows ?? []).filter((r) => r.status?.toUpperCase() === 'PASS').length,
    0,
  )

  return (
    <div className="rounded border border-pfl-slate-200 bg-white overflow-hidden">
      <div className="px-3 py-2 border-b border-pfl-slate-100 flex items-center gap-2 text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-600">
        <span>32-Rubric Audit</span>
        <span className="ml-auto font-mono normal-case tracking-normal text-pfl-slate-700">
          {passCount} / {totalRows} passing
        </span>
      </div>
      <div className="flex flex-col">
        {sections.map((section) => (
          <SectionGroup
            key={section.section_id ?? Math.random()}
            section={section}
            caseId={caseId}
            issueByRubric={issueByRubric}
            suppressedRules={suppressedRules}
          />
        ))}
      </div>
    </div>
  )
}

function SectionGroup({
  section,
  caseId,
  issueByRubric,
  suppressedRules,
}: {
  section: Section
  caseId: string
  issueByRubric: Map<string, LevelIssueRead>
  suppressedRules: Set<string>
}) {
  const rows = section.rows ?? []
  const hasNonPass = rows.some(
    (r) => (r.status ?? '').toUpperCase() !== 'PASS',
  )
  // Auto-expand sections that have any non-pass row; collapse clean
  // sections so the analyst's eye lands on the failing rows first.
  const [open, setOpen] = useState(hasNonPass)

  const pct = section.pct ?? 0
  const earned = section.earned ?? 0
  const max = section.max_score ?? 0

  return (
    <div className="border-t border-pfl-slate-100 first:border-t-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="w-full px-3 py-2 flex items-center gap-2 text-left hover:bg-pfl-slate-50"
      >
        <span className="text-pfl-slate-400 text-[11px] select-none">
          {open ? '▾' : '▸'}
        </span>
        <span className="font-mono text-[11px] uppercase font-bold text-pfl-slate-500 w-4">
          {section.section_id ?? '?'}
        </span>
        <span className="text-[12.5px] font-semibold text-pfl-slate-900">
          {section.title ?? '—'}
        </span>
        <span className="ml-auto flex items-center gap-3">
          <span className="font-mono tabular-nums text-[11.5px] text-pfl-slate-700">
            {earned}/{max}
          </span>
          <span className="font-mono tabular-nums text-[11.5px] text-pfl-slate-700 w-12 text-right">
            {pct.toFixed(0)}%
          </span>
          <div className="h-1.5 w-24 rounded-full bg-pfl-slate-200 overflow-hidden">
            <div
              className={cn('h-full rounded-full', pctBarTone(pct))}
              style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
            />
          </div>
        </span>
      </button>
      {open && (
        <div className="border-t border-pfl-slate-100">
          {rows.map((row) => {
            const sno = typeof row.sno === 'number' ? row.sno : 0
            const rubricKey = String(sno).padStart(2, '0')
            const isSuppressed =
              suppressedRules.has(`scoring_${rubricKey}`) ||
              suppressedRules.has(`scoring_${sno}`)
            const issue = issueByRubric.get(rubricKey)
            return (
              <RubricRowItem
                key={sno}
                row={row}
                rubricKey={rubricKey}
                caseId={caseId}
                issue={issue}
                suppressed={isSuppressed}
              />
            )
          })}
        </div>
      )}
    </div>
  )
}

function RubricRowItem({
  row,
  rubricKey,
  caseId,
  issue,
  suppressed,
}: {
  row: RubricRow
  rubricKey: string
  caseId: string
  issue: LevelIssueRead | undefined
  suppressed: boolean
}) {
  const [open, setOpen] = useState(false)
  const tone = statusTone(row.status)
  const verdict =
    (row.status ?? '').toUpperCase() === 'PASS'
      ? 'pass'
      : (row.status ?? '').toUpperCase() === 'FAIL'
      ? 'fail'
      : 'warn'

  // Issue-driven sources first (FAIL/PENDING rows have a LevelIssue with
  // source_artifacts in evidence). For PASS rows the orchestrator may still
  // attach per-row source_artifacts directly on the rubric row — surface those
  // so the assessor can verify the actual proof file rather than just trust the
  // PASS verdict.
  const sources = issue
    ? extractIssueSourceRefs(issue)
    : extractSourceArtifactRefs(row as unknown as Record<string, unknown>)

  return (
    <div className="border-t border-pfl-slate-100 first:border-t-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={cn(
          'w-full px-3 py-2 flex items-center gap-3 text-left transition-colors',
          tone.rowCls,
          suppressed && 'opacity-60',
        )}
      >
        <span className="text-pfl-slate-400 text-[11px] w-3 select-none">
          {open ? '▾' : '▸'}
        </span>
        <span className="font-mono text-[11px] text-pfl-slate-500 w-6 shrink-0">
          #{rubricKey}
        </span>
        <span
          className={cn(
            'text-[12.5px] font-medium text-pfl-slate-900 flex-1 min-w-0',
            suppressed && 'line-through',
          )}
        >
          {row.parameter ?? '—'}
          {suppressed && (
            <span className="ml-2 text-[10.5px] not-italic font-normal italic text-pfl-slate-500">
              · suppressed by admin
            </span>
          )}
        </span>
        <span
          className={cn(
            'inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider shrink-0',
            tone.cls,
          )}
        >
          {tone.label}
        </span>
        {typeof row.weight === 'number' && (
          <span className="font-mono tabular-nums text-[10.5px] text-pfl-slate-500 shrink-0 w-16 text-right">
            wt {row.weight}
            {typeof row.score === 'number' && <> · sc {row.score}</>}
          </span>
        )}
      </button>
      {open && (
        <div className="px-3 py-2 bg-pfl-slate-50/30 border-t border-pfl-slate-100">
          <EvidenceTwoColumn
            caseId={caseId}
            verdict={verdict}
            description={issue?.description?.trim() || undefined}
            sources={sources}
            left={<RubricResolverBody row={row} />}
          />
        </div>
      )}
    </div>
  )
}

function RubricResolverBody({ row }: { row: RubricRow }) {
  const fields: Array<[string, string | null | undefined]> = [
    ['Section', row.section ?? null],
    ['Role', row.role ?? null],
    ['Expected', row.expected ?? null],
    ['Evidence', row.evidence ?? null],
    ['Remarks', row.remarks ?? null],
  ].filter(([, v]) => typeof v === 'string' && v.trim().length > 0) as Array<
    [string, string]
  >
  if (fields.length === 0) {
    return (
      <div className="text-[12px] italic text-pfl-slate-500">
        No additional resolver detail on this rubric row.
      </div>
    )
  }
  return (
    <div className="grid grid-cols-[max-content,1fr] gap-x-3 gap-y-1 text-[12px]">
      {fields.map(([label, value]) => (
        <React.Fragment key={label}>
          <span className="font-medium text-pfl-slate-600">{label}</span>
          <span className="text-pfl-slate-800 whitespace-pre-wrap">{value}</span>
        </React.Fragment>
      ))}
    </div>
  )
}
