'use client'

/**
 * DiscrepanciesPanel — the "Discrepancies" tab on the case detail page.
 *
 * Shows SystemCam (finpage / bureau authoritative) vs CM CAM IL (manual,
 * BCM / Credit HO) conflicts for the current case, lets the assessor
 * resolve each one (Correct CM CAM IL / Request SystemCam edit / Justify),
 * lists any pending SystemCam edit requests + lets admin / CEO approve
 * or reject. Provides a Markdown report download.
 */

import React, { useState } from 'react'
import { AlertTriangleIcon, CheckCircleIcon, XCircleIcon, DownloadIcon } from 'lucide-react'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useCamDiscrepancies } from '@/lib/useCamDiscrepancies'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import type {
  CamDiscrepancySummary,
  CamDiscrepancyView,
  DiscrepancyResolutionKind,
  SystemCamEditRequestRead,
} from '@/lib/types'

interface DiscrepanciesPanelProps {
  caseId: string
  /** Role of the current user — drives resolve + approve permissions. */
  userRole: string
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

export function DiscrepanciesPanel({ caseId, userRole }: DiscrepanciesPanelProps) {
  const canResolve = userRole === 'admin' || userRole === 'ai_analyser'
  const canApprove = userRole === 'admin' || userRole === 'ceo'

  const {
    data: summary,
    error,
    isLoading,
    mutate,
  } = useCamDiscrepancies(caseId, { refreshInterval: 0 })

  const {
    data: editRequests,
    mutate: mutateRequests,
  } = useSWR<SystemCamEditRequestRead[]>(
    `/cases/${caseId}/system-cam-edit-requests`,
    () => api.cases.listSystemCamEditRequests(caseId),
    { refreshInterval: 0 },
  )

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    )
  }
  if (error || !summary) {
    return (
      <p className="text-sm text-red-700" data-testid="discrepancies-error">
        Failed to load discrepancies. {String(error)}
      </p>
    )
  }

  const openCritical = summary.views.filter(
    (v) => v.flag && !v.resolution && v.flag.severity === 'CRITICAL',
  )
  const openWarning = summary.views.filter(
    (v) => v.flag && !v.resolution && v.flag.severity === 'WARNING',
  )
  const resolved = summary.views.filter((v) => v.resolution)

  return (
    <div className="flex flex-col gap-4" data-testid="discrepancies-panel">
      {/* Summary bar */}
      <SummaryBar summary={summary} caseId={caseId} />

      {/* Open critical */}
      {openCritical.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-red-800 mb-2">
            Critical — Phase 1 blocked
          </h3>
          <div className="flex flex-col gap-2">
            {openCritical.map((v) => (
              <DiscrepancyCard
                key={v.field_key}
                view={v}
                caseId={caseId}
                canResolve={canResolve}
                onResolved={async () => {
                  await mutate()
                  await mutateRequests()
                }}
              />
            ))}
          </div>
        </section>
      )}

      {/* Open warning */}
      {openWarning.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-amber-800 mb-2">
            Warnings
          </h3>
          <div className="flex flex-col gap-2">
            {openWarning.map((v) => (
              <DiscrepancyCard
                key={v.field_key}
                view={v}
                caseId={caseId}
                canResolve={canResolve}
                onResolved={async () => {
                  await mutate()
                  await mutateRequests()
                }}
              />
            ))}
          </div>
        </section>
      )}

      {/* Resolved */}
      {resolved.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-slate-700 mb-2">
            Resolved ({resolved.length})
          </h3>
          <div className="flex flex-col gap-2">
            {resolved.map((v) => (
              <DiscrepancyCard
                key={v.field_key}
                view={v}
                caseId={caseId}
                canResolve={canResolve}
                onResolved={async () => {
                  await mutate()
                  await mutateRequests()
                }}
              />
            ))}
          </div>
        </section>
      )}

      {/* Edit request queue */}
      {editRequests && editRequests.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-slate-800 mb-2">
            SystemCam edit requests
          </h3>
          <div className="flex flex-col gap-2">
            {editRequests.map((r) => (
              <EditRequestCard
                key={r.id}
                request={r}
                caseId={caseId}
                canApprove={canApprove}
                onDecided={async () => {
                  await mutate()
                  await mutateRequests()
                }}
              />
            ))}
          </div>
        </section>
      )}

      {summary.total === 0 && (
        <p className="text-sm text-slate-500 italic" data-testid="discrepancies-empty">
          No CAM discrepancies detected for this case. Phase 1 is unblocked.
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Summary bar
// ---------------------------------------------------------------------------

function SummaryBar({
  summary,
  caseId,
}: {
  summary: CamDiscrepancySummary
  caseId: string
}) {
  const reportHref = `/api/proxy${api.cases.camDiscrepancyReportUrl(caseId)}`
  const reportXlsxHref = `/api/proxy${api.cases.camDiscrepancyReportXlsxUrl(caseId)}`
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between gap-3 text-sm">
          <span>CAM discrepancy status</span>
          <div className="flex items-center gap-3">
            <a
              href={reportXlsxHref}
              download
              className="inline-flex items-center gap-1 text-xs text-pfl-blue-700 hover:underline"
              data-testid="discrepancies-report-xlsx"
            >
              <DownloadIcon className="h-3 w-3" aria-hidden="true" /> .xlsx
            </a>
            <a
              href={reportHref}
              download
              className="inline-flex items-center gap-1 text-xs text-pfl-blue-700 hover:underline"
              data-testid="discrepancies-report-download"
            >
              <DownloadIcon className="h-3 w-3" aria-hidden="true" /> .md
            </a>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Total checked" value={String(summary.total)} />
          <Stat
            label="Critical open"
            value={String(summary.unresolved_critical)}
            tone={summary.unresolved_critical > 0 ? 'danger' : 'ok'}
          />
          <Stat
            label="Warning open"
            value={String(summary.unresolved_warning)}
            tone={summary.unresolved_warning > 0 ? 'warn' : 'ok'}
          />
          <Stat
            label="Phase 1 gate"
            value={summary.phase1_blocked ? 'BLOCKED' : 'OPEN'}
            tone={summary.phase1_blocked ? 'danger' : 'ok'}
          />
        </div>
      </CardContent>
    </Card>
  )
}

function Stat({
  label,
  value,
  tone = 'neutral',
}: {
  label: string
  value: string
  tone?: 'ok' | 'warn' | 'danger' | 'neutral'
}) {
  const toneCls = {
    ok: 'text-green-800',
    warn: 'text-amber-800',
    danger: 'text-red-800',
    neutral: 'text-slate-800',
  }[tone]
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wide text-slate-500">{label}</span>
      <span className={cn('font-mono text-sm font-semibold', toneCls)}>{value}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Per-field discrepancy card
// ---------------------------------------------------------------------------

function DiscrepancyCard({
  view,
  caseId,
  canResolve,
  onResolved,
}: {
  view: CamDiscrepancyView
  caseId: string
  canResolve: boolean
  onResolved: () => Promise<void>
}) {
  const [expanded, setExpanded] = useState(!view.resolution)
  const flag = view.flag
  const res = view.resolution
  const pending = view.pending_edit_request

  const severityColor = flag
    ? flag.severity === 'CRITICAL'
      ? 'border-red-300 bg-red-50'
      : 'border-amber-300 bg-amber-50'
    : 'border-slate-200 bg-white'

  return (
    <div
      className={cn('rounded-lg border p-3', severityColor)}
      data-testid={`discrepancy-card-${view.field_key}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2 min-w-0 flex-1">
          {flag ? (
            flag.severity === 'CRITICAL' ? (
              <XCircleIcon className="h-4 w-4 text-red-700 mt-0.5 shrink-0" aria-hidden="true" />
            ) : (
              <AlertTriangleIcon className="h-4 w-4 text-amber-700 mt-0.5 shrink-0" aria-hidden="true" />
            )
          ) : (
            <CheckCircleIcon className="h-4 w-4 text-green-700 mt-0.5 shrink-0" aria-hidden="true" />
          )}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-slate-900">{view.field_label}</p>
            {flag && (
              <p className="text-xs text-slate-700 mt-1">{flag.note}</p>
            )}
            {flag && (
              <div className="flex flex-wrap gap-2 mt-2">
                <Pair label="SystemCam" value={flag.system_cam_value} mono />
                <Pair label="CM CAM IL" value={flag.cm_cam_il_value} mono />
                {flag.diff_abs != null && (
                  <Pair
                    label="Diff"
                    value={`${flag.diff_abs} (${flag.diff_pct?.toFixed(2)}%)`}
                    mono
                  />
                )}
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {res && (
            <Badge variant="outline" className="text-xs uppercase">
              {res.kind.replace(/_/g, ' ')}
            </Badge>
          )}
          {pending && (
            <Badge variant="warning" className="text-xs uppercase">
              Edit pending
            </Badge>
          )}
          <button
            type="button"
            className="text-xs text-pfl-blue-700 hover:underline"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? 'Collapse' : 'Open'}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="mt-3 flex flex-col gap-3">
          {res && (
            <div className="rounded bg-slate-50 border border-slate-200 px-3 py-2 text-xs">
              <p className="font-semibold text-slate-700 mb-1">
                Resolution ({res.kind.replace(/_/g, ' ')})
              </p>
              {res.corrected_value && (
                <p>
                  <span className="text-slate-500">Value used:</span>{' '}
                  <span className="font-mono">{res.corrected_value}</span>
                </p>
              )}
              <p className="text-slate-700 mt-1 whitespace-pre-wrap">{res.comment}</p>
              <p className="text-slate-400 mt-1">
                by {res.resolved_by} · {new Date(res.resolved_at).toLocaleString()}
              </p>
            </div>
          )}

          {flag && canResolve && (
            <ResolveForm
              caseId={caseId}
              fieldKey={view.field_key}
              systemCamValue={flag.system_cam_value}
              cmIlValue={flag.cm_cam_il_value}
              onResolved={onResolved}
              existingResolution={res ?? null}
            />
          )}
          {flag && !canResolve && (
            <p className="text-xs text-slate-500 italic">
              You don't have permission to resolve this discrepancy. Ask an
              ai_analyser or admin.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function Pair({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string | null | undefined
  mono?: boolean
}) {
  return (
    <div className="text-xs">
      <span className="text-slate-500 uppercase tracking-wide mr-1">{label}:</span>
      <span className={cn(mono && 'font-mono', 'text-slate-800')}>
        {value == null || value === '' ? '—' : value}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Resolve form
// ---------------------------------------------------------------------------

function ResolveForm({
  caseId,
  fieldKey,
  systemCamValue,
  cmIlValue,
  onResolved,
  existingResolution,
}: {
  caseId: string
  fieldKey: string
  systemCamValue: string | null
  cmIlValue: string | null
  onResolved: () => Promise<void>
  existingResolution: { kind: DiscrepancyResolutionKind } | null
}) {
  const [kind, setKind] = useState<DiscrepancyResolutionKind>(
    existingResolution?.kind ?? 'CORRECTED_CM_IL',
  )
  const [correctedValue, setCorrectedValue] = useState<string>(systemCamValue ?? '')
  const [comment, setComment] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const needsValue = kind !== 'JUSTIFIED'
  const canSubmit =
    comment.trim().length >= 10 && (!needsValue || correctedValue.trim().length > 0)

  async function submit() {
    setErr(null)
    setSubmitting(true)
    try {
      await api.cases.resolveCamDiscrepancy(caseId, fieldKey, {
        kind,
        comment,
        corrected_value: needsValue ? correctedValue : null,
      })
      setComment('')
      await onResolved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <fieldset className="flex flex-col gap-2">
        <legend className="text-xs font-semibold text-slate-700">How to resolve</legend>
        <RadioOpt
          id={`${fieldKey}-cm`}
          name={`kind-${fieldKey}`}
          value="CORRECTED_CM_IL"
          checked={kind === 'CORRECTED_CM_IL'}
          onChange={() => {
            setKind('CORRECTED_CM_IL')
            setCorrectedValue(systemCamValue ?? '')
          }}
          label="Correct CM CAM IL (assessor self-serve)"
          hint={`Write this value into the manual sheet: ${systemCamValue ?? '(empty)'} — or edit below.`}
        />
        <RadioOpt
          id={`${fieldKey}-sc`}
          name={`kind-${fieldKey}`}
          value="SYSTEMCAM_EDIT_REQUESTED"
          checked={kind === 'SYSTEMCAM_EDIT_REQUESTED'}
          onChange={() => {
            setKind('SYSTEMCAM_EDIT_REQUESTED')
            setCorrectedValue(cmIlValue ?? '')
          }}
          label="Request SystemCam edit (CEO / admin approval required)"
          hint="Use this when the finpage / bureau value is stale or wrong."
        />
        <RadioOpt
          id={`${fieldKey}-just`}
          name={`kind-${fieldKey}`}
          value="JUSTIFIED"
          checked={kind === 'JUSTIFIED'}
          onChange={() => setKind('JUSTIFIED')}
          label="Justify (leave both values as-is, record why the divergence is acceptable)"
        />
      </fieldset>

      {needsValue && (
        <label className="text-xs flex flex-col gap-1">
          <span className="text-slate-600 font-semibold">Corrected value</span>
          <input
            type="text"
            value={correctedValue}
            onChange={(e) => setCorrectedValue(e.target.value)}
            className="border border-slate-300 rounded px-2 py-1 text-sm"
            data-testid={`corrected-value-${fieldKey}`}
          />
        </label>
      )}

      <label className="text-xs flex flex-col gap-1">
        <span className="text-slate-600 font-semibold">Assessor comment (required, ≥ 10 chars)</span>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={3}
          className="border border-slate-300 rounded px-2 py-1 text-sm"
          placeholder="Why this resolution? The full text lands in the audit report."
          data-testid={`comment-${fieldKey}`}
        />
      </label>

      {err && <p className="text-xs text-red-700" role="alert">{err}</p>}

      <div className="flex justify-end">
        <button
          type="button"
          disabled={!canSubmit || submitting}
          onClick={submit}
          className={cn(
            'text-xs rounded px-3 py-1.5 font-semibold',
            canSubmit && !submitting
              ? 'bg-pfl-blue-700 text-white hover:bg-pfl-blue-800'
              : 'bg-slate-200 text-slate-500 cursor-not-allowed',
          )}
          data-testid={`resolve-submit-${fieldKey}`}
        >
          {submitting ? 'Saving…' : 'Save resolution'}
        </button>
      </div>
    </div>
  )
}

function RadioOpt({
  id,
  name,
  value,
  checked,
  onChange,
  label,
  hint,
}: {
  id: string
  name: string
  value: string
  checked: boolean
  onChange: () => void
  label: string
  hint?: string
}) {
  return (
    <label htmlFor={id} className="flex gap-2 items-start text-xs text-slate-800 cursor-pointer">
      <input
        id={id}
        name={name}
        value={value}
        checked={checked}
        onChange={onChange}
        type="radio"
        className="mt-0.5"
      />
      <span className="flex flex-col">
        <span className="font-medium">{label}</span>
        {hint && <span className="text-slate-500">{hint}</span>}
      </span>
    </label>
  )
}

// ---------------------------------------------------------------------------
// SystemCam edit request card
// ---------------------------------------------------------------------------

function EditRequestCard({
  request,
  caseId,
  canApprove,
  onDecided,
}: {
  request: SystemCamEditRequestRead
  caseId: string
  canApprove: boolean
  onDecided: () => Promise<void>
}) {
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState<null | 'approve' | 'reject'>(null)
  const [err, setErr] = useState<string | null>(null)
  const isPending = request.status === 'PENDING'

  async function decide(approve: boolean) {
    if (comment.trim().length < 10) {
      setErr('Decision comment must be at least 10 characters.')
      return
    }
    setErr(null)
    setSubmitting(approve ? 'approve' : 'reject')
    try {
      await api.cases.decideSystemCamEditRequest(caseId, request.id, {
        approve,
        decision_comment: comment,
      })
      setComment('')
      await onDecided()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(null)
    }
  }

  const statusColor =
    request.status === 'APPROVED'
      ? 'bg-green-100 text-green-800'
      : request.status === 'REJECTED'
      ? 'bg-red-100 text-red-800'
      : request.status === 'WITHDRAWN'
      ? 'bg-slate-100 text-slate-700'
      : 'bg-amber-100 text-amber-800'

  return (
    <div className="rounded-lg border border-slate-200 p-3 bg-white">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-slate-900">
            {request.field_label}
          </p>
          <p className="text-xs text-slate-700 mt-1">{request.justification}</p>
          <div className="flex flex-wrap gap-2 mt-2">
            <Pair label="Current" value={request.current_system_cam_value} mono />
            <Pair label="Requested" value={request.requested_system_cam_value} mono />
          </div>
          <p className="text-[10px] text-slate-400 mt-1">
            by {request.requested_by} · {new Date(request.requested_at).toLocaleString()}
          </p>
          {request.decided_at && (
            <p className="text-[10px] text-slate-400">
              decided {new Date(request.decided_at).toLocaleString()}: {request.decision_comment}
            </p>
          )}
        </div>
        <span className={cn('inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase', statusColor)}>
          {request.status}
        </span>
      </div>

      {isPending && canApprove && (
        <div className="mt-3 flex flex-col gap-2">
          <textarea
            rows={2}
            className="border border-slate-300 rounded px-2 py-1 text-xs"
            placeholder="Decision comment (required, ≥ 10 chars)"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            data-testid={`edit-req-comment-${request.id}`}
          />
          {err && <p className="text-xs text-red-700" role="alert">{err}</p>}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              disabled={submitting !== null || comment.trim().length < 10}
              onClick={() => decide(false)}
              className={cn(
                'text-xs rounded px-3 py-1 font-semibold',
                'bg-slate-100 text-slate-700 hover:bg-slate-200',
                (submitting !== null || comment.trim().length < 10) && 'opacity-50 cursor-not-allowed',
              )}
              data-testid={`edit-req-reject-${request.id}`}
            >
              {submitting === 'reject' ? 'Rejecting…' : 'Reject'}
            </button>
            <button
              type="button"
              disabled={submitting !== null || comment.trim().length < 10}
              onClick={() => decide(true)}
              className={cn(
                'text-xs rounded px-3 py-1 font-semibold',
                'bg-green-700 text-white hover:bg-green-800',
                (submitting !== null || comment.trim().length < 10) && 'opacity-50 cursor-not-allowed',
              )}
              data-testid={`edit-req-approve-${request.id}`}
            >
              {submitting === 'approve' ? 'Approving…' : 'Approve'}
            </button>
          </div>
        </div>
      )}
      {isPending && !canApprove && (
        <p className="text-xs text-slate-500 italic mt-2">
          Pending CEO / admin decision.
        </p>
      )}
    </div>
  )
}
