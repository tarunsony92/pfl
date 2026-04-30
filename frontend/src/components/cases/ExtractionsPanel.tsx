'use client'

/**
 * ExtractionsPanel — accordion-style panel for each extractor result.
 *
 * For each CaseExtractionRead:
 *   - Header: extractor name + field count chip + status badge + warning count
 *   - Body: key-value table, raw JSON toggle, warnings, error
 *
 * Badge is derived from an EFFECTIVE status that re-maps backend PARTIAL to
 * SUCCESS when data was extracted and warnings are low-severity (see
 * effectiveStatus() below). This avoids the confusing "PARTIAL (data found)"
 * label when a single non-critical warning flips a full extract to PARTIAL.
 */

import React, { useState } from 'react'
import { AlertTriangleIcon, ChevronDownIcon, ChevronRightIcon } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/cn'
import type { CaseExtractionRead } from '@/lib/types'

interface ExtractionsPanelProps {
  extractions: CaseExtractionRead[]
}

/** Friendly names for known extractor names */
const EXTRACTOR_LABELS: Record<string, string> = {
  auto_cam: 'AutoCAM',
  checklist: 'Checklist',
  pd_sheet: 'PD Sheet',
  equifax: 'Equifax',
  bank_statement: 'Bank Statement',
  dedupe: 'Dedupe Aggregate',
}

function extractorLabel(name: string): string {
  return EXTRACTOR_LABELS[name.toLowerCase()] ?? name
}

/**
 * Derive a human subject for an extraction — typically the applicant or
 * customer name pulled from the extraction payload. Used to disambiguate
 * multiple rows of the same extractor (e.g. three Equifax reports, one
 * per applicant / co-applicant).
 */
function extractionSubject(extraction: CaseExtractionRead): string | null {
  const data = (extraction.data ?? {}) as Record<string, unknown>
  const candidates: unknown[] = [
    (data.customer_info as Record<string, unknown> | undefined)?.name,
    (data.system_cam as Record<string, unknown> | undefined)?.applicant_name,
    (data.eligibility as Record<string, unknown> | undefined)?.applicant_name,
    (data.cm_cam_il as Record<string, unknown> | undefined)?.borrower_name,
    (data.fields as Record<string, unknown> | undefined)?.applicant_name,
    data.account_holder,
  ]
  for (const c of candidates) {
    if (typeof c === 'string' && c.trim()) return c.trim()
  }
  return null
}

/** For Equifax specifically, annotate a no-hit report as NTC so the user
 * can tell at a glance that the bureau returned "no record" rather than
 * a clean report with a blank score. */
function extractionQualifier(extraction: CaseExtractionRead): string | null {
  if (extraction.extractor_name.toLowerCase() === 'equifax') {
    const data = (extraction.data ?? {}) as Record<string, unknown>
    if (data.bureau_hit === false) return 'NTC / no bureau record'
    const score = data.credit_score
    if (typeof score === 'number' && score > 0) return `score ${score}`
  }
  return null
}

/**
 * Recursively count non-null, non-object, non-array leaf values.
 */
function countLeafValues(obj: unknown): number {
  if (obj === null || obj === undefined) return 0
  if (typeof obj !== 'object') return 1
  if (Array.isArray(obj)) {
    return obj.reduce<number>((acc, v) => acc + countLeafValues(v), 0)
  }
  return Object.values(obj as Record<string, unknown>).reduce<number>(
    (acc, v) => acc + countLeafValues(v),
    0,
  )
}

type StatusVariant = 'success' | 'warning' | 'destructive'
type EffectiveStatus = 'SUCCESS' | 'PARTIAL' | 'FAILED'

/** Warnings that indicate the extractor couldn't recover the primary output. */
const CRITICAL_WARNING_PREFIXES = [
  'missing_credit_score',        // equifax: no CIBIL score found
  'no_accounts',                 // equifax: no tradelines found
  'no_account_header_detected',  // bank_statement: couldn't identify account
  'missing_applicant_name',      // auto_cam: couldn't identify applicant
  'no_known_fields_matched',     // pd_sheet: no structured fields matched
]

