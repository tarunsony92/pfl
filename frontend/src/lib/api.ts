/**
 * Typed API client.  Groups:
 *   api.auth.*
 *   api.users.*
 *   api.cases.*
 *   api.dedupeSnapshots.*
 *
 * All calls are routed through the Next.js Route Handler proxy at
 * /api/proxy/* (T11) — http.ts handles the prefix automatically.
 */

import { httpDelete, httpGet, httpPatch, httpPost, httpPut } from './http'
import { MrpEntrySchema, type MrpEntry } from './types'
import type {
  AuditLogRead,
  CamDiscrepancyResolutionRead,
  CamDiscrepancyResolveRequest,
  CamDiscrepancySummary,
  CaseArtifactRead,
  CaseExtractionRead,
  CaseInitiateRequest,
  CaseInitiateResponse,
  CaseListResponse,
  CaseRead,
  CasePhotosResponse,
  ChecklistValidationResultRead,
  DecisionResultRead,
  DecisionStepRead,
  DedupeMatchRead,
  DedupeSnapshotRead,
  FeedbackCreate,
  FeedbackRead,
  LevelIssueRead,
  LoginResponse,
  MDQueueResponse,
  MFAEnrollResponse,
  PrecedentsResponse,
  SystemCamEditDecisionRequest,
  SystemCamEditRequestRead,
  TriggerLevelResponse,
  UserRead,
  VerificationLevelDetail,
  VerificationLevelNumber,
  VerificationOverview,
} from './types'

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export const auth = {
  login(email: string, password: string, mfa_code?: string): Promise<LoginResponse> {
    return httpPost<LoginResponse>('/auth/login', { email, password, mfa_code })
  },

  logout(): Promise<void> {
    return httpPost<void>('/auth/logout')
  },

  /** Cookie-based refresh — no body required. */
  refresh(): Promise<LoginResponse> {
    return httpPost<LoginResponse>('/auth/refresh')
  },

  mfaEnroll(): Promise<MFAEnrollResponse> {
    return httpPost<MFAEnrollResponse>('/auth/mfa/enroll')
  },

  mfaVerify(code: string): Promise<void> {
    return httpPost<void>('/auth/mfa/verify', { code })
  },
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

export const users = {
  me(): Promise<UserRead> {
    return httpGet<UserRead>('/users/me')
  },

  list(): Promise<UserRead[]> {
    return httpGet<UserRead[]>('/users/')
  },

  create(payload: {
    email: string
    password: string
    full_name: string
    role: string
  }): Promise<UserRead> {
    return httpPost<UserRead>('/users/', payload)
  },

  updateRole(id: string, role: string): Promise<UserRead> {
    return httpPatch<UserRead>(`/users/${id}/role`, { role })
  },

  updateActive(id: string, is_active: boolean): Promise<UserRead> {
    return httpPatch<UserRead>(`/users/${id}/active`, { is_active })
  },

  changePasswordSelf(new_password: string): Promise<void> {
    return httpPatch<void>('/users/me/password', { new_password })
  },
}

// ---------------------------------------------------------------------------
// Cases
// ---------------------------------------------------------------------------

export interface CaseListFilters {
  limit?: number
  offset?: number
  stage?: string
  uploaded_by?: string
  loan_id_prefix?: string
  from_date?: string
  to_date?: string
  include_deleted?: boolean
}

export const cases = {
  list(filters: CaseListFilters = {}): Promise<CaseListResponse> {
    return httpGet<CaseListResponse>('/cases', { params: filters as Record<string, string | number | boolean | null | undefined> })
  },

  get(id: string): Promise<CaseRead> {
    return httpGet<CaseRead>(`/cases/${id}`)
  },

  initiate(payload: CaseInitiateRequest): Promise<CaseInitiateResponse> {
    return httpPost<CaseInitiateResponse>('/cases/initiate', payload)
  },

  finalize(id: string, payload: { artifact_id?: string } = {}): Promise<CaseRead> {
    return httpPost<CaseRead>(`/cases/${id}/finalize`, payload)
  },

  addArtifact(id: string, file: File): Promise<CaseArtifactRead> {
    const form = new FormData()
    form.append('file', file)
    return httpPost<CaseArtifactRead>(`/cases/${id}/artifacts`, form, {
      headers: {}, // let browser set multipart boundary
    })
  },

  async downloadArtifactsZip(
    id: string,
  ): Promise<{ ok: true; blob: Blob; filename: string } | { ok: false; status: number; message: string }> {
    const res = await fetch(`/api/proxy/cases/${id}/artifacts/zip`, {
      method: 'GET',
      credentials: 'include',
    })
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      return { ok: false, status: res.status, message: body || res.statusText }
    }
    const blob = await res.blob()
    const cd = res.headers.get('Content-Disposition') || ''
    const m = /filename="?([^"]+)"?/.exec(cd)
    return { ok: true, blob, filename: m?.[1] ?? `artifacts.zip` }
  },

  reingest(id: string): Promise<void> {
    return httpPost<void>(`/cases/${id}/reingest`)
  },

  approveReupload(id: string, reason: string): Promise<void> {
    return httpPost<void>(`/cases/${id}/approve-reupload`, { reason })
  },

  delete(id: string): Promise<void> {
    return httpDelete<void>(`/cases/${id}`)
  },

  // ── Two-step deletion-approval flow ──────────────────────────────────
  // Any logged-in user files a request; only MD-role (CEO / ADMIN) can
  // approve or reject. Backend enforces the role gating; the UI just
  // disables the buttons when the current user can't act.
  requestDeletion(id: string, reason: string): Promise<CaseRead> {
    return httpPost<CaseRead>(`/cases/${id}/request-deletion`, { reason })
  },

  approveDeletion(id: string): Promise<CaseRead> {
    return httpPost<CaseRead>(`/cases/${id}/approve-deletion`)
  },

  rejectDeletion(id: string, rationale: string): Promise<CaseRead> {
    return httpPost<CaseRead>(`/cases/${id}/reject-deletion`, { rationale })
  },

  pendingDeletionRequests(): Promise<CaseListResponse> {
    return httpGet<CaseListResponse>(`/cases/deletion-requests/pending`)
  },

  extractions(id: string): Promise<CaseExtractionRead[]> {
    return httpGet<CaseExtractionRead[]>(`/cases/${id}/extractions`)
  },

  extractionByName(id: string, name: string): Promise<CaseExtractionRead> {
    return httpGet<CaseExtractionRead>(`/cases/${id}/extractions/${name}`)
  },

  checklistValidation(id: string): Promise<ChecklistValidationResultRead> {
    return httpGet<ChecklistValidationResultRead>(`/cases/${id}/checklist-validation`)
  },

  /** MD-only: waive a single missing required document with a justification.
   * If the waiver clears every remaining requirement, the backend transitions
   * the case stage out of CHECKLIST_MISSING_DOCS so AutoRun can proceed. */
  checklistWaive(
    id: string,
    doc_type: string,
    justification: string,
  ): Promise<ChecklistValidationResultRead> {
    return httpPost<ChecklistValidationResultRead>(
      `/cases/${id}/checklist/waive`,
      { doc_type, justification },
    )
  },

  dedupeMatches(id: string): Promise<DedupeMatchRead[]> {
    return httpGet<DedupeMatchRead[]>(`/cases/${id}/dedupe-matches`)
  },

  auditLog(id: string): Promise<AuditLogRead[]> {
    return httpGet<AuditLogRead[]>(`/cases/${id}/audit-log`)
  },

  // Phase 1 decisioning (M5)
  phase1Start(id: string): Promise<{ decision_result_id: string }> {
    return httpPost<{ decision_result_id: string }>(`/cases/${id}/phase1`)
  },

  phase1Get(id: string): Promise<DecisionResultRead> {
    return httpGet<DecisionResultRead>(`/cases/${id}/phase1`)
  },

  phase1Steps(id: string): Promise<DecisionStepRead[]> {
    return httpGet<DecisionStepRead[]>(`/cases/${id}/phase1/steps`)
  },

  phase1Step(id: string, stepNumber: number): Promise<DecisionStepRead> {
    return httpGet<DecisionStepRead>(`/cases/${id}/phase1/steps/${stepNumber}`)
  },

  phase1Cancel(id: string): Promise<{ detail: string }> {
    return httpPost<{ detail: string }>(`/cases/${id}/phase1/cancel`)
  },

  submitFeedback(id: string, payload: FeedbackCreate): Promise<FeedbackRead> {
    return httpPost<FeedbackRead>(`/cases/${id}/feedback`, payload)
  },

  listFeedback(id: string): Promise<FeedbackRead[]> {
    return httpGet<FeedbackRead[]>(`/cases/${id}/feedback`)
  },

  // 4-level verification gate
  verificationOverview(id: string): Promise<VerificationOverview> {
    return httpGet<VerificationOverview>(`/cases/${id}/verification`)
  },

  verificationLevelDetail(
    id: string,
    level: VerificationLevelNumber,
  ): Promise<VerificationLevelDetail> {
    return httpGet<VerificationLevelDetail>(
      `/cases/${id}/verification/${level}`,
    )
  },

  verificationTrigger(
    id: string,
    level: VerificationLevelNumber,
  ): Promise<TriggerLevelResponse> {
    return httpPost<TriggerLevelResponse>(
      `/cases/${id}/verification/${level}`,
    )
  },

  verificationResolveIssue(
    issueId: string,
    assessorNote: string,
  ): Promise<LevelIssueRead> {
    return httpPost<LevelIssueRead>(
      `/cases/verification/issues/${issueId}/resolve`,
      { assessor_note: assessorNote },
    )
  },

  verificationDecideIssue(
    issueId: string,
    decision: 'MD_APPROVED' | 'MD_REJECTED',
    mdRationale: string,
  ): Promise<LevelIssueRead> {
    return httpPost<LevelIssueRead>(
      `/cases/verification/issues/${issueId}/decide`,
      { decision, md_rationale: mdRationale },
    )
  },

  /** Hit the final-report endpoint. If the gate is not clear the backend
   * returns HTTP 409 with a JSON body listing the blocking issues — we
   * surface that shape explicitly so the UI can explain what's pending. */
  async finalReport(
    caseId: string,
  ): Promise<
    | { ok: true; blob: Blob; filename: string }
    | {
        ok: false
        status: number
        error: string
        message: string
        blocking: Array<{
          sub_step_id: string
          status: string
          severity: string
          description: string
        }>
      }
  > {
    const res = await fetch(`/api/proxy/cases/${caseId}/final-report`, {
      method: 'GET',
      credentials: 'include',
    })
    if (res.ok) {
      const blob = await res.blob()
      const cd = res.headers.get('Content-Disposition') || ''
      const m = cd.match(/filename="([^"]+)"/)
      return {
        ok: true,
        blob,
        filename: m ? m[1] : `PFL-Final-Report-${caseId}.pdf`,
      }
    }
    let body: Record<string, unknown> = {}
    try {
      body = (await res.json()) as Record<string, unknown>
    } catch {
      body = { error: 'unknown', message: `HTTP ${res.status}`, blocking: [] }
    }
    return {
      ok: false,
      status: res.status,
      error: String(body.error ?? 'unknown'),
      message: String(body.message ?? ''),
      blocking: ((body.blocking as unknown[]) ?? []) as Array<{
        sub_step_id: string
        status: string
        severity: string
        description: string
      }>,
    }
  },

  // CAM discrepancy engine (SystemCam vs CM CAM IL reconciliation)
  camDiscrepancies(id: string): Promise<CamDiscrepancySummary> {
    return httpGet<CamDiscrepancySummary>(`/cases/${id}/cam-discrepancies`)
  },

  resolveCamDiscrepancy(
    id: string,
    fieldKey: string,
    payload: CamDiscrepancyResolveRequest,
  ): Promise<CamDiscrepancyResolutionRead> {
    return httpPost<CamDiscrepancyResolutionRead>(
      `/cases/${id}/cam-discrepancies/${fieldKey}/resolve`,
      payload,
    )
  },

  camDiscrepancyReportUrl(id: string): string {
    // Markdown: plain text/markdown + filename.
    return `/cases/${id}/cam-discrepancies/report`
  },

  camDiscrepancyReportXlsxUrl(id: string): string {
    // XLSX: two-sheet workbook for credit ops review.
    return `/cases/${id}/cam-discrepancies/report.xlsx`
  },

  listSystemCamEditRequests(id: string): Promise<SystemCamEditRequestRead[]> {
    return httpGet<SystemCamEditRequestRead[]>(
      `/cases/${id}/system-cam-edit-requests`,
    )
  },

  decideSystemCamEditRequest(
    id: string,
    requestId: string,
    payload: SystemCamEditDecisionRequest,
  ): Promise<SystemCamEditRequestRead> {
    return httpPost<SystemCamEditRequestRead>(
      `/cases/${id}/system-cam-edit-requests/${requestId}/decide`,
      payload,
    )
  },
}

