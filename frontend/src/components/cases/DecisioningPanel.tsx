/**
 * DecisioningPanel — "Verification 2" tab in the case detail page (formerly
 * "Phase 1"). API paths still read /phase1 to avoid a breaking URL change;
 * only the user-facing label + tab title were renamed after the 4-Level
 * Verification gate took on the grunt verification work.
 *
 * Shows:
 *  - "Start Verification 2" button when no run exists + case is INGESTED
 *  - Status badge (PENDING / RUNNING / COMPLETED / FAILED / CANCELLED)
 *  - 11-step progress table with model/status/duration per step
 *  - Final decision card when COMPLETED: outcome badge, recommended amount,
 *    confidence, conditions, reasoning markdown, pros/cons, deviations, risk
 *  - Cancel button (admin only) for PENDING/RUNNING runs
 */

'use client'

import React, { useState } from 'react'
import { cn } from '@/lib/cn'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cases as casesApi } from '@/lib/api'
import { useDecisionResult, useDecisionSteps } from '@/lib/useDecisioning'
import { useVerificationOverview } from '@/lib/useVerification'
import { useCamDiscrepancies } from '@/lib/useCamDiscrepancies'
import type {
  DecisionResultRead,
  DecisionStepRead,
  VerificationLevelNumber,
  VerificationLevelStatus,
} from '@/lib/types'
import type {
  CaseStage,
  DecisionStatus,
  DecisionOutcome,
  StepStatus,
} from '@/lib/enums'

// Anthropic responses with citations enabled return text as either a plain
// string, or `{text, citations}` objects, or arrays of those. Rendering such
// an object directly throws "Objects are not valid as a React child". This
// helper coerces any of those shapes into a displayable string.
function asText(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(asText).join('')
  if (typeof value === 'object') {
    const v = value as { text?: unknown; type?: unknown }
    if (typeof v.text === 'string') return v.text
  }
  return ''
}

/**
 * Split an Opus-generated risk summary into individual concerns.
 *
 * The LLM joins its findings with periods but often omits the trailing
 * space ("…within Hisar.Co-applicant is…"), so a naïve `split('.')`
 * drops words. We also collapse the rendered "unresolved 4-level
 * gates: ['L1_ADDRESS', 'L2_BANKING', …]" Python-list literal into a
 * readable bullet.
 */
