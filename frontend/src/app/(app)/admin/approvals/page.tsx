'use client'

/**
 * /admin/approvals — the MD Adjudication Docket.
 *
 * Cross-case queue of every LevelIssue awaiting a decision. Layout matches the
 * rest of the software (Cases, Case Detail, Settings) — standard header band,
 * Card-based dossiers, normal sans-serif, Badge + Button UI primitives.
 *
 * Three decision paths per issue:
 *   - APPROVE (green)      → [MITIGATION] tag; trains auto-justifier
 *   - CASE-ONLY (amber)    → [CASE_SPECIFIC] tag; recorded on the case, NOT
 *                            surfaced as precedent (auto-justifier skips these)
 *   - REJECT  (red)        → [REJECTION] tag; trains auto-justifier
 *
 * Only visible to ``admin`` and ``ceo`` roles.
 */

import React, { useMemo, useState } from 'react'
import Link from 'next/link'
import { mutate as globalMutate } from 'swr'
import { cn } from '@/lib/cn'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuth } from '@/components/auth/useAuth'
import { useMDQueue, useCasePhotos, usePrecedents } from '@/lib/useVerification'
import { cases as casesApi } from '@/lib/api'
import type {
  LevelIssueRead,
  MDQueueItem,
  VerificationLevelNumber,
} from '@/lib/types'

const LEVEL_TITLE: Record<VerificationLevelNumber, string> = {
  L1_ADDRESS: 'L1 · Address',
  L1_5_CREDIT: 'L1.5 · Credit',
  L2_BANKING: 'L2 · Banking',
  L3_VISION: 'L3 · Vision',
  L4_AGREEMENT: 'L4 · Agreement',
  L5_SCORING: 'L5 · Scoring',
  L5_5_DEDUPE_TVR: 'L5.5 · Dedupe + TVR + NACH + PDC',
}

// Three decision intents. Each produces a different md_rationale prefix, which
// is the single source of truth for the auto-justifier / precedent queries.
type Intent = 'approve' | 'case_only' | 'reject' | null

const INTENT_META = {
  approve: {
    label: 'Approve · override the block',
    sublabel: 'Records a mitigation reason · trains the auto-justifier',
    tag: 'MITIGATION',
    // Submitted to the decide endpoint
    decision: 'MD_APPROVED' as const,
    btnClass: 'bg-emerald-600 hover:bg-emerald-700 text-white',
    cardClass: 'border-emerald-300 hover:border-emerald-500 hover:bg-emerald-50',
    accentText: 'text-emerald-700',
    focusBorder: 'focus:border-emerald-600 border-emerald-200',
    placeholder:
      'What mitigating factor makes this concern acceptable?\n\nExamples:\n• Applicant\u2019s brother-in-law is guarantor on this loan\n• Past DPD is pre-demonetisation; clean 24-month run since\n• Collateral is being hypothecated outside the agreement\n\nBe specific — the auto-justifier will use this to auto-resolve similar future cases.',
  },
  case_only: {
    label: 'Approve for this case only',
    sublabel:
      'Records a reason on the case · does NOT train the auto-justifier',
    tag: 'CASE_SPECIFIC',
    decision: 'MD_APPROVED' as const,
    btnClass: 'bg-amber-500 hover:bg-amber-600 text-white',
    cardClass: 'border-amber-300 hover:border-amber-500 hover:bg-amber-50',
    accentText: 'text-amber-700',
    focusBorder: 'focus:border-amber-500 border-amber-200',
    placeholder:
      'Why is this approval specific to this case and should NOT become a precedent?\n\nExamples:\n• Known family friend of the branch — relationship override, not policy\n• Goodwill write-off on a restructured legacy loan from 2021\n• Pilot-batch concession tied to Branch 14 launch, not a repeatable pattern\n\nBe specific — this reason appears in the report and audit log, but the model will keep flagging similar issues on future cases.',
  },
  reject: {
    label: 'Reject · uphold the block',
    sublabel: 'Records a rejection reason · trains the auto-justifier',
    tag: 'REJECTION',
    decision: 'MD_REJECTED' as const,
    btnClass: 'bg-red-600 hover:bg-red-700 text-white',
    cardClass: 'border-red-300 hover:border-red-500 hover:bg-red-50',
    accentText: 'text-red-700',
    focusBorder: 'focus:border-red-600 border-red-200',
    placeholder:
      'Why does this concern disqualify the loan?\n\nExamples:\n• Willful-default pattern — multiple SETTLED / WO accounts\n• Collateral insufficient for service business (equipment < 40% of ticket)\n• Fraud indicator: PAN mismatch across bureau records\n\nBe specific — the auto-justifier will learn to reject similar future cases.',
  },
} as const

