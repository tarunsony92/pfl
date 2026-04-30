'use client'

/**
 * Case detail page — /cases/[id]
 *
 * Layout:
 *   - Page header: Loan ID, applicant name, StageBadge (large)
 *   - Metadata strip: uploaded by, uploaded at, loan amount, applied tenure
 *   - 6-tab panel: Overview / Artifacts / Extractions / Checklist / Dedupe / Audit Log
 *   - Right-aligned action button group
 */

import React from 'react'
import { useParams } from 'next/navigation'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Skeleton } from '@/components/ui/skeleton'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { StageBadge } from '@/components/cases/StageBadge'
import { ArtifactGrid } from '@/components/cases/ArtifactGrid'
import { ExtractionsPanel } from '@/components/cases/ExtractionsPanel'
import { DiscrepanciesPanel } from '@/components/cases/DiscrepanciesPanel'
import { DiscrepancyBanner } from '@/components/cases/DiscrepancyBanner'
import { ChecklistMatrix } from '@/components/cases/ChecklistMatrix'
import { DedupeMatchTable } from '@/components/cases/DedupeMatchTable'
import { AuditLogTimeline } from '@/components/cases/AuditLogTimeline'
import { VerificationPanel } from '@/components/cases/VerificationPanel'
import { ReingestDialog } from '@/components/cases/actions/ReingestDialog'
import { DeletionRequestButton } from '@/components/cases/actions/DeletionRequestButton'
import { AutoRunTrigger } from '@/components/autorun/AutoRunTrigger'
import { ReuploadDialog } from '@/components/cases/actions/ReuploadDialog'
import { AddArtifactDialog } from '@/components/cases/actions/AddArtifactDialog'
import { DownloadArtifactsZipButton } from '@/components/cases/actions/DownloadArtifactsZipButton'
import { CaseInsightsCard } from '@/components/cases/CaseInsightsCard'
import { CaseConcernsProgressCard } from '@/components/cases/CaseConcernsProgressCard'
import { CaseCamDiscrepancyCard } from '@/components/cases/CaseCamDiscrepancyCard'
import { CaseFinalReportCard } from '@/components/cases/CaseFinalReportCard'
// import { FeedbackWidget } from '@/components/cases/FeedbackWidget'  // hidden 2026-04-26 — re-enable by uncommenting here + below
import { useAuth } from '@/components/auth/useAuth'
import { HTTPError } from '@/lib/http'
import {
  useCase,
  useCaseExtractions,
  useCaseChecklist,
  useCaseDedupeMatches,
  useCaseAuditLog,
} from '@/lib/useCase'
import { useVerificationOverview } from '@/lib/useVerification'
import { useCasePolling } from '@/lib/useCasePolling'
import type { CaseStage } from '@/lib/enums'

function formatDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

function MetaRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs font-medium text-pfl-slate-500 uppercase tracking-wide">{label}</span>
      <span className="text-sm text-pfl-slate-900">{value ?? <span className="italic text-pfl-slate-400">—</span>}</span>
    </div>
  )
}

function CaseDetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <tr className="border-b border-pfl-slate-100 last:border-0">
      <td className="py-2 pr-4 text-xs font-medium text-pfl-slate-500 w-40 uppercase tracking-wide align-top">
        {label}
      </td>
      <td className="py-2 text-sm text-pfl-slate-800 break-all">
        {value ?? <span className="italic text-pfl-slate-400">—</span>}
      </td>
    </tr>
  )
}

