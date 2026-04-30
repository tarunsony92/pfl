'use client'

/**
 * CaseCamDiscrepancyCard — in-data conflict check across the AutoCAM sheets.
 *
 * Per PFL policy, SystemCam is the finpage source-of-truth and CM CAM IL is
 * the manually-keyed worksheet. When the two sheets disagree on a critical
 * identity or financial field, the case MUST NOT advance to Phase 1 until
 * the discrepancy is either corrected or the assessor/MD has accepted it
 * with a note.
 *
 * This card reads both auto_cam extractions (single-sheet variant +
 * multi-sheet) and surfaces any field-level disagreement. Clean-all cases
 * render a green "sheets agree" badge.
 */

import React from 'react'
import { ShieldAlertIcon, ShieldCheckIcon } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { CaseExtractionRead } from '@/lib/types'

type Severity = 'critical' | 'warning' | 'info'

export interface CamDiscrepancy {
  field: string
  label: string
  severity: Severity
  notes?: string
  values: { source: string; value: string }[]
}

interface Props {
  extractions: CaseExtractionRead[]
}

function deepGet(obj: Record<string, unknown> | null | undefined, ...keys: string[]): unknown {
  if (!obj) return undefined
  let cur: unknown = obj
  for (const k of keys) {
    if (cur == null || typeof cur !== 'object') return undefined
    cur = (cur as Record<string, unknown>)[k]
  }
  return cur
}

function toStr(v: unknown): string | null {
  if (v === null || v === undefined || v === '') return null
  if (typeof v === 'number') return String(v)
  if (typeof v === 'string') return v.trim()
  return String(v)
}

function normaliseName(s: string): string {
  return s.toUpperCase().replace(/[^A-Z0-9 ]/g, '').replace(/\s+/g, ' ').trim()
}

function normaliseNumber(s: string): number | null {
  const n = Number(s.replace(/,/g, '').replace(/\s/g, ''))
  return isNaN(n) ? null : n
}

function normalisePct(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null
  const n = typeof v === 'number' ? v : Number(String(v).replace(/%/g, ''))
  if (isNaN(n)) return null
  return n <= 1 ? n * 100 : n
}

/** Pick every auto_cam extraction and merge field-by-field. For each logical
 * field we track which (extraction, sheet, key) contributed what — so a later
 * comparison step can say "sheet X says A, sheet Y says B". */
export function detectCamConflicts(
  extractions: CaseExtractionRead[],
): CamDiscrepancy[] {
  const autos = extractions.filter((e) => e.extractor_name === 'auto_cam')
  if (autos.length === 0) return []

  // Bucket by field → [{source_label, value}]
  type Entry = { source: string; value: string }
  const bucket = new Map<string, Entry[]>()
  const push = (field: string, source: string, v: unknown) => {
    const s = toStr(v)
    if (!s) return
    const arr = bucket.get(field) ?? []
    arr.push({ source, value: s })
    bucket.set(field, arr)
  }

  for (const e of autos) {
    const d = e.data as Record<string, unknown> | null
    if (!d) continue
    const variant = (d['variant'] as string | undefined) ?? 'multi_sheet'
    const tag = (sheet: string) => `${variant === 'single_sheet_cam' ? 'CAM_REPORT' : sheet}`

    // Applicant name
    push('applicant_name', tag('SystemCam'), deepGet(d, 'system_cam', 'applicant_name'))
    push('applicant_name', tag('CM CAM IL'), deepGet(d, 'cm_cam_il', 'borrower_name'))
    push('applicant_name', tag('Elegibilty'), deepGet(d, 'eligibility', 'applicant_name'))

    // PAN
    push('pan', tag('SystemCam'), deepGet(d, 'system_cam', 'pan'))
    push('pan', tag('CM CAM IL'), deepGet(d, 'cm_cam_il', 'pan_number'))

    // Loan amount
    push('loan_amount', tag('SystemCam'), deepGet(d, 'system_cam', 'loan_amount'))
    push('loan_amount', tag('CM CAM IL'), deepGet(d, 'cm_cam_il', 'loan_required'))
    push('loan_amount', tag('Elegibilty'), deepGet(d, 'eligibility', 'eligible_amount'))

    // DOB
    push('date_of_birth', tag('SystemCam'), deepGet(d, 'system_cam', 'date_of_birth'))
    push('date_of_birth', tag('CM CAM IL'), deepGet(d, 'cm_cam_il', 'date_of_birth'))

    // CIBIL
    push('cibil', tag('Elegibilty'), deepGet(d, 'eligibility', 'cibil_score'))
    push('cibil', tag('CM CAM IL'), deepGet(d, 'cm_cam_il', 'cibil'))

    // Monthly income
    push('monthly_income', tag('CM CAM IL'), deepGet(d, 'cm_cam_il', 'total_monthly_income'))
    push('monthly_income', tag('Health Sheet'), deepGet(d, 'health_sheet', 'total_monthly_income'))

    // FOIR (use primary ratio only; SystemCam FOIR Installment/Overall are
    // legitimately different denominators, not conflicts)
    push('foir', tag('Elegibilty'), deepGet(d, 'eligibility', 'foir'))
    push('foir', tag('CM CAM IL'), deepGet(d, 'cm_cam_il', 'foir'))
    push('foir', tag('Health Sheet'), deepGet(d, 'health_sheet', 'foir'))
  }

  const labels: Record<string, string> = {
    applicant_name: 'Applicant name',
    pan: 'PAN',
    loan_amount: 'Loan amount',
    date_of_birth: 'Date of birth',
    cibil: 'CIBIL score',
    monthly_income: 'Monthly income',
    foir: 'FOIR',
  }

  // Severity per field — identity mismatches block advancement.
  const severityFor: Record<string, Severity> = {
    applicant_name: 'critical',
    pan: 'critical',
    date_of_birth: 'critical',
    loan_amount: 'critical',
    cibil: 'warning',
    monthly_income: 'warning',
    foir: 'warning',
  }

  const out: CamDiscrepancy[] = []

  for (const [field, entries] of bucket.entries()) {
    // Deduplicate by normalised value.
    const seen = new Map<string, Entry[]>()
    const normaliser = (v: string): string => {
      if (field === 'applicant_name') return normaliseName(v)
      if (field === 'pan') return v.toUpperCase().trim()
      if (field === 'date_of_birth') return v.replace(/[^0-9]/g, '')
      if (field === 'loan_amount' || field === 'monthly_income' || field === 'cibil') {
        const n = normaliseNumber(v)
        return n == null ? v : String(n)
      }
      if (field === 'foir') {
        const p = normalisePct(v)
        return p == null ? v : p.toFixed(1)
      }
      return v.trim().toLowerCase()
    }
    for (const e of entries) {
      const k = normaliser(e.value)
      if (!k) continue
      const arr = seen.get(k) ?? []
      arr.push(e)
      seen.set(k, arr)
    }
    if (seen.size <= 1) continue // all agree (or missing)

    // For FOIR, tolerate a ±0.5 pct-pt drift between sheets.
    if (field === 'foir') {
      const vals = [...seen.keys()].map((k) => Number(k)).filter((n) => !isNaN(n))
      if (vals.length > 1) {
        const spread = Math.max(...vals) - Math.min(...vals)
        if (spread <= 0.5) continue
      }
    }

    // Dedup to first entry per unique value for display
    const displayValues: Entry[] = []
    for (const arr of seen.values()) displayValues.push(arr[0])

    const sev = severityFor[field] ?? 'warning'
    out.push({
      field,
      label: labels[field] ?? field,
      severity: sev,
      values: displayValues,
      notes:
        field === 'applicant_name' || field === 'pan' || field === 'date_of_birth'
          ? 'Identity fields must match across SystemCam and CM CAM IL before Phase 1.'
          : field === 'loan_amount'
          ? 'Loan amount disagreement between SystemCam and the eligibility / IL sheets.'
          : field === 'foir'
          ? 'Primary FOIR differs by more than 0.5 pct-pt across sheets — re-check the EMI / income inputs.'
          : undefined,
    })
  }

  return out
}