function severityToneClasses(severity: LevelIssueRead['severity']): {
  pill: React.ComponentProps<typeof Badge>['variant']
  bar: string
} {
  if (severity === 'CRITICAL')
    return { pill: 'destructive', bar: 'bg-red-600' }
  if (severity === 'WARNING') return { pill: 'warning', bar: 'bg-amber-500' }
  return { pill: 'outline', bar: 'bg-pfl-slate-400' }
}

function statusLabel(status: LevelIssueRead['status']): {
  label: string
  variant: React.ComponentProps<typeof Badge>['variant']
} {
  switch (status) {
    case 'OPEN':
      return { label: 'Open · needs assessor', variant: 'outline' }
    case 'ASSESSOR_RESOLVED':
      return { label: 'Awaiting MD', variant: 'HUMAN_REVIEW' }
    case 'MD_APPROVED':
      return { label: 'MD approved', variant: 'success' }
    case 'MD_REJECTED':
      return { label: 'MD rejected', variant: 'destructive' }
    default:
      return { label: status, variant: 'outline' }
  }
}

// ---------------------------------------------------------------------------
// Docket row — one issue
// ---------------------------------------------------------------------------

function DocketRow({
  item,
  onDecide,
}: {
  item: MDQueueItem
  onDecide: (
    id: string,
    decision: 'MD_APPROVED' | 'MD_REJECTED',
    rationale: string,
  ) => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [intent, setIntent] = useState<Intent>(null)
  const [rationale, setRationale] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const awaitingMD = item.issue.status === 'ASSESSOR_RESOLVED'
  const canDecide =
    item.issue.status === 'OPEN' || item.issue.status === 'ASSESSOR_RESOLVED'
  const toneClasses = severityToneClasses(item.issue.severity)
  const statusMeta = statusLabel(item.issue.status)

  const showL3Photos = open && item.level_number === 'L3_VISION'
  const { data: housePhotos } = useCasePhotos(
    item.case_id,
    'HOUSE_VISIT_PHOTO',
    showL3Photos,
  )
  const { data: businessPhotos } = useCasePhotos(
    item.case_id,
    'BUSINESS_PREMISES_PHOTO',
    showL3Photos,
  )
  const { data: precedents } = usePrecedents(
    open ? item.issue.sub_step_id : null,
    true,
  )

  async function handleDecide() {
    if (!intent) return
    setBusy(true)
    setErr(null)
    try {
      const meta = INTENT_META[intent]
      const tagged = `[${meta.tag}] ${rationale.trim()}`
      await onDecide(item.issue.id, meta.decision, tagged)
      setRationale('')
      setIntent(null)
      setOpen(false)
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Failed to record decision')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="border-t border-pfl-slate-200"
      data-testid={`md-row-${item.issue.id}`}
    >
      <div
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setOpen((o) => !o)
          }
        }}
        className="cursor-pointer px-6 py-4 hover:bg-pfl-slate-50 flex items-start gap-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pfl-blue-600"
      >
        <div className={cn('shrink-0 w-1 self-stretch rounded-sm', toneClasses.bar)} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <Badge variant={toneClasses.pill}>{item.issue.severity}</Badge>
            <span className="text-xs font-mono text-pfl-slate-500">
              {item.issue.sub_step_id}
            </span>
            <span className="text-xs text-pfl-slate-400">·</span>
            <span className="text-xs text-pfl-slate-600">
              {LEVEL_TITLE[item.level_number]}
            </span>
          </div>
          <div className="text-sm text-pfl-slate-900 leading-snug">
            {item.issue.description.split('\n')[0]}
          </div>
        </div>
        <div className="shrink-0 flex flex-col items-end gap-1.5">
          <Badge variant={statusMeta.variant}>{statusMeta.label}</Badge>
          <span className="text-[11px] text-pfl-slate-400">
            {open ? '▲ collapse' : '▼ expand'}
          </span>
        </div>
      </div>

      {open && (
        <div className="px-6 pb-6 pl-10 grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* LEFT — description + assessor note + precedents */}
          <div className="lg:col-span-1 flex flex-col gap-4">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-pfl-slate-500 font-semibold mb-1.5">
                Concern
              </div>
              <p className="text-sm text-pfl-slate-800 leading-relaxed whitespace-pre-wrap">
                {item.issue.description}
              </p>
            </div>

            {item.issue.assessor_note && (
              <div className="border border-pfl-indigo-200 bg-indigo-50/60 rounded-md p-3">
                <div className="text-[11px] uppercase tracking-wider text-indigo-700 font-semibold mb-1">
                  Assessor note
                </div>
                <div className="text-sm text-pfl-slate-800">
                  {item.issue.assessor_note}
                </div>
              </div>
            )}

            {precedents && precedents.items.length > 0 && (
              <div className="border border-pfl-slate-200 rounded-md p-3 bg-pfl-slate-50">
                <div className="text-[11px] uppercase tracking-wider text-pfl-slate-700 font-semibold mb-2 flex items-center gap-2">
                  Past MD rulings
                  <span className="text-pfl-slate-400">·</span>
                  <span className="text-emerald-700">
                    {precedents.approved_count} approved
                  </span>
                  <span className="text-pfl-slate-400">·</span>
                  <span className="text-red-700">
                    {precedents.rejected_count} rejected
                  </span>
                </div>
                <div className="flex flex-col gap-2">
                  {precedents.items.slice(0, 4).map((p) => (
                    <div
                      key={p.issue_id}
                      className="text-xs border-l-2 border-pfl-slate-300 pl-2"
                    >
                      <div className="flex items-center gap-2 flex-wrap mb-0.5">
                        <Badge
                          variant={
                            p.decision === 'MD_APPROVED' ? 'success' : 'destructive'
                          }
                        >
                          {p.decision === 'MD_APPROVED' ? 'APPROVED' : 'REJECTED'}
                        </Badge>
                        <span className="font-mono text-pfl-slate-500">
                          {p.loan_id}
                        </span>
                      </div>
                      {p.md_rationale && (
                        <div className="text-pfl-slate-700 leading-snug">
                          {p.md_rationale}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-[11px] text-pfl-slate-500 italic">
                  Case-specific approvals are excluded from this list — they never
                  count as precedent.
                </p>
              </div>
            )}
          </div>

          {/* RIGHT — decision panel */}
          {canDecide ? (
            <div className="lg:col-span-2 flex flex-col gap-4">
              {!awaitingMD && (
                <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  The assessor has not yet resolved this concern. You can still
                  decide directly as Managing Director — the audit log will
                  record that you short-circuited the assessor step.
                </div>
              )}

              {/* L3 photos */}
              {item.level_number === 'L3_VISION' &&
                ((housePhotos?.items.length ?? 0) > 0 ||
                  (businessPhotos?.items.length ?? 0) > 0) && (
                  <div className="border border-pfl-slate-200 rounded-md bg-white p-3">
                    <div className="text-[11px] uppercase tracking-wider text-pfl-slate-600 font-semibold mb-2">
                      Source photos
                    </div>
                    {(housePhotos?.items.length ?? 0) > 0 && (
                      <div className="mb-3">
                        <div className="text-xs font-semibold text-pfl-slate-700 mb-1.5">
                          House visit · {housePhotos?.items.length}
                        </div>
                        <div className="grid grid-cols-3 md:grid-cols-5 gap-2">
                          {housePhotos?.items.map((p) => (
                            <a
                              key={p.artifact_id}
                              href={p.download_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="block border border-pfl-slate-200 rounded bg-white hover:border-pfl-blue-500 overflow-hidden aspect-square"
                              title={p.filename}
                            >
                              <img
                                src={p.download_url}
                                alt={p.filename}
                                className="w-full h-full object-cover"
                                loading="lazy"
                              />
                            </a>
                          ))}
                        </div>
                      </div>
                    )}
                    {(businessPhotos?.items.length ?? 0) > 0 && (
                      <div>
                        <div className="text-xs font-semibold text-pfl-slate-700 mb-1.5">
                          Business premises · {businessPhotos?.items.length}
                        </div>
                        <div className="grid grid-cols-3 md:grid-cols-5 gap-2">
                          {businessPhotos?.items.map((p) => (
                            <a
                              key={p.artifact_id}
                              href={p.download_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="block border border-pfl-slate-200 rounded bg-white hover:border-pfl-blue-500 overflow-hidden aspect-square"
                              title={p.filename}
                            >
                              <img
                                src={p.download_url}
                                alt={p.filename}
                                className="w-full h-full object-cover"
                                loading="lazy"
                              />
                            </a>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

              <div className="text-[11px] uppercase tracking-wider text-pfl-slate-600 font-semibold">
                MD Adjudication
              </div>

              {/* Step 1 — three intent cards */}
              {intent === null ? (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {(['approve', 'case_only', 'reject'] as const).map((key) => {
                    const meta = INTENT_META[key]
                    return (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setIntent(key)}
                        className={cn(
                          'text-left border rounded-md px-3 py-3 transition-colors bg-white',
                          meta.cardClass,
                        )}
                      >
                        <div
                          className={cn(
                            'text-xs font-semibold uppercase tracking-wider mb-1',
                            meta.accentText,
                          )}
                        >
                          {meta.label}
                        </div>
                        <p className="text-xs text-pfl-slate-600 leading-snug">
                          {meta.sublabel}
                        </p>
                      </button>
                    )
                  })}
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-3 flex-wrap">
                    <Badge
                      variant={
                        intent === 'approve'
                          ? 'success'
                          : intent === 'reject'
                          ? 'destructive'
                          : 'warning'
                      }
                    >
                      {INTENT_META[intent].label}
                    </Badge>
                    <button
                      type="button"
                      onClick={() => {
                        setIntent(null)
                        setRationale('')
                        setErr(null)
                      }}
                      className="text-xs text-pfl-slate-500 hover:text-pfl-slate-900 underline"
                    >
                      change intent
                    </button>
                  </div>
                  <textarea
                    className={cn(
                      'w-full rounded-md border p-3 text-sm focus:outline-none bg-white leading-relaxed',
                      INTENT_META[intent].focusBorder,
                    )}
                    rows={5}
                    value={rationale}
                    onChange={(e) => setRationale(e.target.value)}
                    placeholder={INTENT_META[intent].placeholder}
                  />
                  <p className="text-xs text-pfl-slate-500 leading-snug">
                    {rationale.trim().length < 10
                      ? `Need at least 10 characters — currently ${rationale.trim().length}.`
                      : `${rationale.trim().length} characters — saved as [${INTENT_META[intent].tag}] in the audit log${
                          intent === 'case_only'
                            ? ' · will NOT be surfaced as precedent to the auto-justifier'
                            : ''
                        }.`}
                  </p>
                  <div className="flex items-center gap-3 flex-wrap">
                    <button
                      type="button"
                      className={cn(
                        'inline-flex items-center rounded px-4 py-2 text-sm font-semibold transition-colors disabled:opacity-50',
                        INTENT_META[intent].btnClass,
                      )}
                      disabled={busy || rationale.trim().length < 10}
                      onClick={handleDecide}
                    >
                      {busy
                        ? 'Submitting…'
                        : intent === 'approve'
                        ? 'Record approval'
                        : intent === 'reject'
                        ? 'Record rejection'
                        : 'Record case-only approval'}
                    </button>
                    {err && <span className="text-xs text-red-700">{err}</span>}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="lg:col-span-2 rounded-md border border-pfl-slate-200 bg-pfl-slate-50 px-3 py-3 text-sm text-pfl-slate-700">
              This issue has already been decided —{' '}
              <span className="font-semibold">
                {item.issue.status === 'MD_APPROVED' ? 'approved' : 'rejected'}
              </span>
              . Open the case for the full decision trail.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function MDApprovalsPage() {
  const { user } = useAuth()
  const isMD = user?.role === 'admin' || user?.role === 'ceo'
  const { data, isLoading, error, mutate } = useMDQueue(isMD)
  const [filter, setFilter] = useState<'all' | 'awaiting' | 'open'>('all')
  const [expandedCases, setExpandedCases] = useState<Record<string, boolean>>({})

  function toggleCase(id: string, currentlyExpanded: boolean) {
    setExpandedCases((prev) => ({ ...prev, [id]: !currentlyExpanded }))
  }

  const items = useMemo(() => {
    if (!data?.items) return []
    if (filter === 'all') return data.items
    if (filter === 'awaiting')
      return data.items.filter((i) => i.issue.status === 'ASSESSOR_RESOLVED')
    return data.items.filter((i) => i.issue.status === 'OPEN')
  }, [data, filter])

  const grouped = useMemo(() => {
    const map = new Map<string, { header: MDQueueItem; issues: MDQueueItem[] }>()
    for (const it of items) {
      const existing = map.get(it.case_id)
      if (!existing) map.set(it.case_id, { header: it, issues: [it] })
      else existing.issues.push(it)
    }
    const sevWeight: Record<string, number> = { CRITICAL: 0, WARNING: 1, INFO: 2 }
    const statusWeight: Record<string, number> = {
      ASSESSOR_RESOLVED: 0,
      OPEN: 1,
      MD_APPROVED: 2,
      MD_REJECTED: 2,
    }
    for (const group of map.values()) {
      group.issues.sort((a, b) => {
        const sa = sevWeight[a.issue.severity] ?? 9
        const sb = sevWeight[b.issue.severity] ?? 9
        if (sa !== sb) return sa - sb
        const ta = statusWeight[a.issue.status] ?? 9
        const tb = statusWeight[b.issue.status] ?? 9
        return ta - tb
      })
    }
    return [...map.values()].sort((x, y) => {
      const xWorst = Math.min(
        ...x.issues.map((i) => sevWeight[i.issue.severity] ?? 9),
      )
      const yWorst = Math.min(
        ...y.issues.map((i) => sevWeight[i.issue.severity] ?? 9),
      )
      if (xWorst !== yWorst) return xWorst - yWorst
      return y.issues.length - x.issues.length
    })
  }, [items])

  async function handleDecide(
    id: string,
    decision: 'MD_APPROVED' | 'MD_REJECTED',
    rationale: string,
  ) {
    await casesApi.verificationDecideIssue(id, decision, rationale)
    // Invalidate local queue + the assessor queue (same issue might have
    // been visible there too) + every loaded level detail / overview, so
    // a case detail tab opened in the background reflects the decision
    // instantly.
    await Promise.all([
      mutate(),
      globalMutate(['verification-assessor-queue']),
      globalMutate(
        (key) =>
          Array.isArray(key) &&
          (key[0] === 'verification-overview' || key[0] === 'verification-level'),
      ),
    ])
  }

  if (!user) {
    return <Skeleton className="m-6 h-96" />
  }
  if (!isMD) {
    return (
      <div
        role="alert"
        className="m-6 rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        This page is reserved for the Managing Director and CEO roles. Your
        account does not have access.
      </div>
    )
  }

  const totalOpen = (data?.total_open ?? 0) + (data?.total_awaiting_md ?? 0)

  return (
    <div className="flex flex-col gap-0">
      {/* Page header */}
      <div className="px-6 py-5 border-b border-pfl-slate-200 flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-baseline gap-3 flex-wrap">
          <h1 className="text-2xl font-bold text-pfl-slate-900">MD Approvals</h1>
          {!isLoading && (
            <span className="text-sm text-pfl-slate-500">
              {totalOpen === 0 ? 'docket clear' : `${totalOpen} pending`}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs text-pfl-slate-600">
          <Badge variant="HUMAN_REVIEW">
            {data?.total_awaiting_md ?? 0} awaiting MD
          </Badge>
          <Badge variant="outline">{data?.total_open ?? 0} open</Badge>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => mutate()}
            aria-label="Refresh docket"
          >
            Refresh
          </Button>
        </div>
      </div>

      {/* Intro + filter bar */}
      <div className="px-6 pt-4 pb-3 border-b border-pfl-slate-200 flex flex-col gap-3">
        <p className="text-sm text-pfl-slate-600 max-w-3xl leading-snug">
          Every unresolved concern raised by the verification gate, grouped per
          case. Approve with a <strong>mitigation reason</strong> to override
          the block and train the auto-justifier, approve for{' '}
          <strong>this case only</strong> to record a one-off reason without
          training the model, or reject with a <strong>rejection reason</strong>{' '}
          to uphold the block.
        </p>
        <div className="flex items-center gap-1">
          {(
            [
              { key: 'all', label: 'All' },
              { key: 'awaiting', label: 'Awaiting MD' },
              { key: 'open', label: 'Open · needs assessor' },
            ] as const
          ).map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={cn(
                'px-3 py-1.5 text-xs font-semibold rounded transition-colors',
                filter === f.key
                  ? 'bg-pfl-slate-900 text-white'
                  : 'text-pfl-slate-600 hover:text-pfl-slate-900 hover:bg-pfl-slate-100',
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* List */}
      <div className="px-6 py-4 flex flex-col gap-4">
        {isLoading && (
          <>
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </>
        )}
        {!isLoading && error && (
          <div className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            Failed to load docket. {(error as Error).message}
          </div>
        )}
        {!isLoading && !error && items.length === 0 && (
          <div className="py-16 text-center text-pfl-slate-500">
            {filter === 'all'
              ? 'No concerns currently await adjudication.'
              : filter === 'awaiting'
              ? 'No issues are awaiting an MD decision.'
              : 'No issues are open awaiting assessor resolution.'}
          </div>
        )}
        {!isLoading &&
          !error &&
          grouped.map((group, idx) => {
            const head = group.header
            const critCount = group.issues.filter(
              (i) => i.issue.severity === 'CRITICAL',
            ).length
            const warnCount = group.issues.filter(
              (i) => i.issue.severity === 'WARNING',
            ).length
            const awaitingMdCount = group.issues.filter(
              (i) => i.issue.status === 'ASSESSOR_RESOLVED',
            ).length
            const openCount = group.issues.filter(
              (i) => i.issue.status === 'OPEN',
            ).length
            const total = group.issues.length
            const isExpanded =
              expandedCases[head.case_id] ?? (idx === 0 ? true : false)
            return (
              <Card
                key={head.case_id}
                className="overflow-hidden"
                data-testid={`md-case-${head.case_id}`}
              >
                <div
                  role="button"
                  tabIndex={0}
                  aria-expanded={isExpanded}
                  onClick={() => toggleCase(head.case_id, isExpanded)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      toggleCase(head.case_id, isExpanded)
                    }
                  }}
                  className="cursor-pointer px-6 py-4 hover:bg-pfl-slate-50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pfl-blue-600"
                >
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span
                        className="inline-flex items-center justify-center w-6 h-6 rounded border border-pfl-slate-300 text-pfl-slate-600 text-sm"
                        aria-hidden
                      >
                        {isExpanded ? '–' : '+'}
                      </span>
                      <h2 className="text-base font-semibold text-pfl-slate-900">
                        {head.applicant_name ?? 'Unknown'}
                        {head.co_applicant_name && (
                          <>
                            <span className="text-pfl-slate-400 font-normal">
                              {' '}
                              with{' '}
                            </span>
                            {head.co_applicant_name}
                          </>
                        )}
                      </h2>
                      <Link
                        href={`/cases/${head.case_id}`}
                        className="text-xs text-pfl-blue-700 hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        open case →
                      </Link>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-pfl-slate-500 font-mono tabular-nums">
                      <span>#{head.loan_id}</span>
                      {head.loan_amount != null && (
                        <span>₹{head.loan_amount.toLocaleString('en-IN')}</span>
                      )}
                    </div>
                  </div>

                  <div className="mt-3 flex items-center gap-2 flex-wrap">
                    <Badge variant="outline">Total {total}</Badge>
                    <Badge variant={critCount > 0 ? 'destructive' : 'outline'}>
                      Critical {critCount}
                    </Badge>
                    <Badge variant={warnCount > 0 ? 'warning' : 'outline'}>
                      Warning {warnCount}
                    </Badge>
                    <Badge
                      variant={awaitingMdCount > 0 ? 'HUMAN_REVIEW' : 'outline'}
                    >
                      Assessor → MD {awaitingMdCount}
                    </Badge>
                    <Badge variant="outline">Open {openCount}</Badge>
                    {!isExpanded && (
                      <span className="text-xs text-pfl-slate-500 italic ml-1">
                        click to expand
                      </span>
                    )}
                  </div>
                </div>
                {isExpanded &&
                  group.issues.map((item) => (
                    <DocketRow
                      key={item.issue.id}
                      item={item}
                      onDecide={handleDecide}
                    />
                  ))}
              </Card>
            )
          })}
      </div>
    </div>
  )
}