// ---------------------------------------------------------------------------
// MD Approvals queue — cross-case feed (admin / CEO only)
// ---------------------------------------------------------------------------

export const verification = {
  mdQueue(): Promise<MDQueueResponse> {
    return httpGet<MDQueueResponse>('/verification/md-queue')
  },
  assessorQueue(): Promise<MDQueueResponse> {
    return httpGet<MDQueueResponse>('/verification/assessor-queue')
  },
}

// ---------------------------------------------------------------------------
// Dedupe snapshots
// ---------------------------------------------------------------------------

export const dedupeSnapshots = {
  list(): Promise<DedupeSnapshotRead[]> {
    return httpGet<DedupeSnapshotRead[]>('/dedupe-snapshots/')
  },

  upload(file: File): Promise<DedupeSnapshotRead> {
    const form = new FormData()
    form.append('file', file)
    return httpPost<DedupeSnapshotRead>('/dedupe-snapshots/', form, {
      headers: {}, // let browser set multipart boundary
    })
  },

  active(): Promise<DedupeSnapshotRead | null> {
    return httpGet<DedupeSnapshotRead | null>('/dedupe-snapshots/active')
  },
}

// ---------------------------------------------------------------------------
// Default export (convenience)
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Notifications — Topbar bell data source
// ---------------------------------------------------------------------------

