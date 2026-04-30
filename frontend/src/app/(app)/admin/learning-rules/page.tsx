'use client'

/**
 * /admin/learning-rules — control surface over every rule the AI runs.
 *
 * For each deterministic rule the verification engine emits (keyed by
 * sub_step_id), show:
 *   - fire count (how many LevelIssue rows it has produced, ever)
 *   - MD precedent breakdown (approved / rejected / pending resolution)
 *   - current status (active / suppressed)
 *   - admin note
 *   - up to 5 recent MD rationales — the "learning signal" the AI will
 *     absorb on similar cases going forward
 *
 * An admin can toggle `is_suppressed` to take a rule out of the engine
 * (matching issues never persist; the gate treats it as if the rule was
 * never defined) and attach a free-form justification.
 *
 * Admin-only (useRequireAdmin guard).
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { BrainIcon, PowerIcon, PowerOffIcon, Loader2Icon } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/use-toast'
import {
  LEVELS,
  LEVEL_META,
  RULE_CATALOG,
  type RuleCatalogEntry,
} from '@/components/cases/VerificationPanel'
import { useRequireAdmin } from '@/lib/useRequireAdmin'
import { api, type RuleStatRead } from '@/lib/api'
import { cn } from '@/lib/cn'
import type { VerificationLevelNumber } from '@/lib/types'

interface RuleRow {
  subStepId: string
  level: VerificationLevelNumber | 'UNKNOWN'
  title: string
  description: string
  stat: RuleStatRead | null
}

function buildRows(stats: RuleStatRead[]): RuleRow[] {
  // Map sub_step_id → catalog entry + level (catalog is the source of
  // truth for friendly titles; BE returns the raw sub_step_id only).
  const catalogIndex = new Map<
    string,
    { level: VerificationLevelNumber; entry: RuleCatalogEntry }
  >()
  for (const lvl of LEVELS) {
    for (const entry of RULE_CATALOG[lvl] ?? []) {
      catalogIndex.set(entry.sub_step_id, { level: lvl, entry })
    }
  }

  const statsById = new Map(stats.map((s) => [s.sub_step_id, s]))
  const seen = new Set<string>()
  const rows: RuleRow[] = []

  // Catalog rules first (deterministic sort by level, then title).
  for (const lvl of LEVELS) {
    for (const entry of RULE_CATALOG[lvl] ?? []) {
      seen.add(entry.sub_step_id)
      rows.push({
        subStepId: entry.sub_step_id,
        level: lvl,
        title: entry.title,
        description: entry.description,
        stat: statsById.get(entry.sub_step_id) ?? null,
      })
    }
  }
  // Runtime-only rules (fired by the engine but not in the catalog, e.g.
  // ``ca_analyzer_failed``). Group them under a synthetic UNKNOWN level.
  for (const s of stats) {
    if (seen.has(s.sub_step_id)) continue
    rows.push({
      subStepId: s.sub_step_id,
      level: 'UNKNOWN',
      title: s.sub_step_id,
      description:
        'Runtime-only rule — not in the frontend catalog. Usually emitted on scanner / analyser failure.',
      stat: s,
    })
  }
  return rows
}

export default function AdminLearningRulesPage() {
  const { ready } = useRequireAdmin()
  const [stats, setStats] = useState<RuleStatRead[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'suppressed' | 'md_signal' | 'fired'>(
    'all',
  )
  const [search, setSearch] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.adminRules.stats()
      setStats(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load rule stats')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (ready) load()
  }, [ready, load])

  const rows = useMemo(() => buildRows(stats), [stats])
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return rows.filter((r) => {
      if (filter === 'suppressed' && !r.stat?.is_suppressed) return false
      if (
        filter === 'md_signal' &&
        (r.stat?.md_approved_count ?? 0) + (r.stat?.md_rejected_count ?? 0) === 0
      )
        return false
      if (filter === 'fired' && (r.stat?.total_fires ?? 0) === 0) return false
      if (q) {
        const hay = `${r.title} ${r.subStepId} ${r.description}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [rows, filter, search])

  const summary = useMemo(() => {
    const total = rows.length
    const suppressed = rows.filter((r) => r.stat?.is_suppressed).length
    const withMdSignal = rows.filter(
      (r) => (r.stat?.md_approved_count ?? 0) + (r.stat?.md_rejected_count ?? 0) > 0,
    ).length
    const hasFired = rows.filter((r) => (r.stat?.total_fires ?? 0) > 0).length
    return { total, suppressed, withMdSignal, hasFired }
  }, [rows])

  async function handleToggleSuppress(row: RuleRow) {
    const next = !row.stat?.is_suppressed
    try {
      await api.adminRules.upsertOverride(row.subStepId, { is_suppressed: next })
      toast({
        title: next ? 'Rule suppressed' : 'Rule reactivated',
        description: next
          ? `${row.title} will no longer block the gate. Re-run L1–L5 to clear any open issues.`
          : `${row.title} is live again — next verification run will emit it as normal.`,
      })
      await load()
    } catch (e) {
      toast({
        title: 'Update failed',
        description: e instanceof Error ? e.message : 'Unexpected error',
        variant: 'destructive',
      })
    }
  }

  async function handleSaveNote(row: RuleRow, note: string) {
    try {
      await api.adminRules.upsertOverride(row.subStepId, { admin_note: note })
      toast({ title: 'Note saved' })
      await load()
    } catch (e) {
      toast({
        title: 'Failed to save note',
        description: e instanceof Error ? e.message : 'Unexpected error',
        variant: 'destructive',
      })
    }
  }

  if (!ready) {
    return (
      <div className="flex flex-col gap-4 py-8">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-6 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-pfl-slate-900 flex items-center gap-2">
            <BrainIcon className="h-6 w-6 text-pfl-blue-700" />
            Learning Rules
          </h1>
          <p className="text-sm text-pfl-slate-600 mt-1 max-w-3xl leading-snug">
            The deterministic rules the AI runs on every case. Each row shows
            how often the rule has fired, what MDs have decided on it so far
            (the signal the AI learns from), and whether it&apos;s currently
            active. Toggle <span className="font-mono">Suppress</span> to take
            a rule out of the engine — the gate will behave as if the rule was
            never defined until you re-enable it.
          </p>
        </div>
        <div className="flex items-stretch gap-2 text-[12px]">
          <SummaryStat label="Total rules" value={summary.total} />
          <SummaryStat label="Suppressed" value={summary.suppressed} tone="red" />
          <SummaryStat
            label="MD signal"
            value={summary.withMdSignal}
            tone="indigo"
            hint="rules with ≥1 MD decision on file"
          />
          <SummaryStat
            label="Has fired"
            value={summary.hasFired}
            tone="emerald"
            hint="rules that produced at least one issue"
          />
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="inline-flex rounded-md border border-pfl-slate-200 overflow-hidden text-[12px]">
          {[
            { k: 'all' as const, l: 'All' },
            { k: 'fired' as const, l: 'Has fired' },
            { k: 'md_signal' as const, l: 'MD signal' },
            { k: 'suppressed' as const, l: 'Suppressed' },
          ].map((o) => (
            <button
              key={o.k}
              type="button"
              onClick={() => setFilter(o.k)}
              className={cn(
                'px-3 py-1.5 border-r border-pfl-slate-200 last:border-r-0',
                filter === o.k
                  ? 'bg-pfl-blue-50 text-pfl-blue-800 font-semibold'
                  : 'text-pfl-slate-600 hover:bg-pfl-slate-50',
              )}
            >
              {o.l}
            </button>
          ))}
        </div>
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search rule title, sub_step_id, description…"
          className="flex-1 min-w-[240px] max-w-md rounded-md border border-pfl-slate-300 px-3 py-1.5 text-[13px]"
        />
        {(loading || !stats) && (
          <Loader2Icon className="h-4 w-4 animate-spin text-pfl-slate-500" />
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {/* Rule list */}
      {loading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-6 text-center text-sm text-pfl-slate-500">
          No rules match this filter.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {filtered.map((r) => (
            <RuleCard
              key={r.subStepId}
              row={r}
              onToggleSuppress={() => handleToggleSuppress(r)}
              onSaveNote={(note) => handleSaveNote(r, note)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function SummaryStat({
  label,
  value,
  tone = 'slate',
  hint,
}: {
  label: string
  value: number
  tone?: 'slate' | 'red' | 'emerald' | 'indigo'
  hint?: string
}) {
  const palette = {
    slate: 'border-pfl-slate-200 text-pfl-slate-700',
    red: 'border-red-200 text-red-700',
    emerald: 'border-emerald-200 text-emerald-700',
    indigo: 'border-indigo-200 text-indigo-700',
  }[tone]
  return (
    <div
      className={cn('rounded-md border bg-white px-3 py-2', palette)}
      title={hint}
    >
      <div className="text-[10px] font-semibold uppercase tracking-wider text-pfl-slate-500">
        {label}
      </div>
      <div className="text-lg font-bold tabular-nums mt-0.5">{value}</div>
    </div>
  )
}

function RuleCard({
  row,
  onToggleSuppress,
  onSaveNote,
}: {
  row: RuleRow
  onToggleSuppress: () => Promise<void>
  onSaveNote: (note: string) => Promise<void>
}) {
  const [expanded, setExpanded] = useState(false)
  const [noteDraft, setNoteDraft] = useState(row.stat?.admin_note ?? '')
  const [saving, setSaving] = useState(false)
  const [toggling, setToggling] = useState(false)

  // Re-sync draft when the row reloads (e.g. after a save).
  useEffect(() => {
    setNoteDraft(row.stat?.admin_note ?? '')
  }, [row.stat?.admin_note])

  const fires = row.stat?.total_fires ?? 0
  const mdApproved = row.stat?.md_approved_count ?? 0
  const mdRejected = row.stat?.md_rejected_count ?? 0
  const openCount = row.stat?.open_count ?? 0
  const isSuppressed = !!row.stat?.is_suppressed
  const levelLabel =
    row.level === 'UNKNOWN' ? 'Runtime' : LEVEL_META[row.level].title

  return (
    <div
      className={cn(
        'rounded-md border bg-white',
        isSuppressed
          ? 'border-red-200 bg-red-50/30'
          : 'border-pfl-slate-200',
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full px-4 py-3 text-left flex items-start gap-3 hover:bg-pfl-slate-50/60"
        aria-expanded={expanded}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500">
              {levelLabel}
            </span>
            <span className="text-[11px] font-mono text-pfl-slate-500">
              {row.subStepId}
            </span>
            {isSuppressed && (
              <span className="text-[10px] font-bold uppercase tracking-wider text-red-700 bg-red-100 px-1.5 py-0.5 rounded">
                Suppressed
              </span>
            )}
            {row.stat?.admin_note && !isSuppressed && (
              <span className="text-[10px] font-semibold uppercase tracking-wider text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded">
                Note
              </span>
            )}
          </div>
          <div className="text-[13.5px] font-semibold text-pfl-slate-900 mt-0.5">
            {row.title}
          </div>
          <div className="text-[12.5px] text-pfl-slate-600 mt-0.5 leading-snug">
            {row.description}
          </div>
        </div>
        <div className="flex flex-col items-end gap-0.5 text-[11px] min-w-[180px]">
          <div className="flex items-center gap-2 flex-wrap">
            <Stat label="fires" value={fires} />
            {openCount > 0 && (
              <Stat label="open" value={openCount} tone="amber" />
            )}
            {mdApproved > 0 && (
              <Stat label="approved" value={mdApproved} tone="emerald" />
            )}
            {mdRejected > 0 && (
              <Stat label="rejected" value={mdRejected} tone="red" />
            )}
          </div>
        </div>
        <span className="text-pfl-slate-500 text-[11px] mt-1">
          {expanded ? '▴' : '▾'}
        </span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-pfl-slate-100 flex flex-col gap-3">
          {/* Suppress toggle */}
          <div className="flex items-start gap-3 pt-3">
            <div className="flex-1">
              <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500">
                Status
              </div>
              <div className="text-[12.5px] text-pfl-slate-700 mt-0.5 leading-snug">
                {isSuppressed
                  ? 'This rule is currently SUPPRESSED. The engine skips it entirely — no issues persist, no gate block, no MD queue entry. Existing issues from past runs are unaffected.'
                  : 'This rule is live. Every L1–L5 run will evaluate it and emit an issue on failure.'}
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={async () => {
                setToggling(true)
                try {
                  await onToggleSuppress()
                } finally {
                  setToggling(false)
                }
              }}
              disabled={toggling}
              className={cn(
                isSuppressed
                  ? 'border-emerald-300 text-emerald-700 hover:bg-emerald-50'
                  : 'border-red-300 text-red-700 hover:bg-red-50',
              )}
            >
              {toggling ? (
                <Loader2Icon className="h-3.5 w-3.5 mr-1.5 animate-spin" />
              ) : isSuppressed ? (
                <PowerIcon className="h-3.5 w-3.5 mr-1.5" />
              ) : (
                <PowerOffIcon className="h-3.5 w-3.5 mr-1.5" />
              )}
              {isSuppressed ? 'Reactivate' : 'Suppress'}
            </Button>
          </div>

          {/* Admin note */}
          <div>
            <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
              Admin note
              <span className="ml-1 font-normal normal-case tracking-normal text-pfl-slate-400">
                · why this override exists
              </span>
            </div>
            <textarea
              value={noteDraft}
              onChange={(e) => setNoteDraft(e.target.value)}
              placeholder="e.g. 'Hypothecation clause check was flagging every LAGR PDF in the new template — disabled pending scanner update.'"
              maxLength={2000}
              className="w-full rounded border border-pfl-slate-300 p-2 text-[12.5px] min-h-[60px]"
            />
            <div className="flex items-center justify-between mt-1 text-[11px] text-pfl-slate-500">
              <span>
                {row.stat?.last_edited_at
                  ? `Last edited ${new Date(row.stat.last_edited_at).toLocaleString()}`
                  : 'Never edited'}
              </span>
              <Button
                size="sm"
                onClick={async () => {
                  setSaving(true)
                  try {
                    await onSaveNote(noteDraft)
                  } finally {
                    setSaving(false)
                  }
                }}
                disabled={saving || noteDraft === (row.stat?.admin_note ?? '')}
              >
                {saving && (
                  <Loader2Icon className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                )}
                Save note
              </Button>
            </div>
          </div>

          {/* Recent MD decisions — the AI's learning signal on this rule */}
          {row.stat && row.stat.recent_md_samples.length > 0 && (
            <div>
              <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
                Recent MD decisions
                <span className="ml-1 font-normal normal-case tracking-normal text-pfl-slate-400">
                  · what the AI is learning on this rule
                </span>
              </div>
              <ul className="flex flex-col gap-1.5">
                {row.stat.recent_md_samples.map((s) => (
                  <li
                    key={s.issue_id}
                    className={cn(
                      'rounded border px-3 py-2 text-[12.5px] flex items-start gap-2',
                      s.decision === 'MD_APPROVED'
                        ? 'border-emerald-200 bg-emerald-50/40'
                        : 'border-red-200 bg-red-50/40',
                    )}
                  >
                    <span
                      className={cn(
                        'font-semibold uppercase text-[10px] tracking-wider mt-0.5 whitespace-nowrap',
                        s.decision === 'MD_APPROVED'
                          ? 'text-emerald-700'
                          : 'text-red-700',
                      )}
                    >
                      {s.decision === 'MD_APPROVED' ? 'Approved' : 'Rejected'}
                    </span>
                    <div className="flex-1">
                      <div className="text-pfl-slate-800">
                        {s.rationale || (
                          <span className="italic text-pfl-slate-500">
                            (no rationale recorded)
                          </span>
                        )}
                      </div>
                      <div className="text-[10.5px] text-pfl-slate-500 mt-0.5">
                        {new Date(s.reviewed_at).toLocaleString()} · case{' '}
                        <span className="font-mono">{s.case_id.slice(0, 8)}</span>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Stat({
  label,
  value,
  tone = 'slate',
}: {
  label: string
  value: number
  tone?: 'slate' | 'amber' | 'emerald' | 'red'
}) {
  const palette = {
    slate: 'text-pfl-slate-600',
    amber: 'text-amber-700',
    emerald: 'text-emerald-700',
    red: 'text-red-700',
  }[tone]
  return (
    <span className={cn('font-mono tabular-nums', palette)}>
      <span className="font-bold">{value}</span>{' '}
      <span className="text-[10px] uppercase tracking-wider text-pfl-slate-400">
        {label}
      </span>
    </span>
  )
}