function splitRiskSummary(s: string): string[] {
  if (!s) return []
  // Re-insert a space after any period (or !/?) that's immediately
  // followed by an alphanumeric character — this is how the LLM joins
  // sentences ("within Hisar.Co-applicant…", "capping confidence at
  // 70.unresolved 4-level gates…"). Common abbreviations like "e.g."
  // / "i.e." / "Mr." don't occur in this text corpus, so the liberal
  // split is safe.
  let normalised = s.replace(/([.!?])([A-Za-z0-9])/g, '$1 $2')
  // Soften the raw Python-list literal form of the gate list so the
  // sentence reads naturally: "unresolved 4-level gates: L1_ADDRESS,
  // L2_BANKING, …"
  normalised = normalised.replace(
    /\[\s*'([^']+)'(?:\s*,\s*'([^']+)')*\s*\]/g,
    (match) => match.replace(/[[\]']/g, ''),
  )
  // Now split on sentence terminators. Keep only non-empty trimmed
  // fragments — and re-attach the terminator so the line still reads
  // as a sentence.
  const parts = normalised
    .split(/(?<=[.!?])\s+/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0)
  return parts
}

/**
 * Colour the confidence bar: below 50% is red (decision is weak-signal),
 * 50-70% is amber (borderline — MD escalation range), ≥70% is green.
 */
function confidencePalette(pct: number): { bar: string; text: string } {
  if (pct < 50) return { bar: 'bg-red-500', text: 'text-red-700' }
  if (pct < 70) return { bar: 'bg-amber-500', text: 'text-amber-700' }
  return { bar: 'bg-emerald-500', text: 'text-emerald-700' }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/**
 * Parse an Opus-generated ``reasoning_markdown`` blob into its top-level
 * ``### Heading`` sections. The raw text looks like
 *
 *   ## Decision Rationale
 *   ### 4-Level Verification Gate
 *   …paragraph…
 *   ### Policy Violations / Deviations
 *   1. …
 *   2. …
 *   ### Why not REJECT outright
 *   …paragraph…
 *   ### Confidence
 *   …one sentence…
 *
 * We split into [{title, body}] so the UI can render each one as a
 * labelled card instead of dumping 40 lines of monospace text.
 * Headings that aren't present are simply absent from the output.
 */
interface ReasoningSectionData {
  title: string
  body: string
}
function parseReasoningSections(md: string): ReasoningSectionData[] {
  if (!md) return []
  const out: ReasoningSectionData[] = []
  const lines = md.split('\n')
  let current: ReasoningSectionData | null = null
  const headingRe = /^#{2,4}\s+(.+?)\s*$/
  for (const line of lines) {
    const m = line.match(headingRe)
    if (m) {
      // Skip the top-level "Decision Rationale" title — redundant.
      const title = m[1].trim()
      if (title.toLowerCase() === 'decision rationale') continue
      if (current) out.push(current)
      current = { title, body: '' }
    } else if (current) {
      current.body += (current.body ? '\n' : '') + line
    }
  }
  if (current) out.push(current)
  // Strip trailing blank lines from each body; drop sections that ended
  // up empty (heading with no content).
  return out
    .map((s) => ({ title: s.title, body: s.body.replace(/\s+$/, '') }))
    .filter((s) => s.body.length > 0)
}

/**
 * Render Opus's decision rationale as structured cards (one per ``###``
 * heading), with the original raw markdown tucked behind a collapsible
 * "Show full rationale" toggle for auditors who want it verbatim.
 *
 * Deliberately no markdown renderer — the bodies are short paragraphs
 * or numbered lists; ``whitespace-pre-wrap`` preserves the line breaks
 * and the occasional ``**bold**`` / backtick marker without pulling in
 * ReactMarkdown + its CSS for a few dozen characters of content.
 */
function ReasoningSection({ reasoning }: { reasoning: string }) {
  const [showRaw, setShowRaw] = React.useState(false)
  const sections = React.useMemo(() => parseReasoningSections(reasoning), [reasoning])

  if (sections.length === 0 && !reasoning.trim()) return null

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-semibold text-slate-700 uppercase tracking-wide">
          Decision Rationale
        </h4>
        <button
          type="button"
          onClick={() => setShowRaw((v) => !v)}
          className="text-[11px] font-medium text-slate-600 hover:text-slate-900"
        >
          {showRaw ? 'Show structured ◂' : 'Show full rationale ▸'}
        </button>
      </div>

      {!showRaw && sections.length > 0 && (
        <div className="flex flex-col gap-2">
          {sections.map((s, i) => (
            <div
              key={i}
              className="rounded border border-slate-200 bg-white px-3 py-2"
            >
              <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-1">
                {s.title}
              </div>
              <div className="text-[12.5px] text-slate-800 whitespace-pre-wrap leading-relaxed">
                {s.body}
              </div>
            </div>
          ))}
        </div>
      )}

      {!showRaw && sections.length === 0 && (
        // No parsable headings — fall back to the raw text but in the
        // same readable typography as the structured view.
        <div className="rounded border border-slate-200 bg-white px-3 py-2 text-[12.5px] text-slate-800 whitespace-pre-wrap leading-relaxed">
          {reasoning}
        </div>
      )}

      {showRaw && (
        <div
          className="prose prose-sm max-w-none text-slate-700 bg-slate-50 rounded p-3 whitespace-pre-wrap font-mono text-xs"
          data-testid="reasoning-markdown"
        >
          {reasoning}
        </div>
      )}
    </div>
  )
}

function DecisionStatusBadge({ status }: { status: string }) {
  const classes: Record<string, string> = {
    PENDING: 'bg-amber-100 text-amber-800',
    RUNNING: 'bg-blue-100 text-blue-800 animate-pulse',
    COMPLETED: 'bg-green-100 text-green-800',
    FAILED: 'bg-red-100 text-red-700',
    CANCELLED: 'bg-slate-100 text-slate-600',
  }
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold',
        classes[status] ?? 'bg-slate-100 text-slate-700',
      )}
      data-testid="decision-status-badge"
    >
      {status}
    </span>
  )
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const classes: Record<string, string> = {
    APPROVE: 'bg-green-200 text-green-900',
    APPROVE_WITH_CONDITIONS: 'bg-emerald-100 text-emerald-800',
    REJECT: 'bg-red-200 text-red-900',
    ESCALATE_TO_CEO: 'bg-pink-100 text-pink-800',
  }
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-3 py-1 text-sm font-bold',
        classes[outcome] ?? 'bg-slate-100 text-slate-700',
      )}
      data-testid="outcome-badge"
    >
      {outcome.replace(/_/g, ' ')}
    </span>
  )
}

function StepStatusDot({ status }: { status: string }) {
  const classes: Record<string, string> = {
    PENDING: 'bg-slate-300',
    RUNNING: 'bg-blue-500 animate-pulse',
    SUCCEEDED: 'bg-green-500',
    FAILED: 'bg-red-500',
    SKIPPED: 'bg-amber-300',
  }
  return (
    <span
      className={cn(
        'inline-block h-2.5 w-2.5 rounded-full shrink-0',
        classes[status] ?? 'bg-slate-300',
      )}
      aria-label={status}
    />
  )
}

function formatDuration(start: string | null | undefined, end: string | null | undefined): string {
  if (!start || !end) return '—'
  try {
    const ms = new Date(end).getTime() - new Date(start).getTime()
    if (ms < 1000) return `${ms}ms`
    return `${(ms / 1000).toFixed(1)}s`
  } catch {
    return '—'
  }
}