export interface NotificationRead {
  id: string
  case_id: string
  loan_id: string
  applicant_name: string | null
  kind:
    | 'MISSING_DOCS'
    | 'EXTRACTOR_FAILED'
    | 'EXTRACTION_CRITICAL_WARNING'
    | 'DISCREPANCY_BLOCKING'
  severity: 'CRITICAL' | 'WARNING'
  title: string
  description: string
  action_label: string
  action_tab: string
  created_at: string
}

export interface NotificationListResponse {
  total: number
  critical: number
  warning: number
  notifications: NotificationRead[]
}

export const notifications = {
  list(): Promise<NotificationListResponse> {
    return httpGet<NotificationListResponse>('/notifications')
  },
}

// ---------------------------------------------------------------------------
// Admin Learning Rules — per-rule fire counts, MD precedent stats, and the
// suppress / admin-note control surface behind /admin/learning-rules.
// ---------------------------------------------------------------------------

export interface RuleMDDecisionSample {
  issue_id: string
  case_id: string
  decision: 'MD_APPROVED' | 'MD_REJECTED'
  rationale: string | null
  reviewed_at: string
}

export interface RuleStatRead {
  sub_step_id: string
  total_fires: number
  open_count: number
  assessor_resolved_count: number
  md_approved_count: number
  md_rejected_count: number
  is_suppressed: boolean
  admin_note: string | null
  last_edited_at: string | null
  recent_md_samples: RuleMDDecisionSample[]
}

