'use client'

/**
 * CaseInsightsCard — AI Insights at a glance.
 *
 * Shows key extracted fields from auto_cam + equifax extractions:
 *   applicant, DOB, PAN, CIBIL, FOIR, loan requested, income, expenses,
 *   net surplus, equifax accounts, dedupe matches, artifacts classified.
 *
 * M4: Overview tab addition.
 */

import React from 'react'
import {
  UserIcon,
  CalendarIcon,
  CreditCardIcon,
  BarChart2Icon,
  TrendingDownIcon,
  BanknoteIcon,
  WalletIcon,
  MinusCircleIcon,
  PlusCircleIcon,
  UsersIcon,
  CheckCircleIcon,
  InfoIcon,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { CaseExtractionRead, DedupeMatchRead, CaseArtifactRead } from '@/lib/types'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CaseInsightsCardProps {
  extractions: CaseExtractionRead[]
  dedupeMatches: DedupeMatchRead[]
  artifacts: CaseArtifactRead[]
  caseApplicantName?: string | null
  caseLoanAmount?: number | null
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Pick the "best" auto_cam extraction — prefer the one with the richest data
 * (typically the full 4-sheet CAM over the single-sheet CAM_REPORT variant). */
function pickBestAutoCam(extractions: CaseExtractionRead[]): Record<string, unknown> | null {
  const all = extractions.filter((e) => e.extractor_name === 'auto_cam')
  if (all.length === 0) return null
  // Prefer: multi-sheet (variant !== 'single_sheet_cam'), then by most populated sheets.
  const sorted = [...all].sort((a, b) => {
    const av = (a.data as Record<string, unknown>)?.variant === 'single_sheet_cam' ? 1 : 0
    const bv = (b.data as Record<string, unknown>)?.variant === 'single_sheet_cam' ? 1 : 0
    if (av !== bv) return av - bv
    const aFields = countLeafObj(a.data)
    const bFields = countLeafObj(b.data)
    return bFields - aFields
  })
  return sorted[0].data as Record<string, unknown>
}

function countLeafObj(obj: unknown): number {
  if (obj === null || obj === undefined) return 0
  if (typeof obj !== 'object') return 1
  if (Array.isArray(obj)) return obj.reduce<number>((a, v) => a + countLeafObj(v), 0)
  return Object.values(obj as Record<string, unknown>).reduce<number>((a, v) => a + countLeafObj(v), 0)
}

/** Pick the primary-applicant Equifax extraction: prefer bureau_hit=true,
 * falling back to whichever has the highest (non-negative) credit_score, and
 * finally the first entry. */
function pickPrimaryEquifax(
  extractions: CaseExtractionRead[],
  caseApplicantName?: string | null,
): CaseExtractionRead | null {
  const all = extractions.filter((e) => e.extractor_name === 'equifax')
  if (all.length === 0) return null
  const withHit = all.filter((e) => (e.data as Record<string, unknown>)?.bureau_hit === true)
  const pool = withHit.length > 0 ? withHit : all
  // If caseApplicantName is known, prefer the entry whose customer_info.name matches (case-insensitive).
  if (caseApplicantName) {
    const target = caseApplicantName.trim().toLowerCase()
    const match = pool.find((e) => {
      const name = (
        (e.data as Record<string, unknown>)?.customer_info as Record<string, unknown> | undefined
      )?.name
      return typeof name === 'string' && name.trim().toLowerCase().includes(target)
    })
    if (match) return match
  }
  // Otherwise pick the highest positive score.
  return [...pool].sort((a, b) => {
    const sa = Number((a.data as Record<string, unknown>)?.credit_score) || -Infinity
    const sb = Number((b.data as Record<string, unknown>)?.credit_score) || -Infinity
    return sb - sa
  })[0]
}

/** First non-empty value across a list of candidate paths on the auto_cam payload. */
function firstPresent(autoCam: Record<string, unknown> | null, ...paths: string[][]): unknown {
  for (const path of paths) {
    const v = deepGet(autoCam, ...path)
    if (v !== undefined && v !== null && v !== '') return v
  }
  return undefined
}

/** Safely navigate nested path in a record. */
function deepGet(obj: Record<string, unknown> | null, ...keys: string[]): unknown {
  if (!obj) return undefined
  let cur: unknown = obj
  for (const k of keys) {
    if (cur === null || cur === undefined || typeof cur !== 'object') return undefined
    cur = (cur as Record<string, unknown>)[k]
  }
  return cur
}

function fmt(v: unknown): string | null {
  if (v === null || v === undefined || v === '') return null
  if (typeof v === 'number') return String(v)
  return String(v)
}

function fmtCurrency(v: unknown): string | null {
  if (v === null || v === undefined || v === '') return null
  const n = typeof v === 'number' ? v : Number(v)
  if (isNaN(n)) return String(v)
  return `₹ ${n.toLocaleString('en-IN')}`
}

/** Normalise a raw FOIR value (fraction or percent) to a percent number.
 * Values ≤ 1 are treated as fractions; everything else as percentages already.
 */
function foirToPct(raw: unknown): number | null {
  if (raw === null || raw === undefined || raw === '') return null
  const n = typeof raw === 'number' ? raw : Number(raw)
  if (isNaN(n)) return null
  return n <= 1 ? n * 100 : n
}

function buildFoirInfo(args: {
  autoCam: Record<string, unknown> | null
  foirRaw: unknown
  monthlyIncome: unknown
  proposedEmiNum: number | null
  existingEmiNum: number | null
}): string {
  const { autoCam, foirRaw, monthlyIncome, proposedEmiNum, existingEmiNum } = args
  const camIlFoir = foirToPct(deepGet(autoCam, 'cm_cam_il', 'foir'))
  const healthFoir = foirToPct(deepGet(autoCam, 'health_sheet', 'foir'))
  const eligFoir = foirToPct(deepGet(autoCam, 'eligibility', 'foir'))
  const sysInstFoir = foirToPct(deepGet(autoCam, 'system_cam', 'foir_installment'))
  const sysOverallFoir = foirToPct(deepGet(autoCam, 'system_cam', 'foir_overall'))
  const shown = foirToPct(foirRaw)
  const income = monthlyIncome != null ? Number(monthlyIncome) : null
  const computedPrimary =
    income && income > 0 && proposedEmiNum != null
      ? (proposedEmiNum / income) * 100
      : null
  const computedWithExisting =
    income && income > 0 && proposedEmiNum != null
      ? ((proposedEmiNum + (existingEmiNum || 0)) / income) * 100
      : null

  const fmtPct = (p: number | null) => (p == null ? '—' : `${p.toFixed(1)}%`)
  const lines: string[] = []
  lines.push(
    `FOIR = (EMI being serviced) ÷ Monthly Income.\nPFL's primary FOIR uses only the PROPOSED EMI against Total Income.`,
  )
  lines.push('')
  lines.push(`Displayed: ${fmtPct(shown)} (picked from the first CAM source below).`)
  lines.push('')
  lines.push('Sources in priority order:')
  lines.push(` • Elegibilty sheet .foir      → ${fmtPct(eligFoir)}`)
  lines.push(` • CM CAM IL .foir             → ${fmtPct(camIlFoir)}`)
  lines.push(` • Health Sheet .foir          → ${fmtPct(healthFoir)}`)
  lines.push(` • SystemCam FOIR Installment% → ${fmtPct(sysInstFoir)} (uses business income only)`)
  lines.push(` • SystemCam FOIR Overall%     → ${fmtPct(sysOverallFoir)} (includes existing EMIs)`)
  lines.push('')
  lines.push('Independent sanity check:')
  if (proposedEmiNum != null && income) {
    lines.push(
      ` computed = ${fmtCurrency(proposedEmiNum)} ÷ ${fmtCurrency(income)} = ${fmtPct(computedPrimary)}`,
    )
    if ((existingEmiNum || 0) > 0) {
      lines.push(
        ` with existing EMIs = (${fmtCurrency(proposedEmiNum)} + ${fmtCurrency(existingEmiNum || 0)}) ÷ ${fmtCurrency(income)} = ${fmtPct(computedWithExisting)}`,
      )
    }
  } else {
    lines.push(' computed: need proposed EMI + monthly income')
  }

  // Cross-check — flag any source whose value diverges from the displayed one
  // by more than 0.5 pct-pts (ignoring the SystemCam ratios which legitimately
  // use different denominators).
  const deviations: string[] = []
  const check = (name: string, val: number | null) => {
    if (val == null || shown == null) return
    if (Math.abs(val - shown) > 0.5) {
      deviations.push(`${name}: ${fmtPct(val)}`)
    }
  }
  check('Elegibilty', eligFoir)
  check('CM CAM IL', camIlFoir)
  check('Health Sheet', healthFoir)
  check('computed', computedPrimary)
  if (deviations.length > 0) {
    lines.push('')
    lines.push(`⚠ Source mismatch (>0.5 pct-pt): ${deviations.join(', ')}`)
  }
  return lines.join('\n')
}

// ---------------------------------------------------------------------------
// Badge helpers
// ---------------------------------------------------------------------------

type BadgeColor = 'green' | 'amber' | 'red' | 'neutral'

function CibilBadge({ score }: { score: number }) {
  const color: BadgeColor = score > 750 ? 'green' : score >= 700 ? 'amber' : 'red'
  const cls = {
    green: 'bg-green-100 text-green-800',
    amber: 'bg-amber-100 text-amber-800',
    red: 'bg-red-100 text-red-800',
    neutral: 'bg-pfl-slate-100 text-pfl-slate-700',
  }[color]
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-semibold ${cls}`}>
      {score}
    </span>
  )
}

function FoirBadge({ foirRaw }: { foirRaw: unknown }) {
  const n = typeof foirRaw === 'number' ? foirRaw : Number(foirRaw)
  if (isNaN(n)) return <span className="text-sm text-pfl-slate-800">{String(foirRaw)}</span>
  const pct = n <= 1 ? n * 100 : n
  const color: BadgeColor = pct > 50 ? 'red' : pct > 40 ? 'amber' : 'green'
  const cls = {
    green: 'bg-green-100 text-green-800',
    amber: 'bg-amber-100 text-amber-800',
    red: 'bg-red-100 text-red-800',
    neutral: 'bg-pfl-slate-100 text-pfl-slate-700',
  }[color]
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-semibold ${cls}`}>
      {pct.toFixed(1)}%
    </span>
  )
}