function formatCurrency(value: number | null | undefined): string {
  if (value == null) return '—'
  return `₹ ${value.toLocaleString('en-IN')}`
}

/** Compact number formatter: 1234 → "1.2k", 125 → "125". */
function fmtCompact(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n === 0) return '0'
  if (n < 1000) return String(n)
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`
  return `${(n / 1_000_000).toFixed(1)}M`
}

/** Formatter for USD micro-amounts: $0.00134 → "$0.0013", $0.10 → "$0.10". */
function fmtUsd(value: string | number | null | undefined, digits = 4): string {
  if (value == null || value === '') return '—'
  const n = typeof value === 'number' ? value : parseFloat(value)
  if (isNaN(n)) return '—'
  return `$${n.toFixed(digits)}`
}

/** Sum numeric fields across steps. */
function sumField(steps: DecisionStepRead[], field: keyof DecisionStepRead): number {
  return steps.reduce((acc, s) => {
    const v = s[field]
    const n = typeof v === 'number' ? v : v != null ? Number(v) : 0
    return acc + (isNaN(n) ? 0 : n)
  }, 0)
}

/** Group steps by model tier (haiku / sonnet / opus / other) for a per-tier
 * cost + token breakdown — useful for understanding where API spend goes. */
function groupByTier(steps: DecisionStepRead[]): Array<{
  tier: string
  count: number
  inputTokens: number
  outputTokens: number
  cacheReadTokens: number
  cacheCreationTokens: number
  costUsd: number
}> {
  const groups = new Map<string, { count: number; input: number; output: number; cacheR: number; cacheW: number; cost: number }>()
  for (const s of steps) {
    const tier = inferTier(s.model_used)
    const g = groups.get(tier) ?? { count: 0, input: 0, output: 0, cacheR: 0, cacheW: 0, cost: 0 }
    g.count += 1
    g.input += Number(s.input_tokens ?? 0)
    g.output += Number(s.output_tokens ?? 0)
    g.cacheR += Number(s.cache_read_tokens ?? 0)
    g.cacheW += Number(s.cache_creation_tokens ?? 0)
    g.cost += s.cost_usd != null ? parseFloat(s.cost_usd) : 0
    groups.set(tier, g)
  }
  const order: Record<string, number> = { opus: 0, sonnet: 1, haiku: 2, other: 3 }
  return Array.from(groups.entries())
    .map(([tier, g]) => ({
      tier,
      count: g.count,
      inputTokens: g.input,
      outputTokens: g.output,
      cacheReadTokens: g.cacheR,
      cacheCreationTokens: g.cacheW,
      costUsd: g.cost,
    }))
    .sort((a, b) => (order[a.tier] ?? 9) - (order[b.tier] ?? 9))
}

function inferTier(model: string | null | undefined): string {
  if (!model) return 'other'
  const m = model.toLowerCase()
  if (m.includes('opus')) return 'opus'
  if (m.includes('sonnet')) return 'sonnet'
  if (m.includes('haiku')) return 'haiku'
  return 'other'
}

// ---------------------------------------------------------------------------
// Token + Cost summary card
// ---------------------------------------------------------------------------

interface UsageSummaryProps {
  steps: DecisionStepRead[]
  totalCostUsd: string | null
}

function UsageSummary({ steps, totalCostUsd }: UsageSummaryProps) {
  const inputTotal = sumField(steps, 'input_tokens')
  const outputTotal = sumField(steps, 'output_tokens')
  const cacheReadTotal = sumField(steps, 'cache_read_tokens')
  const cacheWriteTotal = sumField(steps, 'cache_creation_tokens')
  const computedCost = sumField(steps, 'cost_usd' as keyof DecisionStepRead)
  const costDisplay = totalCostUsd != null ? parseFloat(totalCostUsd) : computedCost
  const cacheHitPct =
    inputTotal + cacheReadTotal > 0
      ? (cacheReadTotal / (inputTotal + cacheReadTotal)) * 100
      : 0
  const tiers = groupByTier(steps)

  return (
    <Card className="mb-4" data-testid="usage-summary">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold text-slate-800">API Usage & Cost</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {/* Top-line numbers */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <StatCell label="Total Cost" value={fmtUsd(costDisplay, 4)} highlight />
          <StatCell label="Input Tokens" value={fmtCompact(inputTotal)} />
          <StatCell label="Output Tokens" value={fmtCompact(outputTotal)} />
          <StatCell label="Cache Read" value={fmtCompact(cacheReadTotal)} sub={`${cacheHitPct.toFixed(0)}% hit`} />
          <StatCell label="Cache Write" value={fmtCompact(cacheWriteTotal)} />
        </div>

        {/* Per-tier breakdown */}
        {tiers.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs border-collapse" data-testid="usage-by-tier">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500 uppercase tracking-wide">
                  <th className="py-1.5 pr-3">Tier</th>
                  <th className="py-1.5 pr-3">Steps</th>
                  <th className="py-1.5 pr-3 text-right">Input</th>
                  <th className="py-1.5 pr-3 text-right">Output</th>
                  <th className="py-1.5 pr-3 text-right">Cache R/W</th>
                  <th className="py-1.5 pr-3 text-right">Cost</th>
                  <th className="py-1.5 pr-3 text-right">% of total</th>
                </tr>
              </thead>
              <tbody>
                {tiers.map((t) => (
                  <tr key={t.tier} className="border-b border-slate-100 last:border-0">
                    <td className="py-1.5 pr-3 font-medium capitalize">{t.tier}</td>
                    <td className="py-1.5 pr-3 text-slate-500">{t.count}</td>
                    <td className="py-1.5 pr-3 text-right font-mono text-slate-600">{fmtCompact(t.inputTokens)}</td>
                    <td className="py-1.5 pr-3 text-right font-mono text-slate-600">{fmtCompact(t.outputTokens)}</td>
                    <td className="py-1.5 pr-3 text-right font-mono text-slate-600">
                      {fmtCompact(t.cacheReadTokens)} / {fmtCompact(t.cacheCreationTokens)}
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono font-semibold text-slate-800">
                      {fmtUsd(t.costUsd, 4)}
                    </td>
                    <td className="py-1.5 pr-3 text-right text-slate-500">
                      {costDisplay > 0 ? `${((t.costUsd / costDisplay) * 100).toFixed(0)}%` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function StatCell({
  label,
  value,
  sub,
  highlight,
}: {
  label: string
  value: string
  sub?: string
  highlight?: boolean
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] text-slate-500 uppercase tracking-wide">{label}</span>
      <span
        className={cn(
          'font-mono',
          highlight ? 'text-base font-bold text-slate-900' : 'text-sm text-slate-800',
        )}
      >
        {value}
      </span>
      {sub && <span className="text-[10px] text-slate-400">{sub}</span>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step rows table
// ---------------------------------------------------------------------------

interface StepTableProps {
  steps: DecisionStepRead[]
}

function StepTable({ steps }: StepTableProps) {
  if (steps.length === 0) {
    return (
      <p className="text-sm text-slate-500 italic" data-testid="steps-empty">
        No steps have run yet.
      </p>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse" data-testid="steps-table">
        <thead>
          <tr className="border-b border-slate-200 text-left text-slate-500 uppercase tracking-wide">
            <th className="py-2 pr-3 w-8">#</th>
            <th className="py-2 pr-3">Step</th>
            <th className="py-2 pr-3">Model</th>
            <th className="py-2 pr-3">Status</th>
            <th className="py-2 pr-3">Duration</th>
            <th className="py-2 pr-3 text-right">Input</th>
            <th className="py-2 pr-3 text-right">Output</th>
            <th className="py-2 pr-3 text-right" title="Cache read / write tokens">
              Cache&nbsp;R/W
            </th>
            <th className="py-2 pr-3 text-right">Cost (USD)</th>
          </tr>
        </thead>
        <tbody>
          {steps.map((s) => {
            const isSkipped = s.status === 'SKIPPED'
            const coveredBy =
              isSkipped && s.output_data && typeof s.output_data === 'object'
                ? (s.output_data as Record<string, unknown>).covered_by
                : null
            return (
              <tr
                key={s.id}
                className={cn(
                  'border-b border-slate-100 last:border-0',
                  isSkipped ? 'bg-slate-50/60 text-slate-500' : 'hover:bg-slate-50',
                )}
                data-testid={`step-row-${s.step_number}`}
              >
                <td className="py-2 pr-3 font-mono text-slate-400">{s.step_number}</td>
                <td className="py-2 pr-3 font-medium text-slate-800">
                  <div className="flex flex-col gap-0.5">
                    <span>{s.step_name}</span>
                    {isSkipped && typeof coveredBy === 'string' && (
                      <span className="text-[10px] text-slate-500 italic">
                        covered by {coveredBy}
                      </span>
                    )}
                  </div>
                </td>
                <td className="py-2 pr-3 text-slate-500 font-mono">{s.model_used ?? '—'}</td>
                <td className="py-2 pr-3">
                  <div className="flex items-center gap-1.5">
                    <StepStatusDot status={s.status} />
                    <span>{s.status}</span>
                  </div>
                </td>
                <td className="py-2 pr-3 text-slate-500">
                  {isSkipped ? '—' : formatDuration(s.started_at, s.completed_at)}
                </td>
                <td className="py-2 pr-3 text-right text-slate-600 font-mono">
                  {fmtCompact(s.input_tokens)}
                </td>
                <td className="py-2 pr-3 text-right text-slate-600 font-mono">
                  {fmtCompact(s.output_tokens)}
                </td>
                <td className="py-2 pr-3 text-right text-slate-500 font-mono">
                  {fmtCompact(s.cache_read_tokens)} / {fmtCompact(s.cache_creation_tokens)}
                </td>
                <td className="py-2 pr-3 text-right text-slate-800 font-mono font-semibold">
                  {fmtUsd(s.cost_usd, 4)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Final decision card
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Level status row — 6 mini-tiles (L1, L1.5, L2, L3, L4, L5) sitting under
// the verdict hero. Each tile shows the level pill + status badge and on
// click scrolls to that level's expand in the verification panel above.
// Lets an MD reviewer triage a case at a glance: which levels are clean,
// which ones the verdict was capped on, where to drill.
// ---------------------------------------------------------------------------

const LEVEL_TILE_META: Array<{ level: VerificationLevelNumber; label: string }> = [
  { level: 'L1_ADDRESS', label: 'L1' },
  { level: 'L1_5_CREDIT', label: 'L1.5' },
  { level: 'L2_BANKING', label: 'L2' },
  { level: 'L3_VISION', label: 'L3' },
  { level: 'L4_AGREEMENT', label: 'L4' },
  { level: 'L5_SCORING', label: 'L5' },
  { level: 'L5_5_DEDUPE_TVR', label: 'L5.5' },
]

function statusToTone(
  status: VerificationLevelStatus | null | undefined,
): { label: string; cls: string } {
  if (status === 'PASSED')
    return {
      label: 'PASS',
      cls: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    }
  if (status === 'PASSED_WITH_MD_OVERRIDE')
    return {
      label: 'MD OVR',
      cls: 'bg-indigo-50 text-indigo-700 border-indigo-200',
    }
  if (status === 'BLOCKED')
    return { label: 'BLOCKED', cls: 'bg-red-50 text-red-700 border-red-200' }
  if (status === 'FAILED')
    return { label: 'FAILED', cls: 'bg-red-50 text-red-700 border-red-200' }
  return {
    label: 'PENDING',
    cls: 'bg-slate-50 text-slate-600 border-slate-200',
  }
}

function LevelStatusRow({ caseId }: { caseId: string }) {
  const { data: overview, isLoading } = useVerificationOverview(caseId)
  const byLevel = new Map<VerificationLevelNumber, VerificationLevelStatus>()
  for (const lvl of overview?.levels ?? []) {
    byLevel.set(lvl.level_number, lvl.status)
  }

  const onClick = (level: VerificationLevelNumber) => {
    const el = document.getElementById(`level-${level}`)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    // Flash a focus ring so the user knows where they landed
    el.classList.add('ring-2', 'ring-pfl-blue-400', 'ring-offset-2')
    window.setTimeout(
      () => el.classList.remove('ring-2', 'ring-pfl-blue-400', 'ring-offset-2'),
      1500,
    )
  }

  return (
    <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-7">
      {LEVEL_TILE_META.map(({ level, label }) => {
        const status = byLevel.get(level)
        const tone = statusToTone(status)
        return (
          <button
            key={level}
            type="button"
            onClick={() => onClick(level)}
            disabled={isLoading}
            className={cn(
              'flex flex-col items-start gap-1 rounded border px-2 py-2 text-left transition hover:shadow-sm hover:border-slate-400 disabled:opacity-60',
              tone.cls,
            )}
            title={`Jump to ${label} expand`}
          >
            <span className="text-[11px] font-bold uppercase tracking-wider">
              {label}
            </span>
            <span className="text-[10px] font-bold tracking-wider">
              {tone.label}
            </span>
          </button>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Collapsible section wrapper — uses the native <details> element so we
// don't pull in animation libs for a one-line UX. Defaults open or closed
// based on `defaultOpen` (Risk Summary / Deviations are noisy on clean
// cases — closed by default; Conditions are actionable — open by default).
// ---------------------------------------------------------------------------

function CollapsibleSection({
  title,
  hint,
  defaultOpen = false,
  children,
}: {
  title: string
  hint?: string
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  return (
    <details open={defaultOpen} className="group rounded border border-slate-200 bg-white">
      <summary className="cursor-pointer list-none px-3 py-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-700 hover:bg-slate-50">
        <span className="text-slate-400 transition-transform group-open:rotate-90">▸</span>
        <span>{title}</span>
        {hint && (
          <span className="font-normal normal-case text-slate-400 text-[11px]">
            · {hint}
          </span>
        )}
      </summary>
      <div className="px-3 py-2 border-t border-slate-100">{children}</div>
    </details>
  )
}

interface DecisionCardProps {
  dr: DecisionResultRead
  caseId: string
}

function DecisionCard({ dr, caseId }: DecisionCardProps) {
  const confidencePct = typeof dr.confidence_score === 'number' ? dr.confidence_score : null
  const confidenceStyle =
    confidencePct != null ? confidencePalette(confidencePct) : null
  const riskLines = splitRiskSummary(asText(dr.risk_summary))
  return (
    <Card className="mt-4" data-testid="decision-card">
      <CardHeader>
        <CardTitle className="text-base">Final Decision</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {/* Hero banner — the single most load-bearing piece of the L6
            output. Large outcome badge, then the three numbers the MD
            actually acts on (amount · tenure · confidence), with a
            coloured confidence bar so the weak / borderline / strong
            signal is visible at a glance. Total cost is demoted to a
            muted trailing line since it's operational, not decisive. */}
        <div className="flex flex-col gap-3 rounded-md border border-slate-200 bg-slate-50 p-4">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              Verdict
            </span>
            {dr.final_decision && <OutcomeBadge outcome={dr.final_decision} />}
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="flex flex-col gap-0.5">
              <span className="text-[10.5px] text-slate-500 uppercase tracking-wider">
                Recommended amount
              </span>
              <span className="text-[15px] font-semibold text-slate-900">
                {formatCurrency(dr.recommended_amount)}
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-[10.5px] text-slate-500 uppercase tracking-wider">
                Tenure
              </span>
              <span className="text-[15px] font-semibold text-slate-900">
                {dr.recommended_tenure != null
                  ? `${dr.recommended_tenure} months`
                  : '—'}
              </span>
            </div>
            <div className="flex flex-col gap-1">
              <div className="flex items-center justify-between">
                <span className="text-[10.5px] text-slate-500 uppercase tracking-wider">
                  Confidence
                </span>
                <span
                  className={cn(
                    'text-[12px] font-semibold',
                    confidenceStyle?.text ?? 'text-slate-700',
                  )}
                >
                  {confidencePct != null ? `${confidencePct}%` : '—'}
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-slate-200 overflow-hidden">
                {confidencePct != null && (
                  <div
                    className={cn('h-full rounded-full', confidenceStyle?.bar)}
                    style={{ width: `${Math.max(0, Math.min(100, confidencePct))}%` }}
                  />
                )}
              </div>
            </div>
          </div>
          <div className="text-[11px] text-slate-500">
            Compute cost:{' '}
            <span className="font-mono">
              {dr.total_cost_usd != null
                ? `$${parseFloat(dr.total_cost_usd).toFixed(4)}`
                : '—'}
            </span>
          </div>
        </div>

        {/* Per-level quick-stat row — the single most useful triage
            view for an MD reviewer: 6 tiles showing pass/blocked/MD-
            override at a glance, click to scroll to that level above. */}
        <LevelStatusRow caseId={caseId} />

        {/* Conditions — actionable, default-open. One bullet per
            condition, each rendered as its own block so long
            explanations wrap cleanly. */}
        {Array.isArray(dr.conditions) && (dr.conditions as unknown[]).length > 0 && (
          <CollapsibleSection
            title="Conditions"
            hint="what must be cleared"
            defaultOpen
          >
            <ul
              className="flex flex-col gap-1.5 text-sm text-slate-800"
              data-testid="conditions-list"
            >
              {(dr.conditions as unknown[]).map((c, i) => (
                <li
                  key={i}
                  className="flex gap-2 rounded border border-slate-200 bg-white px-3 py-2 leading-snug"
                >
                  <span className="text-slate-400 mt-0.5">·</span>
                  <span>{asText(c)}</span>
                </li>
              ))}
            </ul>
          </CollapsibleSection>
        )}

        {/* Risk summary — split the LLM-joined prose into one bullet
            per concern. Closed by default to keep the page calm; click
            to drill. */}
        {riskLines.length > 0 && (
          <CollapsibleSection
            title="Risk Summary"
            hint={`${riskLines.length} concern${riskLines.length === 1 ? '' : 's'} · why confidence is capped`}
          >
            <ul
              className="flex flex-col gap-1.5 text-sm text-slate-800"
              data-testid="risk-summary"
            >
              {riskLines.map((line, i) => (
                <li
                  key={i}
                  className="flex gap-2 rounded border border-amber-200 bg-amber-50/60 px-3 py-2 leading-snug"
                >
                  <span className="text-amber-600 mt-0.5">!</span>
                  <span>{line}</span>
                </li>
              ))}
            </ul>
          </CollapsibleSection>
        )}

        {/* Pros / Cons — collapsed by default. Useful for auditors,
            not load-bearing for the MD verdict. */}
        {dr.pros_cons != null && (
          <CollapsibleSection title="Pros / Cons">
            <div className="overflow-x-auto" data-testid="pros-cons-table">
              {typeof dr.pros_cons === 'object' && dr.pros_cons !== null ? (
                <table className="w-full text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-slate-200">
                      <th className="py-1 pr-4 text-left text-green-700">Pros</th>
                      <th className="py-1 text-left text-red-700">Cons</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td className="py-2 pr-4 align-top text-slate-700">
                        {Array.isArray((dr.pros_cons as Record<string, unknown>).pros) ? (
                          <ul className="list-disc list-inside space-y-0.5">
                            {((dr.pros_cons as Record<string, unknown>).pros as unknown[]).map((p, i) => (
                              <li key={i}>{asText(p)}</li>
                            ))}
                          </ul>
                        ) : null}
                      </td>
                      <td className="py-2 align-top text-slate-700">
                        {Array.isArray((dr.pros_cons as Record<string, unknown>).cons) ? (
                          <ul className="list-disc list-inside space-y-0.5">
                            {((dr.pros_cons as Record<string, unknown>).cons as unknown[]).map((c, i) => (
                              <li key={i}>{asText(c)}</li>
                            ))}
                          </ul>
                        ) : null}
                      </td>
                    </tr>
                  </tbody>
                </table>
              ) : (
                <span className="text-slate-500">{String(dr.pros_cons)}</span>
              )}
            </div>
          </CollapsibleSection>
        )}

        {/* Policy Deviations — collapsed by default; only renders when
            real entries exist (the LLM sometimes emits null sentinels). */}
        {(() => {
          const devs = Array.isArray(dr.deviations)
            ? (dr.deviations as unknown[])
                .map((d) => asText(d).trim())
                .filter((s) => s.length > 0)
            : []
          if (devs.length === 0) return null
          return (
            <CollapsibleSection
              title="Policy Deviations"
              hint={`${devs.length} flagged`}
            >
              <ul
                className="list-disc list-inside text-sm text-amber-800 space-y-1"
                data-testid="deviations-list"
              >
                {devs.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            </CollapsibleSection>
          )
        })()}

        {/* Decision Rationale — parsed from reasoning_markdown into
            structured sections the MD can scan quickly. The raw
            markdown (with code-block formatting) stays available
            behind the "Show full rationale" toggle so auditors can
            still read it verbatim. */}
        {dr.reasoning_markdown && (
          <ReasoningSection reasoning={asText(dr.reasoning_markdown)} />
        )}

        {/* Error message */}
        {dr.error_message && (
          <div
            className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
            data-testid="error-message"
          >
            {dr.error_message}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

interface DecisioningPanelProps {
  caseId: string
  currentStage: CaseStage
  isAdmin: boolean
}

export function DecisioningPanel({ caseId, currentStage, isAdmin }: DecisioningPanelProps) {
  const { data: dr, error: drError, isLoading: drLoading, mutate: mutateDr } = useDecisionResult(caseId)
  const hasResult = !!dr && !drError
  const isActive = hasResult && (dr.status === 'PENDING' || dr.status === 'RUNNING')
  const { data: steps, isLoading: stepsLoading } = useDecisionSteps(caseId, hasResult)

  const [starting, setStarting] = useState(false)
  const [canceling, setCanceling] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  // API usage + pipeline steps are operational telemetry — useful for
  // auditors but not load-bearing on the MD's decision. Collapsed by
  // default so the Final Decision / Rationale / Pros+Cons stay front-and-
  // centre. Remembers open/close state within the session.
  const [usageOpen, setUsageOpen] = useState(false)
  const [stepsOpen, setStepsOpen] = useState(false)

  // Phase 1 gate — block the Start button when CRITICAL CAM discrepancies
  // are unresolved. Backend already 409s on the POST, but surfacing the
  // state in the button gives the reviewer an instant explanation.
  const { data: discSummary } = useCamDiscrepancies(caseId, { refreshInterval: 0 })
  const discBlocked = !!discSummary?.phase1_blocked
  const discCriticalCount = discSummary?.unresolved_critical ?? 0

  async function handleStart() {
    setStarting(true)
    setActionError(null)
    try {
      await casesApi.phase1Start(caseId)
      await mutateDr()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Failed to start Verification 2')
    } finally {
      setStarting(false)
    }
  }

  async function handleCancel() {
    setCanceling(true)
    setActionError(null)
    try {
      await casesApi.phase1Cancel(caseId)
      await mutateDr()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Failed to cancel')
    } finally {
      setCanceling(false)
    }
  }

  // SKIPPED steps are legacy — they've been absorbed by the 6-level
  // verification gate and carry no model, no tokens, no cost. Filter them
  // out of the visible pipeline + tier breakdown so the table only shows
  // rows the model actually ran.
  const activeSteps = (steps ?? []).filter((s) => s.status !== 'SKIPPED')
  const skippedCount = (steps ?? []).length - activeSteps.length

  return (
    <div className="flex flex-col gap-4" data-testid="decisioning-panel">
      {/* Header row */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-slate-700">Verification 2</h3>
          {hasResult && <DecisionStatusBadge status={dr.status} />}
        </div>

        <div className="flex items-center gap-2">
          {/* Start button — only when no result yet and case is INGESTED.
              Disabled + tooltip when CAM discrepancies block the gate. */}
          {!hasResult && !drLoading && currentStage === 'INGESTED' && (
            <span
              title={
                discBlocked
                  ? `Resolve ${discCriticalCount} CRITICAL CAM discrepanc${
                      discCriticalCount === 1 ? 'y' : 'ies'
                    } on the Discrepancies tab first.`
                  : undefined
              }
              data-testid="start-phase1-btn-wrapper"
            >
              <button
                onClick={handleStart}
                disabled={starting || discBlocked}
                aria-disabled={starting || discBlocked}
                className={cn(
                  'rounded px-3 py-1.5 text-sm font-medium text-white',
                  discBlocked
                    ? 'bg-slate-400 cursor-not-allowed'
                    : 'bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50',
                )}
                data-testid="start-phase1-btn"
              >
                {starting
                  ? 'Starting…'
                  : discBlocked
                  ? `Start Verification 2 (${discCriticalCount} blocking)`
                  : 'Start Verification 2'}
              </button>
            </span>
          )}

          {/* Cancel button — admin only, for active runs */}
          {isAdmin && isActive && (
            <button
              onClick={handleCancel}
              disabled={canceling}
              className="rounded border border-red-300 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
              data-testid="cancel-phase1-btn"
            >
              {canceling ? 'Canceling…' : 'Cancel'}
            </button>
          )}
        </div>
      </div>

      {/* Action error */}
      {actionError && (
        <div
          role="alert"
          className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
          data-testid="action-error"
        >
          {actionError}
        </div>
      )}

      {/* Loading skeleton */}
      {drLoading && (
        <div className="flex flex-col gap-2" data-testid="dr-loading">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-32 w-full" />
        </div>
      )}

      {/* No result yet */}
      {!drLoading && !hasResult && currentStage !== 'INGESTED' && (
        <p className="text-sm text-slate-500 italic" data-testid="no-result-msg">
          Verification 2 has not been started for this case.
        </p>
      )}

      {!drLoading && !hasResult && currentStage === 'INGESTED' && (
        <p className="text-sm text-slate-500" data-testid="ready-msg">
          This case is ready for Verification 2. Click &quot;Start Verification 2&quot; to begin.
        </p>
      )}

      {/* API usage + cost summary — operational telemetry, collapsed by
          default so the MD's view stays focused on the Final Decision. */}
      {hasResult && !stepsLoading && (steps ?? []).length > 0 && (
        <div className="border border-slate-200 rounded-md bg-white mb-4">
          <button
            type="button"
            onClick={() => setUsageOpen((v) => !v)}
            className="w-full px-4 py-2.5 flex items-center gap-2 text-left hover:bg-slate-50"
            aria-expanded={usageOpen}
            data-testid="usage-summary-toggle"
          >
            <span className="text-sm font-semibold text-slate-800">
              API Usage & Cost
            </span>
            <span className="text-slate-400 text-xs">·</span>
            <span className="text-xs text-slate-500 font-mono">
              {dr.total_cost_usd != null
                ? `$${parseFloat(dr.total_cost_usd).toFixed(4)}`
                : '—'}
            </span>
            <span className="ml-auto text-slate-500 text-[11px]">
              {usageOpen ? '▴ hide' : '▾ show'}
            </span>
          </button>
          {usageOpen && (
            <div className="px-4 pb-4 border-t border-slate-100 pt-3">
              <UsageSummary steps={activeSteps} totalCostUsd={dr.total_cost_usd} />
            </div>
          )}
        </div>
      )}

      {/* Pipeline steps — same treatment: collapsed by default, quick
          summary in the header when closed so auditors still see the
          shape of the run without expanding. */}
      {hasResult && (
        <div className="border border-slate-200 rounded-md bg-white">
          <button
            type="button"
            onClick={() => setStepsOpen((v) => !v)}
            className="w-full px-4 py-2.5 flex items-center gap-2 text-left hover:bg-slate-50"
            aria-expanded={stepsOpen}
            data-testid="steps-toggle"
          >
            <span className="text-sm font-semibold text-slate-800">
              Pipeline Steps
            </span>
            {isActive && (
              <span className="text-xs text-blue-600 font-normal animate-pulse">
                Running…
              </span>
            )}
            <span className="text-slate-400 text-xs">·</span>
            <span className="text-xs text-slate-500">
              {activeSteps.length} ran
              {skippedCount > 0 && `, ${skippedCount} skipped`}
            </span>
            <span className="ml-auto text-slate-500 text-[11px]">
              {stepsOpen ? '▴ hide' : '▾ show'}
            </span>
          </button>
          {stepsOpen && (
            <div className="px-4 pb-4 border-t border-slate-100 pt-3">
              {stepsLoading ? (
                <div className="flex flex-col gap-2">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-8 w-full" />
                  ))}
                </div>
              ) : (
                <StepTable steps={activeSteps} />
              )}
            </div>
          )}
        </div>
      )}

      {/* Decision card */}
      {hasResult && dr.status === 'COMPLETED' && (
        <DecisionCard dr={dr} caseId={caseId} />
      )}
    </div>
  )
}