function hasCriticalWarning(warnings: string[] | null | undefined): boolean {
  if (!warnings || warnings.length === 0) return false
  return warnings.some((w) =>
    CRITICAL_WARNING_PREFIXES.some((prefix) => w.startsWith(prefix)),
  )
}

/**
 * Effective display status — re-maps backend PARTIAL to SUCCESS when the
 * extractor pulled usable data and warnings are low-severity. Rule:
 *   FAILED  — backend FAILED OR no fields extracted
 *   PARTIAL — fields > 0 AND (warnings ≥ 3 OR critical warning present)
 *   SUCCESS — otherwise
 * Backend SUCCESS is always surfaced as SUCCESS.
 */
function effectiveStatus(
  status: string,
  fieldCount: number,
  warnings: string[] | null | undefined,
): EffectiveStatus {
  const upper = status.toUpperCase()
  if (fieldCount === 0 || upper === 'FAILED') return 'FAILED'
  if (upper === 'SUCCESS') return 'SUCCESS'
  const warningCount = warnings?.length ?? 0
  if (warningCount >= 3 || hasCriticalWarning(warnings)) return 'PARTIAL'
  return 'SUCCESS'
}

function statusVariant(effective: EffectiveStatus): StatusVariant {
  switch (effective) {
    case 'SUCCESS': return 'success'
    case 'PARTIAL': return 'warning'
    default: return 'destructive'
  }
}

