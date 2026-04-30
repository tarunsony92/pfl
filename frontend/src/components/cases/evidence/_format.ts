'use client'
/**
 * Shared formatting + source-artifact helpers for the verification
 * evidence layout. Extracted from VerificationPanel.tsx so the fire
 * path (IssueEvidencePanel) and the pass path (PassDetailDispatcher)
 * consume one source of truth — and so smart-layout cards in this
 * folder can call the same helpers without poking back into the
 * 4000-line panel module.
 */

import { useCase } from '@/lib/useCase'
import type { CaseArtifactRead, LevelIssueRead } from '@/lib/types'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SourceArtifactRef = {
  artifact_id: string
  relevance?: string
  filename?: string
  page?: number
  highlight_field?: string
}

export type ResolvedArtifact = {
  ref: SourceArtifactRef
  artifact: CaseArtifactRead | null
}

/** Verdict shorthand used by every smart-layout card and the
 *  EvidenceTwoColumn header pill. Mirrors the existing `Verdict` type
 *  inside VerificationPanel.tsx but limited to the four states a rule
 *  can land in (no `info` / `overridden` — those belong to the row
 *  status pill, not the evidence header). */
export type EvidenceVerdict = 'pass' | 'warn' | 'fail' | 'skipped'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Keys that carry raw artefact values the UI should NEVER display verbatim
 *  inside the structured-evidence panel — they're either huge
 *  (gps_watermark_meta, usage) or redundant with other fields
 *  (resolution, evidence_type tags). */
export const HIDDEN_EVIDENCE_KEYS = new Set<string>([
  'usage',
  'cost_usd',
  'model_used',
  'resolution',
  'loan_agreement_parties_scanned',
  // Consumed by the source-artifact column — not for the generic dump.
  'source_artifacts',
  // Legacy opaque blobs from earlier opus_credit_verdict payloads. Newer
  // issues pull these fields out into typed keys (applicant_verdict, etc.)
  // which the generic renderer handles cleanly. Keeping these hidden means
  // a re-run lights up the structured display while older stored issues
  // don't regress into a raw JSON dump.
  'analyst',
  'party',
  // L5: the raw rubric row is a big nested object; the issue description
  // already carries the salient bits (row number, parameter, weight).
  'row',
  // L5 scoring summary keys are all consumed by ScoringSummaryCard; the
  // generic key/value table would duplicate the score + list.
  'failing_rows',
  'weakest_sections',
  'top_misses',
  'section_title',
  'grade',
  'earned',
  'max_score',
  'pct',
  'section_id',
])

/** Map ArtifactSubtype → a short, human label for the source-file viewer.
 *  Used when ``source_artifacts[].relevance`` isn't set (fallback path). */
export const SUBTYPE_LABEL: Record<string, string> = {
  KYC_AADHAAR: 'Applicant Aadhaar',
  CO_APPLICANT_AADHAAR: 'Co-applicant Aadhaar',
  KYC_PAN: 'Applicant PAN',
  CO_APPLICANT_PAN: 'Co-applicant PAN',
  RATION_CARD: 'Ration card',
  ELECTRICITY_BILL: 'Electricity bill',
  HOUSE_VISIT_PHOTO: 'House visit photo',
  BUSINESS_PREMISES_PHOTO: 'Business premises photo',
  BANK_STATEMENT: 'Bank statement',
  EQUIFAX_HTML: 'Equifax bureau report',
  CIBIL_HTML: 'CIBIL bureau report',
  HIGHMARK_HTML: 'HighMark bureau report',
  EXPERIAN_HTML: 'Experian bureau report',
  LAGR: 'Loan agreement',
  LAPP: 'Loan application',
  AUTO_CAM: 'Auto CAM sheet',
  PD_SHEET: 'PD sheet',
  CHECKLIST: 'Checklist',
}

// ---------------------------------------------------------------------------
// Pretty-printers
// ---------------------------------------------------------------------------

/** Pretty-print one evidence value — handles strings, numbers, tuples
 *  (lat/lon), and short arrays/objects. Long arrays/objects get collapsed
 *  to a ``JSON.stringify`` preview so the panel stays compact. */