export default function CaseDetailPage() {
  const params = useParams<{ id: string }>()
  const caseId = params?.id ?? ''

  const { user } = useAuth()
  const isAdmin = user?.role === 'admin' || user?.role === 'ceo' || user?.role === 'credit_ho'
  const userRole = user?.role ?? ''
  const [activeTab, setActiveTab] = React.useState<string>('overview')

  const { data: caseData, error: caseError, isLoading: caseLoading, mutate: mutateCase } = useCase(caseId)
  const { data: extractions, isLoading: extractionsLoading } = useCaseExtractions(caseId)
  const { data: checklist, error: checklistError, isLoading: checklistLoading } = useCaseChecklist(caseId)
  const { data: dedupeMatches, isLoading: dedupeLoading } = useCaseDedupeMatches(caseId)
  const { data: auditLog, isLoading: auditLoading } = useCaseAuditLog(caseId)
  const { data: verificationOverview } = useVerificationOverview(caseId)

  // Poll SWR keys while a worker is actively processing this case
  useCasePolling(caseId, caseData?.current_stage as CaseStage | undefined)

  // Derive download handler — open the attachment-disposition URL so the
  // browser actually saves the file. ``download_url`` is the inline-preview
  // variant and would just open in a new tab; ``attachment_url`` carries
  // ``Content-Disposition: attachment; filename=...`` so the Save dialog
  // appears as the user expects from a "Download" button.
  function handleDownloadArtifact(artifactId: string) {
    const artifact = caseData?.artifacts.find((a) => a.id === artifactId)
    const url = artifact?.attachment_url ?? artifact?.download_url
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer')
    }
  }

  // --- Loading state ---
  if (caseLoading) {
    return (
      <div className="flex flex-col gap-6 px-6 py-6" aria-busy="true" aria-label="Loading case">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  // --- Error state ---
  if (caseError || !caseData) {
    const status = caseError instanceof HTTPError ? caseError.status : null
    return (
      <div
        role="alert"
        className="mx-6 mt-8 rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        {status === 404 ? 'Case not found.' : 'Failed to load case. Please try again.'}
      </div>
    )
  }

  const stage = caseData.current_stage as CaseStage
  const isMissingDocs = stage === 'CHECKLIST_MISSING_DOCS'
  const checklistNotRun =
    checklistError instanceof HTTPError
      ? checklistError.status === 404
      : !checklistLoading && !checklist

  return (
    <div className="flex flex-col gap-0">
      {/* Page header */}
      <div className="px-6 py-5 border-b border-pfl-slate-200">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-pfl-slate-900 font-mono">
                {caseData.loan_id}
              </h1>
              <StageBadge stage={stage} className="text-sm px-3 py-1" />
            </div>
            <p className="text-pfl-slate-600 text-sm">
              {caseData.applicant_name ?? (
                <span className="italic text-pfl-slate-400">No applicant name</span>
              )}
            </p>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 flex-wrap">
            <AutoRunTrigger
              caseId={caseId}
              loanId={caseData.loan_id}
              applicantName={caseData.applicant_name}
            />
            <ReuploadDialog caseId={caseId} mutateCase={mutateCase} />
            {isMissingDocs && (
              <AddArtifactDialog caseId={caseId} mutateCase={mutateCase} />
            )}
            <DownloadArtifactsZipButton
              caseId={caseId}
              loanId={caseData.loan_id}
            />
            {isAdmin && (
              <ReingestDialog
                caseId={caseId}
                currentStage={stage}
                mutateCase={mutateCase}
              />
            )}
            <DeletionRequestButton
              caseData={caseData}
              isAdmin={isAdmin}
              mutateCase={mutateCase}
            />
          </div>
        </div>

        {/* Metadata strip */}
        <div className="mt-4 flex flex-wrap gap-6 border-t border-pfl-slate-100 pt-4">
          <MetaRow label="Uploaded by" value={caseData.uploaded_by.slice(0, 8) + '…'} />
          <MetaRow label="Uploaded at" value={formatDateTime(caseData.uploaded_at)} />
          <MetaRow
            label="Loan amount"
            value={
              caseData.loan_amount != null
                ? `₹ ${caseData.loan_amount.toLocaleString('en-IN')}`
                : null
            }
          />
          <MetaRow
            label="Tenure"
            value={
              caseData.loan_tenure_months != null
                ? `${caseData.loan_tenure_months} months`
                : null
            }
          />
        </div>
      </div>

      {/* Tabs + Feedback */}
      <div className="px-6 py-6">
        <Tabs defaultValue="overview" value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="verification">
              Verification
              {(() => {
                const pending =
                  (verificationOverview?.open_issue_count ?? 0) +
                  (verificationOverview?.awaiting_md_count ?? 0)
                if (pending <= 0) return null
                return (
                  <span
                    className="ml-1.5 inline-flex items-center justify-center min-w-[20px] h-[18px] rounded-full bg-red-600 px-1.5 text-[10px] font-semibold text-white leading-none"
                    title={`${verificationOverview?.open_issue_count ?? 0} open · ${verificationOverview?.awaiting_md_count ?? 0} awaiting MD`}
                  >
                    {pending}
                  </span>
                )
              })()}
            </TabsTrigger>
            <TabsTrigger value="artifacts">
              Artifacts
              {caseData.artifacts.length > 0 && (
                <span className="ml-1.5 rounded-full bg-pfl-slate-200 px-1.5 py-0.5 text-xs text-pfl-slate-600">
                  {caseData.artifacts.length}
                </span>
              )}
            </TabsTrigger>
            <TabsTrigger value="extractions">Extractions</TabsTrigger>
            <TabsTrigger value="discrepancies">
              Discrepancies
            </TabsTrigger>
            <TabsTrigger value="checklist">Checklist</TabsTrigger>
            <TabsTrigger value="dedupe">Dedupe</TabsTrigger>
            <TabsTrigger value="audit">Audit Log</TabsTrigger>
          </TabsList>

          {/* Overview tab */}
          <TabsContent value="overview">
            {/* CAM discrepancy banner — self-quieting when no open flags */}
            <DiscrepancyBanner
              caseId={caseId}
              onGoToTab={() => setActiveTab('discrepancies')}
            />
            {/* AI Insights card */}
            <CaseInsightsCard
              extractions={extractions ?? []}
              dedupeMatches={dedupeMatches ?? []}
              artifacts={caseData.artifacts}
              caseApplicantName={caseData.applicant_name}
              caseLoanAmount={caseData.loan_amount}
            />

            {/* Concerns resolution progress — same gate the final-report PDF uses. */}
            <CaseConcernsProgressCard caseId={caseData.id} />

            {/* In-data conflict check — SystemCam ↔ CM CAM IL sheet reconciliation */}
            <CaseCamDiscrepancyCard extractions={extractions ?? []} />
            {/* Final Verdict Report card moved to the Verification tab so the
                operator only triggers the download after walking the gate. */}

            <Card>
              <CardHeader>
                <CardTitle>Case Details</CardTitle>
              </CardHeader>
              <CardContent>
                <table className="w-full">
                  <tbody>
                    <CaseDetailRow label="Case ID" value={<span className="font-mono text-xs">{caseData.id}</span>} />
                    <CaseDetailRow label="Loan ID" value={<span className="font-mono">{caseData.loan_id}</span>} />
                    <CaseDetailRow label="Applicant" value={caseData.applicant_name} />
                    <CaseDetailRow label="Co-applicant" value={caseData.co_applicant_name} />
                    <CaseDetailRow
                      label="Loan amount"
                      value={
                        caseData.loan_amount != null
                          ? `₹ ${caseData.loan_amount.toLocaleString('en-IN')}`
                          : null
                      }
                    />
                    <CaseDetailRow
                      label="Tenure"
                      value={
                        caseData.loan_tenure_months != null
                          ? `${caseData.loan_tenure_months} months`
                          : null
                      }
                    />
                    <CaseDetailRow label="Stage" value={<StageBadge stage={stage} />} />
                    <CaseDetailRow label="Reupload count" value={caseData.reupload_count} />
                    <CaseDetailRow label="Created" value={formatDateTime(caseData.created_at)} />
                    <CaseDetailRow label="Updated" value={formatDateTime(caseData.updated_at)} />
                    <CaseDetailRow
                      label="Finalized at"
                      value={caseData.finalized_at ? formatDateTime(caseData.finalized_at) : null}
                    />
                  </tbody>
                </table>

                {/* Stage timeline placeholder */}
                {auditLog && auditLog.length > 0 && (
                  <div className="mt-6">
                    <h4 className="text-sm font-semibold text-pfl-slate-700 mb-3">Stage History</h4>
                    <div className="flex flex-col gap-1">
                      {[...auditLog]
                        .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
                        .filter((e) => e.action.toLowerCase().includes('stage') || e.action.toLowerCase().includes('transit'))
                        .slice(0, 8)
                        .map((e) => (
                          <div key={e.id} className="flex items-center gap-2 text-xs text-pfl-slate-600">
                            <span className="w-36 shrink-0 text-pfl-slate-400">
                              {formatDateTime(e.created_at)}
                            </span>
                            <span>{e.action}</span>
                          </div>
                        ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* Artifacts tab */}
          <TabsContent value="artifacts">
            <ArtifactGrid
              artifacts={caseData.artifacts}
              onDownload={handleDownloadArtifact}
            />
          </TabsContent>

          {/* Extractions tab */}
          <TabsContent value="extractions">
            {extractionsLoading ? (
              <div className="flex flex-col gap-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : (
              <ExtractionsPanel extractions={extractions ?? []} />
            )}
          </TabsContent>

          {/* Discrepancies tab — SystemCam vs CM CAM IL conflict resolution */}
          <TabsContent value="discrepancies">
            <DiscrepanciesPanel caseId={caseId} userRole={userRole} />
          </TabsContent>

          {/* Checklist tab */}
          <TabsContent value="checklist">
            <ChecklistMatrix
              result={checklist}
              isLoading={checklistLoading}
              notRun={checklistNotRun}
            />
          </TabsContent>

          {/* Dedupe tab */}
          <TabsContent value="dedupe">
            {dedupeLoading ? (
              <div className="flex flex-col gap-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : (
              <DedupeMatchTable
                matches={dedupeMatches ?? []}
                isAdmin={isAdmin}
                noActiveSnapshot={
                  extractions?.some(
                    (e) =>
                      e.extractor_name === 'dedupe' &&
                      Array.isArray(e.warnings) &&
                      e.warnings.includes('no_active_snapshot'),
                  ) ?? false
                }
              />
            )}
          </TabsContent>

          {/* 4-Level Verification tab */}
          <TabsContent value="verification">
            <VerificationPanel
              caseId={caseId}
              isAdmin={isAdmin}
              currentStage={stage}
            />
            {/* Final Verdict Report — placed at the bottom of the verification
                tab so the operator only triggers the download after walking
                every level + L6 decisioning. The card itself enforces the
                gate (won't emit a PDF until every concern is settled). */}
            <div className="mt-6">
              <CaseFinalReportCard
                caseId={caseData.id}
                loanId={caseData.loan_id}
              />
            </div>
          </TabsContent>

          {/* Audit Log tab */}
          <TabsContent value="audit">
            <AuditLogTimeline entries={auditLog ?? []} isLoading={auditLoading} />
          </TabsContent>
        </Tabs>

        {/* Feedback widget — hidden 2026-04-26; re-enable by uncommenting the
            import at the top + this usage. */}
        {/* <FeedbackWidget caseId={caseId} /> */}
      </div>
    </div>
  )
}