export interface RuleOverrideUpsertRequest {
  is_suppressed?: boolean | null
  admin_note?: string | null
}

export interface RuleOverrideRead {
  sub_step_id: string
  is_suppressed: boolean
  admin_note: string | null
  updated_by: string | null
  last_edited_at: string | null
}

export const adminRules = {
  stats(): Promise<RuleStatRead[]> {
    return httpGet<RuleStatRead[]>('/admin/rules/stats')
  },
  upsertOverride(
    subStepId: string,
    body: RuleOverrideUpsertRequest,
  ): Promise<RuleOverrideRead> {
    return httpPut<RuleOverrideRead>(
      `/admin/rules/overrides/${encodeURIComponent(subStepId)}`,
      body,
    )
  },
  clearOverride(subStepId: string): Promise<{ ok: boolean }> {
    return httpDelete<{ ok: boolean }>(
      `/admin/rules/overrides/${encodeURIComponent(subStepId)}`,
    )
  },
}

// ---------------------------------------------------------------------------
// MRP Catalogue — canonical per-item MRPs backing L3 per-item display.
// ---------------------------------------------------------------------------

export const mrpCatalogue = {
  async list(businessType?: string): Promise<MrpEntry[]> {
    const qs = businessType ? `?business_type=${encodeURIComponent(businessType)}&limit=500&offset=0` : '?limit=500&offset=0'
    const data = await httpGet<unknown>(`/admin/mrp-catalogue${qs}`)
    return MrpEntrySchema.array().parse(data)
  },
  async create(body: {
    business_type: string
    item_description: string
    category: 'equipment' | 'stock' | 'consumable' | 'other'
    mrp_inr: number
    rationale?: string | null
  }): Promise<MrpEntry> {
    const data = await httpPost<unknown>(`/admin/mrp-catalogue`, body)
    return MrpEntrySchema.parse(data)
  },
  async patch(
    id: string,
    body: Partial<{
      mrp_inr: number
      item_description: string
      category: 'equipment' | 'stock' | 'consumable' | 'other'
      rationale: string | null
    }>,
  ): Promise<MrpEntry> {
    const data = await httpPatch<unknown>(`/admin/mrp-catalogue/${id}`, body)
    return MrpEntrySchema.parse(data)
  },
  async delete(id: string): Promise<void> {
    await httpDelete<void>(`/admin/mrp-catalogue/${id}`)
  },
}