// ---------------------------------------------------------------------------
// Row component
// ---------------------------------------------------------------------------

interface InsightRowProps {
  icon: React.ReactNode
  label: string
  value: React.ReactNode
  note?: string | null
  info?: string
}

function InsightRow({ icon, label, value, note, info }: InsightRowProps) {
  return (
    <div className="flex items-start gap-3 py-2 border-b border-pfl-slate-100 last:border-0">
      <span className="mt-0.5 text-pfl-slate-400 shrink-0">{icon}</span>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-pfl-slate-500 uppercase tracking-wide flex items-center gap-1">
          <span>{label}</span>
          {info && (
            <span
              className="group relative inline-flex cursor-help text-pfl-slate-400 hover:text-pfl-slate-600"
              tabIndex={0}
              aria-label={`How ${label} is computed`}
            >
              <InfoIcon className="h-3.5 w-3.5" />
              <span
                role="tooltip"
                className="pointer-events-none absolute left-5 top-1/2 z-20 -translate-y-1/2 w-72 whitespace-pre-line rounded-md border border-pfl-slate-200 bg-white px-3 py-2 text-[11px] font-normal normal-case tracking-normal text-pfl-slate-700 shadow-lg opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
              >
                {info}
              </span>
            </span>
          )}
        </p>
        <div className="mt-0.5 text-sm text-pfl-slate-900 break-all">{value}</div>
        {note && <p className="mt-0.5 text-xs text-pfl-slate-400 italic">{note}</p>}
      </div>
    </div>
  )
}