export function CaseCamDiscrepancyCard({ extractions }: Props) {
  const discrepancies = detectCamConflicts(extractions)
  const hasAutoCam = extractions.some((e) => e.extractor_name === 'auto_cam')

  if (!hasAutoCam) {
    return null // nothing to check yet
  }

  const critical = discrepancies.filter((d) => d.severity === 'critical')
  const warning = discrepancies.filter((d) => d.severity === 'warning')
  const clean = discrepancies.length === 0

  return (
    <Card className="mb-6">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <CardTitle className="text-base font-semibold text-pfl-slate-900 flex items-center gap-2">
            {clean ? (
              <ShieldCheckIcon className="h-4 w-4 text-emerald-600" />
            ) : (
              <ShieldAlertIcon
                className={
                  critical.length > 0 ? 'h-4 w-4 text-red-600' : 'h-4 w-4 text-amber-600'
                }
              />
            )}
            <span>In-data check — CAM sheets</span>
          </CardTitle>
          <p className="text-xs text-pfl-slate-400">
            {clean
              ? 'All sheets agree.'
              : `${critical.length} critical · ${warning.length} warning`}
          </p>
        </div>
      </CardHeader>
      <CardContent>
        {clean ? (
          <div className="text-[13px] text-pfl-slate-600 leading-relaxed">
            SystemCam, CM CAM IL, Elegibilty and Health Sheet agree on applicant
            name, PAN, DOB, loan amount, CIBIL, monthly income and FOIR. No
            in-data conflicts block Phase 1.
          </div>
        ) : (
          <div className="space-y-2.5">
            {discrepancies.map((d) => (
              <div
                key={d.field}
                className={
                  d.severity === 'critical'
                    ? 'rounded border border-red-200 bg-red-50/50 px-3 py-2'
                    : 'rounded border border-amber-200 bg-amber-50/50 px-3 py-2'
                }
              >
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={
                      d.severity === 'critical'
                        ? 'text-[10px] font-semibold uppercase tracking-wider text-red-700'
                        : 'text-[10px] font-semibold uppercase tracking-wider text-amber-700'
                    }
                  >
                    {d.severity}
                  </span>
                  <span className="text-[12.5px] font-semibold text-pfl-slate-900">
                    {d.label}
                  </span>
                </div>
                <ul className="text-[12px] text-pfl-slate-800 leading-snug space-y-0.5 mt-1 pl-2">
                  {d.values.map((v, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="font-mono text-pfl-slate-500 text-[11px] min-w-[110px]">
                        {v.source}
                      </span>
                      <span className="font-mono">{v.value}</span>
                    </li>
                  ))}
                </ul>
                {d.notes && (
                  <p className="mt-1 text-[11px] text-pfl-slate-600 italic leading-snug">
                    {d.notes}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