// ---------------------------------------------------------------------------
// Admin · L3 bulk-rerun (rolls stale extractions forward to schema v2).
// ---------------------------------------------------------------------------

export type StaleL3Preview = {
  stale_count: number
  case_ids: string[]
  estimated_cost_usd: number
}

export type StaleL3RerunResponse = {
  queued_count: number
  estimated_cost_usd: number
}

export const adminL3 = {
  preview(): Promise<StaleL3Preview> {
    return httpGet<StaleL3Preview>('/admin/l3/stale-extractions')
  },
  rerunStale(): Promise<StaleL3RerunResponse> {
    return httpPost<StaleL3RerunResponse>('/admin/l3/rerun-stale', {})
  },
}

// ---------------------------------------------------------------------------
// Admin · Negative-area pincode list (drives L5 rule #11).
// ---------------------------------------------------------------------------

export type NegativeAreaEntry = {
  id: string
  pincode: string
  reason: string | null
  source: string
  is_active: boolean
  uploaded_by_user_id: string | null
  created_at: string
  updated_at: string
}

export type BulkUploadResponse = {
  inserted: number
  skipped_duplicates: number
  skipped_invalid: string[]
}

export const adminNegativeArea = {
  list(activeOnly = false): Promise<NegativeAreaEntry[]> {
    const qs = activeOnly ? '?active_only=true' : ''
    return httpGet<NegativeAreaEntry[]>(`/admin/negative-areas${qs}`)
  },
  create(body: {
    pincode: string
    reason?: string | null
    source?: string
  }): Promise<NegativeAreaEntry> {
    return httpPost<NegativeAreaEntry>('/admin/negative-areas', body)
  },
  bulkUpload(body: {
    pincodes: string[]
    reason?: string | null
    source?: string
  }): Promise<BulkUploadResponse> {
    return httpPost<BulkUploadResponse>('/admin/negative-areas/bulk', body)
  },
  patch(
    id: string,
    body: { is_active?: boolean; reason?: string | null },
  ): Promise<NegativeAreaEntry> {
    return httpPatch<NegativeAreaEntry>(`/admin/negative-areas/${id}`, body)
  },
  delete(id: string): Promise<{ ok: boolean }> {
    return httpDelete<{ ok: boolean }>(`/admin/negative-areas/${id}`)
  },
}