/** Renders a key-value table from a flat record. Nested objects fall through to JSON. */
function KVTable({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data)
  if (entries.length === 0) return <p className="text-xs text-pfl-slate-400 italic">No data</p>

  return (
    <table className="w-full text-xs border-collapse">
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k} className="border-b border-pfl-slate-100 last:border-0">
            <td className="py-1.5 pr-3 font-medium text-pfl-slate-600 w-1/3 align-top whitespace-nowrap">
              {k}
            </td>
            <td className="py-1.5 text-pfl-slate-800 break-all">
              {v === null || v === undefined
                ? <span className="italic text-pfl-slate-400">—</span>
                : typeof v === 'object'
                ? <span className="font-mono text-pfl-slate-500">{JSON.stringify(v)}</span>
                : String(v)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ExtractionItem({ extraction }: { extraction: CaseExtractionRead }) {
  const [isOpen, setIsOpen] = useState(false)
  const [showRaw, setShowRaw] = useState(false)

  const warningCount = extraction.warnings?.length ?? 0
  const fieldCount = countLeafValues(extraction.data)
  const effective = effectiveStatus(extraction.status, fieldCount, extraction.warnings)
  const variant = statusVariant(effective)
  const isPartial = effective === 'PARTIAL'

  return (
    <div className={cn(
      'rounded-lg border overflow-hidden',
      isPartial ? 'border-amber-200' : 'border-pfl-slate-200',
    )}>
      {/* Header / toggle */}
      <button
        type="button"
        className={cn(
          'w-full flex items-center gap-3 px-4 py-3 transition-colors text-left',
          isPartial
            ? 'bg-amber-50 hover:bg-amber-100'
            : 'bg-pfl-slate-50 hover:bg-pfl-slate-100',
        )}
        onClick={() => setIsOpen((v) => !v)}
        aria-expanded={isOpen}
      >
        {isOpen
          ? <ChevronDownIcon className="h-4 w-4 text-pfl-slate-500 shrink-0" aria-hidden="true" />
          : <ChevronRightIcon className="h-4 w-4 text-pfl-slate-500 shrink-0" aria-hidden="true" />
        }
        <span className="flex-1 flex items-baseline gap-2 min-w-0">
          <span className="font-semibold text-sm text-pfl-slate-900 whitespace-nowrap">
            {extractorLabel(extraction.extractor_name)}
          </span>
          {(() => {
            const subject = extractionSubject(extraction)
            const qualifier = extractionQualifier(extraction)
            if (!subject && !qualifier) return null
            return (
              <span className="text-xs text-pfl-slate-500 truncate">
                {subject ? `— ${subject}` : ''}
                {subject && qualifier ? ' · ' : (!subject && qualifier ? '— ' : '')}
                {qualifier ?? ''}
              </span>
            )
          })()}
        </span>
        <div className="flex items-center gap-2">
          {/* Field count chip */}
          {fieldCount > 0 && (
            <span className="text-xs text-pfl-slate-600 font-medium bg-pfl-slate-100 rounded px-1.5 py-0.5">
              {fieldCount} field{fieldCount !== 1 ? 's' : ''} extracted
            </span>
          )}
          {warningCount > 0 && (
            <span className="flex items-center gap-1 text-xs text-amber-700 font-medium bg-amber-50 rounded px-1.5 py-0.5">
              <AlertTriangleIcon className="h-3 w-3" aria-hidden="true" />
              {warningCount} warning{warningCount > 1 ? 's' : ''}
            </span>
          )}
          <Badge variant={variant} className="capitalize text-xs">
            {effective}
          </Badge>
        </div>
      </button>

      {/* Body */}
      {isOpen && (
        <div className="px-4 py-4 bg-white flex flex-col gap-4">
          {/* PARTIAL contextual note */}
          {isPartial && (
            <div className="flex items-start gap-2 rounded bg-amber-50 border border-amber-200 px-3 py-2">
              <AlertTriangleIcon className="h-4 w-4 text-amber-600 mt-0.5 shrink-0" aria-hidden="true" />
              <p className="text-xs text-amber-800">
                {fieldCount > 0
                  ? `Data available — ${fieldCount} field${fieldCount !== 1 ? 's' : ''} extracted. Some fields are missing or could not be read.`
                  : 'No fields could be extracted. See warnings below for details.'}
              </p>
            </div>
          )}

          {/* Key-value data */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold text-pfl-slate-500 uppercase tracking-wide">Data</p>
              <button
                type="button"
                className="text-xs text-pfl-blue-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pfl-blue-600 rounded"
                onClick={() => setShowRaw((v) => !v)}
                aria-expanded={showRaw}
                aria-label={showRaw ? 'Hide raw JSON' : 'View raw JSON'}
              >
                {showRaw ? 'Hide raw JSON' : 'View raw JSON'}
              </button>
            </div>
            {showRaw
              ? (
                <pre className="text-xs bg-pfl-slate-50 rounded p-3 overflow-auto max-h-72 text-pfl-slate-700">
                  {JSON.stringify(extraction.data, null, 2)}
                </pre>
              )
              : <KVTable data={extraction.data} />
            }
          </div>

          {/* Warnings */}
          {warningCount > 0 && (
            <div>
              <p className="text-xs font-semibold text-pfl-slate-500 uppercase tracking-wide mb-2">
                Warnings
              </p>
              <ul className="flex flex-col gap-1">
                {extraction.warnings!.map((w, i) => (
                  <li key={i} className="flex items-center gap-1.5 text-xs text-amber-800 bg-amber-50 rounded px-2 py-1">
                    <AlertTriangleIcon className="h-3 w-3 shrink-0" aria-hidden="true" />
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Error */}
          {extraction.error_message && (
            <div className="rounded bg-red-50 border border-red-200 px-3 py-2">
              <p className="text-xs font-semibold text-red-700 mb-0.5">Error</p>
              <p className="text-xs text-red-600">{extraction.error_message}</p>
            </div>
          )}

          {/* Extracted at */}
          <p className="text-xs text-pfl-slate-400">
            Extracted:{' '}
            {new Date(extraction.extracted_at).toLocaleString(undefined, {
              dateStyle: 'medium',
              timeStyle: 'short',
            })}
          </p>
        </div>
      )}
    </div>
  )
}

export function ExtractionsPanel({ extractions }: ExtractionsPanelProps) {
  if (extractions.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-pfl-slate-500 italic">
        No extraction results yet.
      </p>
    )
  }

  return (
    <div className={cn('flex flex-col gap-3')}>
      {extractions.map((e) => (
        <ExtractionItem key={e.id} extraction={e} />
      ))}
    </div>
  )
}