function EmptyValue({ reason }: { reason?: string }) {
  return (
    <span className="italic text-pfl-slate-400 text-sm">
      — {reason ? <span className="text-xs">({reason})</span> : null}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CaseInsightsCard({
  extractions,
  dedupeMatches,
  artifacts,
  caseApplicantName,
  caseLoanAmount,
}: CaseInsightsCardProps) {
  const autoCam = pickBestAutoCam(extractions)
  const equifaxExtractions = extractions.filter((e) => e.extractor_name === 'equifax')
  const primaryEquifax = pickPrimaryEquifax(extractions, caseApplicantName)

  // Timestamps — pick the most recent auto_cam extraction
  const autoCamExtracted = extractions.find((e) => e.extractor_name === 'auto_cam')?.extracted_at

  // Applicant name: prefer case record, fall back to auto_cam
  const applicantName =
    fmt(caseApplicantName) ??
    fmt(deepGet(autoCam, 'system_cam', 'applicant_name')) ??
    fmt(deepGet(autoCam, 'cm_cam_il', 'borrower_name'))

  // DOB / PAN come from system_cam of the full CAM, with equifax fallback
  const primaryEquifaxData = primaryEquifax
    ? (primaryEquifax.data as Record<string, unknown>)
    : null

  const dob =
    fmt(deepGet(autoCam, 'system_cam', 'date_of_birth')) ??
    fmt(deepGet(primaryEquifaxData, 'customer_info', 'dob'))

  const pan =
    fmt(deepGet(autoCam, 'system_cam', 'pan')) ??
    fmt(deepGet(autoCam, 'cm_cam_il', 'pan_number')) ??
    fmt(deepGet(primaryEquifaxData, 'customer_info', 'pan'))

  // CIBIL — CAM eligibility sheet > CM CAM IL > primary Equifax.credit_score.
  // For Equifax we use the primary-applicant entry (not the first, which may be
  // a co-applicant NTC report with score -1).
  const cibilFromCam =
    deepGet(autoCam, 'eligibility', 'cibil_score') ??
    deepGet(autoCam, 'cm_cam_il', 'cibil')
  const cibilFromEquifax = primaryEquifax
    ? deepGet(primaryEquifax.data as Record<string, unknown>, 'credit_score')
    : undefined
  const cibilRaw = cibilFromCam ?? cibilFromEquifax
  const cibilNum =
    cibilRaw !== undefined && cibilRaw !== null && cibilRaw !== ''
      ? Number(cibilRaw)
      : null

  // FOIR — try the fixture path, then the real-file paths (cm_cam_il, health_sheet).
  const foirRaw = firstPresent(
    autoCam,
    ['eligibility', 'foir'],
    ['cm_cam_il', 'foir'],
    ['health_sheet', 'foir'],
  )

  // Loan requested
  const loanRequested =
    firstPresent(
      autoCam,
      ['system_cam', 'loan_amount'],
      ['cm_cam_il', 'loan_required'],
      ['eligibility', 'eligible_amount'],
    ) ?? caseLoanAmount

  // Monthly income / expense / net surplus — fixture's Health Sheet path first,
  // then the real-file fallback at cm_cam_il.total_monthly_income.
  const monthlyIncome = firstPresent(
    autoCam,
    ['health_sheet', 'total_monthly_income'],
    ['cm_cam_il', 'total_monthly_income'],
  )

  // Monthly expense — CM CAM IL "Hosehold Expanses" is the credit-relevant
  // expense on real files. Fixtures use the older health_sheet path.
  const EXPENSE_SOURCES: { path: string[]; label: string }[] = [
    { path: ['cm_cam_il', 'household_expense'], label: "CM CAM IL · 'Hosehold Expanses' row" },
    { path: ['cm_cam_il', 'total_monthly_expense'], label: "CM CAM IL · 'Total Monthly Expense'" },
    { path: ['health_sheet', 'total_monthly_expense'], label: "Health Sheet · 'Total Monthly Expense'" },
    { path: ['system_cam', 'total_household_expense'], label: "SystemCam · 'Total Household Expense' (Expense Review)" },
    { path: ['system_cam', 'household_expense'], label: "SystemCam · 'Household Expenses' (Expense Review)" },
  ]
  let monthlyExpense: unknown = undefined
  let monthlyExpenseSource: string | null = null
  for (const src of EXPENSE_SOURCES) {
    const v = deepGet(autoCam, ...src.path)
    if (v !== undefined && v !== null && v !== '') {
      monthlyExpense = v
      monthlyExpenseSource = src.label
      break
    }
  }

  // Net surplus — prefer CAM's own Disposable Income row (income − expense −
  // existing EMIs). If absent, derive it from income + FOIR + expense:
  //   surplus = income × (1 − FOIR) − expense
  // which is "what's left each month after debt-service (FOIR) and living costs".
  const foirNum = (() => {
    const n = typeof foirRaw === 'number' ? foirRaw : Number(foirRaw)
    if (isNaN(n)) return null
    return n <= 1 ? n : n / 100
  })()
  const incomeNum = monthlyIncome != null ? Number(monthlyIncome) : null
  const expenseNum = monthlyExpense != null ? Number(monthlyExpense) : null
  const netSurplusExtracted = firstPresent(
    autoCam,
    ['cm_cam_il', 'disposable_income'],
    ['health_sheet', 'net_surplus'],
  )
  let netSurplus: number | null = null
  let netSurplusSource: 'cam' | 'derived' | null = null
  if (netSurplusExtracted != null && !isNaN(Number(netSurplusExtracted))) {
    netSurplus = Number(netSurplusExtracted)
    netSurplusSource = 'cam'
  } else if (incomeNum != null && expenseNum != null && foirNum != null) {
    netSurplus = Math.round(incomeNum * (1 - foirNum) - expenseNum)
    netSurplusSource = 'derived'
  }

  // Equifax total accounts — take the primary (applicant) entry's summary,
  // not the sum across co-applicant NTC reports (which are always 0).
  const totalEquifaxAccounts = primaryEquifax
    ? Number(
        deepGet(primaryEquifax.data as Record<string, unknown>, 'summary', 'total_accounts') ??
          deepGet(primaryEquifax.data as Record<string, unknown>, 'summary', 'open_accounts') ??
          0,
      )
    : 0

  // Existing obligations — from the bureau. We treat any account whose status
  // isn't explicitly closed/settled as "active". Equifax doesn't always emit a
  // per-account EMI line, so we fall back to CAM's 'EMI Obligation' row (which
  // the CM keys in after reading the bureau) for the existing-EMI total.
  type AcctLike = {
    status?: string
    balance?: number | string | null
    emi_amount?: number | string | null
    installment_amount?: number | string | null
    institution?: string
    product_type?: string
    type?: string
  }
  const primaryAccounts: AcctLike[] = primaryEquifax
    ? (((primaryEquifax.data as Record<string, unknown>)['accounts'] as AcctLike[] | undefined) ?? [])
    : []
  const activeAccounts = primaryAccounts.filter((a) => {
    const s = (a.status || '').toLowerCase()
    return s !== '' && !(s.includes('closed') || s.includes('settled') || s.includes('written off'))
  })
  const activeOutstanding = activeAccounts.reduce(
    (sum, a) => sum + (Number(a.balance) || 0),
    0,
  )
  const activeEmiFromBureau = activeAccounts.reduce(
    (sum, a) => sum + (Number(a.emi_amount) || Number(a.installment_amount) || 0),
    0,
  )
  const existingEmiCam = deepGet(autoCam, 'cm_cam_il', 'emi_obligation')
  const existingEmiNum =
    activeEmiFromBureau > 0
      ? activeEmiFromBureau
      : existingEmiCam != null && !isNaN(Number(existingEmiCam))
      ? Number(existingEmiCam)
      : null
  const existingEmiSource: 'bureau' | 'cam' | null =
    activeEmiFromBureau > 0 ? 'bureau' : existingEmiNum != null ? 'cam' : null

  // Proposed EMI for this loan — from CAM (servable_emi on CM CAM IL, or
  // expected_emi on the single-sheet SystemCam).
  const proposedEmiRaw = firstPresent(
    autoCam,
    ['cm_cam_il', 'servable_emi'],
    ['system_cam', 'expected_emi'],
  )
  const proposedEmiNum =
    proposedEmiRaw != null && !isNaN(Number(proposedEmiRaw)) ? Number(proposedEmiRaw) : null

  const totalEmiLoad =
    existingEmiNum != null || proposedEmiNum != null
      ? (existingEmiNum || 0) + (proposedEmiNum || 0)
      : null

  // Dedupe matches
  const noActiveSnapshot = extractions.some(
    (e) => e.extractor_name === 'dedupe' &&
      Array.isArray(e.warnings) &&
      e.warnings.includes('no_active_snapshot'),
  )

  // Artifacts classified — uses the new CaseArtifactRead.subtype field.
  // UNKNOWN and null both count as unclassified.
  const totalArtifacts = artifacts.length
  const classifiedArtifacts = artifacts.filter(
    (a) => a.subtype && a.subtype !== 'UNKNOWN',
  ).length

  return (
    <Card className="mb-6">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between">
          <CardTitle className="text-base font-semibold text-pfl-slate-900">AI Insights</CardTitle>
          {autoCamExtracted && (
            <p className="text-xs text-pfl-slate-400">
              updated{' '}
              {new Date(autoCamExtracted).toLocaleString(undefined, {
                dateStyle: 'medium',
                timeStyle: 'short',
              })}
            </p>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-0">
          {/* Column 1 */}
          <div>
            <InsightRow
              icon={<UserIcon className="h-4 w-4" />}
              label="Applicant"
              value={applicantName ?? <EmptyValue reason="not extracted" />}
            />
            <InsightRow
              icon={<CalendarIcon className="h-4 w-4" />}
              label="Date of Birth"
              value={dob ?? <EmptyValue reason="not extracted" />}
            />
            <InsightRow
              icon={<CreditCardIcon className="h-4 w-4" />}
              label="PAN"
              value={pan ?? <EmptyValue reason="not extracted" />}
            />
            <InsightRow
              icon={<BarChart2Icon className="h-4 w-4" />}
              label="CIBIL Score"
              value={
                cibilNum !== null && !isNaN(cibilNum)
                  ? <CibilBadge score={cibilNum} />
                  : <EmptyValue reason="not extracted" />
              }
              note={cibilFromCam !== undefined ? 'source: AutoCAM eligibility' : cibilFromEquifax !== undefined ? 'source: Equifax' : undefined}
            />
            <InsightRow
              icon={<TrendingDownIcon className="h-4 w-4" />}
              label="FOIR"
              value={
                foirRaw !== undefined && foirRaw !== null
                  ? <FoirBadge foirRaw={foirRaw} />
                  : <EmptyValue reason="not extracted" />
              }
              info={buildFoirInfo({
                autoCam,
                foirRaw,
                monthlyIncome,
                proposedEmiNum,
                existingEmiNum,
              })}
            />
            <InsightRow
              icon={<BanknoteIcon className="h-4 w-4" />}
              label="Loan Requested"
              value={
                loanRequested !== undefined && loanRequested !== null
                  ? fmtCurrency(loanRequested)
                  : <EmptyValue reason="not extracted" />
              }
            />
          </div>

          {/* Column 2 */}
          <div>
            <InsightRow
              icon={<PlusCircleIcon className="h-4 w-4" />}
              label="Monthly Income"
              value={
                monthlyIncome !== undefined && monthlyIncome !== null
                  ? fmtCurrency(monthlyIncome)
                  : <EmptyValue reason="not extracted" />
              }
            />
            <InsightRow
              icon={<MinusCircleIcon className="h-4 w-4" />}
              label="Monthly Expense"
              value={
                monthlyExpense !== undefined && monthlyExpense !== null
                  ? fmtCurrency(monthlyExpense)
                  : <EmptyValue reason="not extracted" />
              }
              info={
                monthlyExpenseSource
                  ? `Pulled from AutoCAM:\n${monthlyExpenseSource}\n\nOn PFL CAMs this is the household (living) expense the borrower reports during assessment.`
                  : `Expected at AutoCAM → CM CAM IL → 'Hosehold Expanses' row.\nFallback paths: system_cam.total_household_expense, health_sheet.total_monthly_expense.\nThe CAM must have an expense figure populated for the credit health calc to run.`
              }
            />
            <InsightRow
              icon={<WalletIcon className="h-4 w-4" />}
              label="Net Surplus"
              value={
                netSurplus !== null
                  ? fmtCurrency(netSurplus)
                  : <EmptyValue reason="need income + FOIR + expense" />
              }
              note={
                netSurplusSource === 'cam'
                  ? 'source: AutoCAM disposable income'
                  : netSurplusSource === 'derived'
                  ? 'derived: income × (1 − FOIR) − expense'
                  : undefined
              }
              info={
                netSurplusSource === 'cam'
                  ? `Pulled directly from AutoCAM → CM CAM IL → 'Disposable Income' row.\n\nThe CAM computes this as: Total Income − Household Expense − EMI Obligations.`
                  : netSurplusSource === 'derived'
                  ? `Derived because CAM did not ship a Disposable Income row.\n\nFormula: Monthly Income × (1 − FOIR) − Monthly Expense\n= ${incomeNum != null ? `₹${Number(incomeNum).toLocaleString('en-IN')}` : '?'} × (1 − ${foirNum != null ? (foirNum * 100).toFixed(1) + '%' : '?'}) − ${expenseNum != null ? `₹${Number(expenseNum).toLocaleString('en-IN')}` : '?'}\n\nInterprets "what's left each month after debt-service (FOIR) and living costs". Banking will substitute observed monthly inflow once wired.`
                  : `Needs any one of:\n• AutoCAM Disposable Income (CM CAM IL row 48), or\n• Monthly Income + FOIR + Monthly Expense (for the derived formula).\n\nAdd the missing CAM field or let L2 Banking populate an observed inflow.`
              }
            />
            <InsightRow
              icon={<BarChart2Icon className="h-4 w-4" />}
              label="Equifax Accounts"
              value={
                equifaxExtractions.length > 0
                  ? totalEquifaxAccounts > 0
                    ? String(totalEquifaxAccounts)
                    : <EmptyValue reason="no account data" />
                  : <EmptyValue reason="no Equifax extraction" />
              }
            />
            <InsightRow
              icon={<BarChart2Icon className="h-4 w-4" />}
              label="Existing Obligations"
              value={
                activeAccounts.length === 0 && existingEmiNum == null
                  ? <EmptyValue reason="no active loans" />
                  : (
                      <span>
                        {activeAccounts.length} active
                        {existingEmiNum != null && existingEmiNum > 0
                          ? ` · EMI ${fmtCurrency(existingEmiNum)}`
                          : ''}
                        {activeOutstanding > 0 ? ` · O/s ${fmtCurrency(activeOutstanding)}` : ''}
                      </span>
                    )
              }
              info={
                'Active-loan count + existing monthly EMI, drawn from the bureau + CAM.\n\n' +
                'Source of active-loan count: primary Equifax accounts where status ≠ Closed/Settled/Written-off.\n' +
                'Outstanding balance: sum of "balance" across those active accounts.\n' +
                'Monthly EMI: ' + (
                  existingEmiSource === 'bureau'
                    ? 'summed from Equifax per-account EMI.'
                    : existingEmiSource === 'cam'
                    ? "AutoCAM → CM CAM IL → 'EMI Obligation' (CM keys in what the bureau report shows)."
                    : 'not yet reported — bureau accounts carry no EMI line and CAM EMI Obligation is blank.'
                )
              }
            />
            <InsightRow
              icon={<TrendingDownIcon className="h-4 w-4" />}
              label="Total EMI Load (monthly)"
              value={
                totalEmiLoad == null
                  ? <EmptyValue reason="need proposed EMI" />
                  : fmtCurrency(totalEmiLoad)
              }
              note={
                totalEmiLoad != null
                  ? `existing ${fmtCurrency(existingEmiNum || 0)} + proposed ${fmtCurrency(proposedEmiNum || 0)}`
                  : undefined
              }
              info={
                `Total monthly EMI the borrower will be servicing once this loan disburses.\n\n` +
                `Formula: Existing EMIs + Proposed EMI\n` +
                `= ${fmtCurrency(existingEmiNum || 0)} + ${fmtCurrency(proposedEmiNum || 0)}\n` +
                `= ${totalEmiLoad != null ? fmtCurrency(totalEmiLoad) : '—'}\n\n` +
                `Proposed EMI source: AutoCAM → CM CAM IL → 'Servable EMI' (or SystemCam 'Expected EMI' on single-sheet CAMs).\n` +
                `This number feeds the FOIR sanity-check on the left.`
              }
            />
            <InsightRow
              icon={<UsersIcon className="h-4 w-4" />}
              label="Dedupe Matches"
              value={
                noActiveSnapshot
                  ? <EmptyValue reason="no active snapshot" />
                  : String(dedupeMatches.length)
              }
            />
            <InsightRow
              icon={<CheckCircleIcon className="h-4 w-4" />}
              label="Artifacts Classified"
              value={
                totalArtifacts > 0
                  ? `${classifiedArtifacts} of ${totalArtifacts}`
                  : <EmptyValue reason="no artifacts" />
              }
            />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