// ─── Incomplete-autorun gate ───────────────────────────────────────────────
//
// Auto-run completeness gate: list missing required artefacts on a case
// before triggering, and record an entry in the defaulter log when the
// user proceeds anyway.

export interface MissingArtifact {
  subtype: string
  label: string
  optional_alternatives: string[] | null
}

export interface MissingArtifactsResponse {
  case_id: string
  missing: MissingArtifact[]
  is_complete: boolean
}

export interface IncompleteAutorunLogRead {
  id: string
  case_id: string
  user_id: string
  user_email: string | null
  user_full_name: string | null
  case_loan_id: string | null
  case_applicant_name: string | null
  missing_subtypes: string[]
  reason: string | null
  created_at: string
}

export const incompleteAutoruns = {
  missingArtifacts(caseId: string): Promise<MissingArtifactsResponse> {
    return httpGet<MissingArtifactsResponse>(
      `/cases/${caseId}/missing-required-artifacts`,
    )
  },

  recordIncompleteAutorun(
    caseId: string,
    payload: { missing_subtypes: string[]; reason?: string | null },
  ): Promise<IncompleteAutorunLogRead> {
    return httpPost<IncompleteAutorunLogRead>(
      `/cases/${caseId}/incomplete-autorun-log`,
      payload,
    )
  },

  listLogs(params: { limit?: number; offset?: number } = {}): Promise<
    IncompleteAutorunLogRead[]
  > {
    const q = new URLSearchParams()
    if (params.limit != null) q.set('limit', String(params.limit))
    if (params.offset != null) q.set('offset', String(params.offset))
    const qs = q.toString()
    return httpGet<IncompleteAutorunLogRead[]>(
      `/admin/incomplete-autorun-logs${qs ? '?' + qs : ''}`,
    )
  },
}

export const api = {
  auth,
  users,
  cases,
  dedupeSnapshots,
  verification,
  notifications,
  adminRules,
  mrpCatalogue,
  adminL3,
  adminNegativeArea,
  incompleteAutoruns,
}
export default api

// Photo + precedent helpers (MD decision screen)
export async function casePhotos(
  caseId: string,
  subtype: 'HOUSE_VISIT_PHOTO' | 'BUSINESS_PREMISES_PHOTO' | 'BUSINESS_PREMISES_CROP',
): Promise<CasePhotosResponse> {
  return httpGet<CasePhotosResponse>(
    `/cases/${caseId}/photos/${subtype}`,
  )
}

export async function fetchPrecedents(
  subStepId: string,
): Promise<PrecedentsResponse> {
  return httpGet<PrecedentsResponse>(
    `/verification/precedents/${encodeURIComponent(subStepId)}`,
  )
}
