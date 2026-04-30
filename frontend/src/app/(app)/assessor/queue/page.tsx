'use client'

/**
 * /assessor/queue — Assessor triage page (Phase 1).
 *
 * Shows every OPEN verification-gate issue across all cases — the backlog of
 * gap-fix work that happens BEFORE the MD ever sees a concern. For each issue
 * the assessor can:
 *   1. Upload a missing supporting document → POST /cases/{id}/artifacts
 *   2. Re-run the owning level → POST /cases/{id}/verification/{level}
 *   3. Mark the issue resolved with a note → moves status to ASSESSOR_RESOLVED
 *      so it surfaces in the MD Approvals queue.
 *
 * Per-case header also exposes "Regenerate ZIP" which streams a fresh
 * archive of all artifacts (including anything just uploaded).
 *
 * Visible to: AI_ANALYSER, UNDERWRITER, CREDIT_HO, ADMIN.
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
import { useAssessorQueue } from '@/lib/useVerification'
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

function severityToneClasses(severity: LevelIssueRead['severity']): {
  pill: React.ComponentProps<typeof Badge>['variant']
  bar: string
} {
  if (severity === 'CRITICAL')
    return { pill: 'destructive', bar: 'bg-red-600' }
  if (severity === 'WARNING') return { pill: 'warning', bar: 'bg-amber-500' }
  return { pill: 'outline', bar: 'bg-pfl-slate-400' }
}

// ---------------------------------------------------------------------------
// Per-issue triage card
// ---------------------------------------------------------------------------

function IssueTriageRow({
  item,
  onUpload,
  onRerun,
  onResolve,
}: {
  item: MDQueueItem
  onUpload: (caseId: string, file: File) => Promise<void>
  onRerun: (caseId: string, level: VerificationLevelNumber) => Promise<void>
  onResolve: (issueId: string, note: string) => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const [uploading, setUploading] = useState(false)
  const [rerunning, setRerunning] = useState(false)
  const [resolving, setResolving] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const toneClasses = severityToneClasses(item.issue.severity)

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setMsg(null)
    try {
      await onUpload(item.case_id, file)
      setMsg({ kind: 'ok', text: `Uploaded ${file.name} — now tied to this case's artifacts.` })
    } catch (err) {
      setMsg({
        kind: 'err',
        text: err instanceof Error ? err.message : 'Upload failed',
      })
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  async function handleRerun() {
    setRerunning(true)
    setMsg(null)
    try {
      await onRerun(item.case_id, item.level_number)
      setMsg({
        kind: 'ok',
        text: `Re-ran ${LEVEL_TITLE[item.level_number]}. The queue will refresh — if this issue is now resolved it'll drop off.`,
      })
    } catch (err) {
      setMsg({
        kind: 'err',
        text: err instanceof Error ? err.message : 'Re-run failed',
      })
    } finally {
      setRerunning(false)
    }
  }

  async function handleResolve() {
    if (note.trim().length < 10) return
    setResolving(true)
    setMsg(null)
    try {
      await onResolve(item.issue.id, note.trim())
      setNote('')
      setMsg({
        kind: 'ok',
        text: 'Promoted to MD queue — the MD will see this next.',
      })
    } catch (err) {
      setMsg({
        kind: 'err',
        text: err instanceof Error ? err.message : 'Promote failed',
      })
    } finally {
      setResolving(false)
    }
  }

  return (
    <div
      className="border-t border-pfl-slate-200"
      data-testid={`assessor-row-${item.issue.id}`}
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
          <Badge variant="outline">Open</Badge>
          <span className="text-[11px] text-pfl-slate-400">
            {open ? '▲ collapse' : '▼ triage'}
          </span>
        </div>
      </div>

      {open && (
        <div className="px-6 pb-6 pl-10 grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-pfl-slate-500 font-semibold mb-1.5">
              What the gate found
            </div>
            <p className="text-sm text-pfl-slate-800 leading-relaxed whitespace-pre-wrap">
              {item.issue.description}
            </p>
            {item.issue.assessor_note && (
              <div className="mt-3 rounded-md border border-indigo-200 bg-indigo-50/60 px-3 py-2">
                <div className="text-[11px] uppercase tracking-wider text-indigo-700 font-semibold mb-0.5">
                  Existing assessor note
                </div>
                <div className="text-sm text-pfl-slate-800">
                  {item.issue.assessor_note}
                </div>
              </div>
            )}
          </div>

          <div className="flex flex-col gap-4">
            {/* Step 1 — upload a missing document */}
            <div className="rounded-md border border-pfl-slate-200 bg-pfl-slate-50 p-3">
              <div className="text-[11px] uppercase tracking-wider text-pfl-slate-600 font-semibold mb-1.5">
                Step 1 · Upload a missing document
              </div>
              <p className="text-xs text-pfl-slate-600 mb-2 leading-snug">
                Attach the supporting artifact (income proof, ration card, QR
                screenshot, etc.). It's added to this case&apos;s artifacts
                immediately — you&apos;ll need to re-run the level below to
                test whether this closes the gap.
              </p>
              <label
                className={cn(
                  'inline-flex items-center gap-2 px-3 py-1.5 rounded text-xs font-semibold transition-colors cursor-pointer',
                  uploading
                    ? 'bg-pfl-slate-300 text-pfl-slate-600 cursor-wait'
                    : 'bg-pfl-blue-800 text-white hover:bg-pfl-blue-900',
                )}
              >
                {uploading ? 'Uploading…' : 'Choose file'}
                <input
                  type="file"
                  className="hidden"
                  onChange={handleFileChange}
                  disabled={uploading}
                />
              </label>
            </div>

            {/* Step 2 — re-run the level */}
            <div className="rounded-md border border-pfl-slate-200 bg-pfl-slate-50 p-3">
              <div className="text-[11px] uppercase tracking-wider text-pfl-slate-600 font-semibold mb-1.5">
                Step 2 · Re-run {LEVEL_TITLE[item.level_number]}
              </div>
              <p className="text-xs text-pfl-slate-600 mb-2 leading-snug">
                Re-runs the level against the current artifact set. If this
                issue is now resolved it drops off your queue; if not, it stays
                open.
              </p>
              <Button
                variant="outline"
                size="sm"
                disabled={rerunning}
                onClick={handleRerun}
              >
                {rerunning ? 'Running…' : `Re-run ${LEVEL_TITLE[item.level_number]}`}
              </Button>
            </div>

            {/* Step 3 — promote to MD */}
            <div className="rounded-md border border-pfl-slate-200 bg-pfl-slate-50 p-3">
              <div className="text-[11px] uppercase tracking-wider text-pfl-slate-600 font-semibold mb-1.5">
                Step 3 · Promote to MD (if it can&apos;t be self-resolved)
              </div>
              <p className="text-xs text-pfl-slate-600 mb-2 leading-snug">
                Use when the gap genuinely can&apos;t be closed at the assessor
                level and the MD needs to adjudicate. Your note is attached to
                the issue so the MD sees what you tried.
              </p>
              <textarea
                className="w-full rounded-md border border-pfl-slate-300 focus:border-pfl-blue-600 focus:outline-none p-2 text-sm leading-relaxed"
                rows={3}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="What did you try? Why does this need MD adjudication?"
              />
              <div className="flex items-center gap-3 mt-2">
                <Button
                  size="sm"
                  disabled={resolving || note.trim().length < 10}
                  onClick={handleResolve}
                >
                  {resolving ? 'Promoting…' : 'Promote to MD'}
                </Button>
                <span className="text-xs text-pfl-slate-500">
                  {note.trim().length < 10
                    ? `${note.trim().length}/10 characters`
                    : 'Ready to promote'}
                </span>
              </div>
            </div>

            {msg && (
              <div
                className={cn(
                  'rounded-md px-3 py-2 text-xs',
                  msg.kind === 'ok'
                    ? 'border border-emerald-200 bg-emerald-50 text-emerald-800'
                    : 'border border-red-200 bg-red-50 text-red-800',
                )}
              >
                {msg.text}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Per-case dossier (header + issues)
// ---------------------------------------------------------------------------

function CaseDossier({
  group,
  defaultExpanded,
  onUpload,
  onRerun,
  onResolve,
  onZipDownload,
}: {
  group: { header: MDQueueItem; issues: MDQueueItem[] }
  defaultExpanded: boolean
  onUpload: (caseId: string, file: File) => Promise<void>
  onRerun: (caseId: string, level: VerificationLevelNumber) => Promise<void>
  onResolve: (issueId: string, note: string) => Promise<void>
  onZipDownload: (caseId: string) => Promise<void>
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const [zipping, setZipping] = useState(false)
  const [zipMsg, setZipMsg] = useState<string | null>(null)
  const head = group.header
  const critCount = group.issues.filter((i) => i.issue.severity === 'CRITICAL').length
  const warnCount = group.issues.filter((i) => i.issue.severity === 'WARNING').length

  async function handleZip(e: React.MouseEvent) {
    e.stopPropagation()
    setZipping(true)
    setZipMsg(null)
    try {
      await onZipDownload(head.case_id)
    } catch (err) {
      setZipMsg(err instanceof Error ? err.message : 'ZIP failed')
    } finally {
      setZipping(false)
    }
  }

  // Header uses a div + role=button so nested <Link> and <button>
  // (open case, regenerate ZIP) stay legal descendants — a <button> inside a
  // <button> is invalid HTML and triggers a hydration error that trips the
  // route-level error boundary.
  function onHeaderKey(e: React.KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      setExpanded((x) => !x)
    }
  }

  return (
    <Card className="overflow-hidden" data-testid={`assessor-case-${head.case_id}`}>
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={() => setExpanded((e) => !e)}
        onKeyDown={onHeaderKey}
        className="cursor-pointer px-6 py-4 hover:bg-pfl-slate-50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pfl-blue-600"
      >
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-3 flex-wrap">
            <span
              className="inline-flex items-center justify-center w-6 h-6 rounded border border-pfl-slate-300 text-pfl-slate-600 text-sm"
              aria-hidden
            >
              {expanded ? '–' : '+'}
            </span>
            <h2 className="text-base font-semibold text-pfl-slate-900">
              {head.applicant_name ?? 'Unknown'}
              {head.co_applicant_name && (
                <>
                  <span className="text-pfl-slate-400 font-normal"> with </span>
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
            <button
              type="button"
              onClick={handleZip}
              disabled={zipping}
              className="text-xs text-pfl-blue-700 hover:underline disabled:text-pfl-slate-400 disabled:no-underline"
              title="Download a fresh ZIP with all current artifacts"
            >
              {zipping ? 'zipping…' : 'regenerate ZIP ↓'}
            </button>
          </div>
          <div className="flex items-center gap-3 text-xs text-pfl-slate-500 font-mono tabular-nums">
            <span>#{head.loan_id}</span>
            {head.loan_amount != null && (
              <span>₹{head.loan_amount.toLocaleString('en-IN')}</span>
            )}
          </div>
        </div>

        <div className="mt-3 flex items-center gap-2 flex-wrap">
          <Badge variant="outline">Total {group.issues.length}</Badge>
          <Badge variant={critCount > 0 ? 'destructive' : 'outline'}>
            Critical {critCount}
          </Badge>
          <Badge variant={warnCount > 0 ? 'warning' : 'outline'}>
            Warning {warnCount}
          </Badge>
          {zipMsg && (
            <span className="text-xs text-red-700 ml-1">{zipMsg}</span>
          )}
          {!expanded && (
            <span className="text-xs text-pfl-slate-500 italic ml-1">
              click to triage
            </span>
          )}
        </div>
      </div>
      {expanded &&
        group.issues.map((item) => (
          <IssueTriageRow
            key={item.issue.id}
            item={item}
            onUpload={onUpload}
            onRerun={onRerun}
            onResolve={onResolve}
          />
        ))}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AssessorQueuePage() {
  const { user } = useAuth()
  const canAssess =
    user?.role === 'ai_analyser' ||
    user?.role === 'underwriter' ||
    user?.role === 'credit_ho' ||
    user?.role === 'admin'

  const { data, isLoading, error, mutate } = useAssessorQueue(canAssess)

  const items = data?.items ?? []

  const grouped = useMemo(() => {
    const map = new Map<string, { header: MDQueueItem; issues: MDQueueItem[] }>()
    for (const it of items) {
      const existing = map.get(it.case_id)
      if (!existing) map.set(it.case_id, { header: it, issues: [it] })
      else existing.issues.push(it)
    }
    const sevWeight: Record<string, number> = { CRITICAL: 0, WARNING: 1, INFO: 2 }
    for (const group of map.values()) {
      group.issues.sort((a, b) => {
        const sa = sevWeight[a.issue.severity] ?? 9
        const sb = sevWeight[b.issue.severity] ?? 9
        return sa - sb
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

  async function handleUpload(caseId: string, file: File) {
    await casesApi.addArtifact(caseId, file)
    await mutate()
  }

  async function handleRerun(caseId: string, level: VerificationLevelNumber) {
    await casesApi.verificationTrigger(caseId, level)
    await mutate()
  }

  async function handleResolve(issueId: string, note: string) {
    await casesApi.verificationResolveIssue(issueId, note)
    // Invalidate every case-view cache that might be open so they reflect
    // the resolve instantly, plus the MD queue (since the issue now also
    // shows there as Awaiting MD).
    await Promise.all([
      mutate(),
      globalMutate(['verification-md-queue']),
      globalMutate(
        (key) =>
          Array.isArray(key) &&
          (key[0] === 'verification-overview' || key[0] === 'verification-level'),
      ),
    ])
  }

  async function handleZip(caseId: string) {
    const res = await casesApi.downloadArtifactsZip(caseId)
    if (!res.ok) throw new Error(res.message || `HTTP ${res.status}`)
    const url = URL.createObjectURL(res.blob)
    const a = document.createElement('a')
    a.href = url
    a.download = res.filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  if (!user) return <Skeleton className="m-6 h-96" />
  if (!canAssess) {
    return (
      <div
        role="alert"
        className="m-6 rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        This page is reserved for assessor roles (Underwriter, AI Analyser,
        Credit HO, Admin). Your account does not have access.
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-0">
      {/* Page header */}
      <div className="px-6 py-5 border-b border-pfl-slate-200 flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-baseline gap-3 flex-wrap">
          <h1 className="text-2xl font-bold text-pfl-slate-900">
            Assessor Queue
          </h1>
          {!isLoading && (
            <span className="text-sm text-pfl-slate-500">
              {items.length === 0 ? 'no gaps to triage' : `${items.length} open`}
            </span>
          )}
        </div>
        <Button variant="ghost" size="sm" onClick={() => mutate()}>
          Refresh
        </Button>
      </div>

      {/* Intro */}
      <div className="px-6 pt-4 pb-4 border-b border-pfl-slate-200">
        <p className="text-sm text-pfl-slate-600 max-w-3xl leading-snug">
          Gap-fix backlog — every OPEN verification-gate issue across cases
          before the MD sees it. For each issue: upload the missing artifact,
          re-run the affected level, and promote to MD only if you can&apos;t
          resolve the gap yourself.
        </p>
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
            Failed to load queue. {(error as Error).message}
          </div>
        )}
        {!isLoading && !error && items.length === 0 && (
          <div className="py-16 text-center text-pfl-slate-500">
            No open issues right now — everything is either resolved or
            already in the MD queue.
          </div>
        )}
        {!isLoading &&
          !error &&
          grouped.map((group, idx) => (
            <CaseDossier
              key={group.header.case_id}
              group={group}
              defaultExpanded={idx === 0}
              onUpload={handleUpload}
              onRerun={handleRerun}
              onResolve={handleResolve}
              onZipDownload={handleZip}
            />
          ))}
      </div>
    </div>
  )
}