export function formatEvidenceValue(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  if (Array.isArray(v)) {
    if (v.length === 2 && typeof v[0] === 'number' && typeof v[1] === 'number') {
      return `${v[0].toFixed(5)}, ${v[1].toFixed(5)}`
    }
    if (v.every((x) => typeof x === 'string')) return (v as string[]).join(' · ')
    return JSON.stringify(v)
  }
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/** Humanise an evidence-dict key → label. Keeps the mechanical names
 *  (applicant_address, gps_coords) comprehensible without hand-writing a
 *  label per key. */
export function humanKey(k: string): string {
  return k
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/Gps/g, 'GPS')
    .replace(/Coapp/g, 'Co-app')
    .replace(/Aadhaar Father/g, 'Aadhaar father')
}

export function formatBytes(n: number | null | undefined): string {
  if (n == null) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export function isImageArtifact(art: CaseArtifactRead): boolean {
  if (art.content_type?.startsWith('image/')) return true
  return /\.(jpe?g|png|webp|gif|bmp|heic|tiff?)$/i.test(art.filename)
}

export function isPdfArtifact(art: CaseArtifactRead): boolean {
  if (art.content_type === 'application/pdf') return true
  return /\.pdf$/i.test(art.filename)
}

export function isHtmlArtifact(art: CaseArtifactRead): boolean {
  if (art.content_type === 'text/html') return true
  return /\.html?$/i.test(art.filename)
}

export function artifactLabel(art: CaseArtifactRead, refRelevance?: string): string {
  if (refRelevance) return refRelevance
  if (art.subtype && SUBTYPE_LABEL[art.subtype]) return SUBTYPE_LABEL[art.subtype]
  if (art.subtype) return art.subtype.replace(/_/g, ' ').toLowerCase()
  return art.filename
}

// ---------------------------------------------------------------------------
// Source-artifact extraction
// ---------------------------------------------------------------------------

/** Parse a raw `source_artifacts` array (from either an issue's evidence
 *  dict or a pass_evidence entry) into typed refs. Any row missing
 *  artifact_id is dropped silently. */
export function extractSourceArtifactRefs(
  ev: Record<string, unknown> | null | undefined,
): SourceArtifactRef[] {
  if (!ev) return []
  const raw = ev['source_artifacts']
  if (!Array.isArray(raw)) return []
  return raw
    .filter(
      (r): r is Record<string, unknown> =>
        !!r &&
        typeof r === 'object' &&
        typeof (r as Record<string, unknown>)['artifact_id'] === 'string',
    )
    .map((r) => ({
      artifact_id: r['artifact_id'] as string,
      relevance: typeof r['relevance'] === 'string' ? (r['relevance'] as string) : undefined,
      filename: typeof r['filename'] === 'string' ? (r['filename'] as string) : undefined,
      page: typeof r['page'] === 'number' ? (r['page'] as number) : undefined,
      highlight_field:
        typeof r['highlight_field'] === 'string' ? (r['highlight_field'] as string) : undefined,
    }))
}

/** Source refs for a fire-path issue. Prefers `evidence.source_artifacts`,
 *  falls back to the legacy single `issue.artifact_id`. */
export function extractIssueSourceRefs(issue: LevelIssueRead): SourceArtifactRef[] {
  const refs = extractSourceArtifactRefs(
    (issue.evidence ?? {}) as Record<string, unknown>,
  )
  if (refs.length > 0) return refs
  if (issue.artifact_id) return [{ artifact_id: issue.artifact_id }]
  return []
}

// ---------------------------------------------------------------------------
// Resolution hook
// ---------------------------------------------------------------------------

/** Resolve a list of `SourceArtifactRef` against the case's artefact list.
 *  Returns the matched artefact (or null if no longer on the case) for each
 *  ref, plus a loading flag. SWR dedupes the underlying useCase fetch so
 *  callers don't need to memoise. */
export function useResolvedArtifacts(
  caseId: string,
  refs: SourceArtifactRef[],
): { matched: ResolvedArtifact[]; isLoading: boolean } {
  const { data, isLoading } = useCase(caseId)
  const artifactsById = new Map<string, CaseArtifactRead>()
  for (const a of data?.artifacts ?? []) artifactsById.set(a.id, a)
  const matched: ResolvedArtifact[] = refs.map((ref) => ({
    ref,
    artifact: artifactsById.get(ref.artifact_id) ?? null,
  }))
  return { matched, isLoading }
}
