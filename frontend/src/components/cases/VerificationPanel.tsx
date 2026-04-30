'use client'

/**
 * VerificationPanel — "Verification" tab on the case detail page.
 *
 * Clean structural layout:
 *   - Gate banner (pass / fail)
 *   - Summary table (4 rows, Start / Re-run per level)
 *   - One collapsible card per level with:
 *       · header = level name + status pill + counters + chevron
 *       · parameters list = ✓/!/✗ + label + value
 *       · findings = concerns + positives (where applicable)
 *       · issues = severity + description + assessor/MD flow
 */

import React, { useState } from 'react'
import { mutate as globalMutate } from 'swr'
import { cn } from '@/lib/cn'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { cases as casesApi } from '@/lib/api'
import {
  useVerificationOverview,
  useVerificationLevelDetail,
  usePrecedents,
} from '@/lib/useVerification'
import { useDecisionResult } from '@/lib/useDecisioning'
import { useCamDiscrepancies } from '@/lib/useCamDiscrepancies'
import { useAuth } from '@/components/auth/useAuth'
import { DecisioningPanel } from '@/components/cases/DecisioningPanel'
import { L3StockAnalysisCard } from './l3/L3StockAnalysisCard'
import { L3PhotoGallery } from './l3/L3PhotoGallery'
import { PassDetailDispatcher } from './evidence/PassDetailDispatcher'
import {
  EvidenceTwoColumn,
  GenericEvidenceTable,
} from './evidence/EvidenceTwoColumn'
import { lookupCard } from './evidence/registry'
import { BureauWorstCaseStrip } from './evidence/BureauWorstCaseStrip'
import { L3PerItemTable, type L3ItemRow } from './evidence/L3PerItemTable'
import { L5ScoringOverviewStrip } from './evidence/L5ScoringOverviewStrip'
import { L5ScoringRubricTable } from './evidence/L5ScoringRubricTable'
import {
  HIDDEN_EVIDENCE_KEYS,
  extractIssueSourceRefs,
  formatEvidenceValue,
  humanKey,
  type EvidenceVerdict,
} from './evidence/_format'
import type {
  L3StockAnalysis,
  L3VisualEvidence,
  LevelIssueRead,
  VerificationLevelDetail,
  VerificationLevelNumber,
  VerificationLevelStatus,
  VerificationResultRead,
} from '@/lib/types'
import type { CaseStage } from '@/lib/enums'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const LEVELS: VerificationLevelNumber[] = [
  'L1_ADDRESS',
  'L1_5_CREDIT',
  'L2_BANKING',
  'L3_VISION',
  'L4_AGREEMENT',
  'L5_SCORING',
  'L5_5_DEDUPE_TVR',
]

export const LEVEL_META: Record<
  VerificationLevelNumber,
  { title: string; subtitle: string }
> = {
  L1_ADDRESS: {
    title: 'L1 · Address',
    subtitle: 'Identity + address cross-match',
  },
  L1_5_CREDIT: {
    title: 'L1.5 · Credit',
    subtitle: 'Bureau willful-default + fraud scan (applicant + co-applicant)',
  },
  L2_BANKING: {
    title: 'L2 · Banking',
    subtitle: 'CA-grade bank statement analysis',
  },
  L3_VISION: {
    title: 'L3 · Vision',
    subtitle: 'House + business premises condition',
  },
  L4_AGREEMENT: {
    title: 'L4 · Agreement',
    subtitle: 'Loan-agreement enforceability',
  },
  L5_SCORING: {
    title: 'L5 · Scoring',
    subtitle: 'Final 32-point NBFC FINPAGE audit',
  },
  L5_5_DEDUPE_TVR: {
    title: 'L5.5 · Dedupe + TVR + NACH + PDC',
    subtitle: 'Identity dedupe + TVR audio + NACH e-mandate + PDC cheque (vision-verified)',
  },
}

// ---------------------------------------------------------------------------
// Rule catalog — the list of every logic rule each level's engine runs.
// Rendered in the right-hand column of the expanded level card so the assessor
// sees not just the failures (as issues) but ALSO every rule that passed. A
// missing issue for a rule = that rule passed.
// ---------------------------------------------------------------------------

export type RuleCatalogEntry = {
  sub_step_id: string
  title: string
  description: string
  /** Optional: when this returns a reason string, the rule is rendered as N/A
   * for this run and excluded from the match-% denominator. Given the run's
   * sub_step_results (from VerificationResult.sub_step_results). */
  skipIf?: (sub: Record<string, unknown>) => string | null
}

export const RULE_CATALOG: Record<VerificationLevelNumber, RuleCatalogEntry[]> = {
  L1_ADDRESS: [
    {
      sub_step_id: 'applicant_coapp_address_match',
      title: 'Applicant ↔ Co-applicant address',
      description: 'Aadhaar addresses of both primary parties reconcile.',
    },
    {
      sub_step_id: 'gps_vs_aadhaar',
      title: 'House-visit GPS ↔ Aadhaar',
      description:
        'Photo coordinates resolve to the same district/village as the Aadhaar address.',
    },
    {
      sub_step_id: 'ration_owner_rule',
      title: 'Bill owner is a loan party',
      description:
        'Ration/electricity bill is in the borrower, co-applicant, or declared-guardian name.',
    },
    {
      sub_step_id: 'business_visit_gps',
      title: 'Business-visit photo GPS',
      description:
        'At least one BUSINESS_PREMISES_PHOTO yielded usable GPS coordinates (EXIF or watermark OCR).',
      // Only relevant when biz photos exist — if no photos were uploaded
      // the checklist validator blocks the case upstream.
      skipIf: (sub) =>
        (sub['business_photo_count'] as number | undefined) === 0
          ? 'no business-visit photos uploaded on this case'
          : null,
    },
    {
      sub_step_id: 'house_business_commute',
      title: 'House ↔ Business commute',
      description:
        'Driving distance + travel time between residence and business are within the credit-policy / Opus-judge tolerance.',
      skipIf: (sub) => {
        const st = sub['commute_sub_step_status'] as string | undefined
        if (st === 'skipped_missing_house_gps')
          return 'house GPS unavailable — commute cannot be computed'
        if (st === 'skipped_missing_business_gps')
          return 'business GPS unavailable — commute cannot be computed'
        return null
      },
    },
    {
      sub_step_id: 'aadhaar_vs_bureau_address',
      title: 'Aadhaar ↔ Equifax bureau',
      description: 'Aadhaar address is corroborated by at least one bureau record.',
    },
    {
      sub_step_id: 'aadhaar_vs_bank_address',
      title: 'Aadhaar ↔ Bank-statement',
      description: 'Aadhaar address appears on the bank statement header.',
    },
  ],
  L1_5_CREDIT: [
    {
      sub_step_id: 'bureau_report_missing',
      title: 'Bureau report present',
      description:
        'An Equifax / bureau extraction is on file for the applicant.',
    },
    {
      sub_step_id: 'credit_write_off',
      title: 'No write-offs',
      description: 'No WO / Write-Off accounts on applicant\u2019s bureau (strong willful-default flag).',
    },
    {
      sub_step_id: 'credit_loss',
      title: 'No loss accounts',
      description: 'No LSS / Loss accounts (lender has marked amount uncollectible).',
    },
    {
      sub_step_id: 'credit_settled',
      title: 'No compromised settlements',
      description: 'No SETTLED / Compromised accounts (closed with partial payment is a negative signal).',
    },
    {
      sub_step_id: 'credit_substandard',
      title: 'No substandard accounts',
      description: 'No SUB accounts \u2014 no 90+ days overdue account moving toward NPA.',
    },
    {
      sub_step_id: 'credit_doubtful',
      title: 'No doubtful accounts',
      description: 'No DBT \u2014 recovery-uncertain accounts on the applicant\u2019s bureau.',
    },
    {
      sub_step_id: 'credit_sma',
      title: 'No SMA overdue',
      description: 'No Special-Mention-Account (SMA-0/1/2) early-warning overdue accounts.',
    },
    {
      sub_step_id: 'credit_score_floor',
      title: 'Credit score above floor',
      description: 'Applicant credit score \u2265 PFL comfort band (\u2265 700 pass, <700 warn, <680 critical).',
    },
    {
      sub_step_id: 'opus_credit_verdict',
      title: 'Opus credit verdict',
      description: 'Seasoned-analyst review (applicant + co-applicant) returns ``clean`` or better.',
    },
    // Co-applicant mirrors — same hard rules re-run against the co-app bureau.
    // Every entry uses the same ``skipIf`` check on sub_step_results.co_applicant:
    // when the co-applicant has no bureau row on file (common — credit-
    // invisible co-app), the rule is N/A, not a pass. Prevents the UI from
    // claiming false positives on every credit-invisible co-applicant.
    ...([
      ['coapp_credit_write_off', 'Co-app: no write-offs', 'No WO / Write-Off on co-applicant\u2019s bureau.'],
      ['coapp_credit_loss', 'Co-app: no loss accounts', 'No LSS / Loss accounts on co-applicant\u2019s bureau.'],
      ['coapp_credit_settled', 'Co-app: no compromised settlements', 'No SETTLED / Compromised accounts on co-applicant\u2019s bureau.'],
      ['coapp_credit_substandard', 'Co-app: no substandard accounts', 'No SUB accounts on co-applicant\u2019s bureau.'],
      ['coapp_credit_doubtful', 'Co-app: no doubtful accounts', 'No DBT accounts on co-applicant\u2019s bureau.'],
      ['coapp_credit_sma', 'Co-app: no SMA overdue', 'No SMA-0/1/2 overdue accounts on co-applicant\u2019s bureau.'],
      ['coapp_credit_score_floor', 'Co-app: credit score above floor', 'Co-applicant credit score \u2265 PFL comfort band (\u2265 700 pass, <700 warn, <680 critical).'],
    ] as const).map(([sub_step_id, title, description]) => ({
      sub_step_id,
      title,
      description,
      skipIf: (sub: Record<string, unknown>) => {
        const co = (sub['co_applicant'] as Record<string, unknown> | undefined) ?? {}
        if (Object.keys(co).length === 0) {
          return 'no co-applicant bureau on file'
        }
        return null
      },
    })),
  ],
  L2_BANKING: [
    {
      sub_step_id: 'bank_statement_missing',
      title: 'Bank statement present',
      description:
        'A bank statement extraction is on file and yielded transaction lines.',
    },
    {
      sub_step_id: 'bank_statement_months_coverage',
      title: 'Bank statement covers ≥ 6 months',
      description:
        'Cumulative date span of extracted transactions is at least 6 months.',
    },
    { sub_step_id: 'nach_bounces', title: 'NACH / ECS bounces', description: 'No bounces in the last 3-6 months.' },
    { sub_step_id: 'avg_balance_vs_emi', title: 'Average balance vs EMI', description: 'Average monthly balance ≥ 1.5× proposed EMI and ≥ ₹1,000.' },
    { sub_step_id: 'credits_vs_declared_income', title: 'Credits vs declared income', description: 'Total credit inflow tracks the declared monthly income.' },
    { sub_step_id: 'single_payer_concentration', title: 'Payer concentration', description: 'Credits come from multiple distinct payers, not a single source.' },
    { sub_step_id: 'impulsive_debit_overspend', title: 'Impulsive-debit ratio', description: 'Discretionary debits stay within a healthy share of income.' },
    { sub_step_id: 'chronic_low_balance', title: 'Chronic low balance', description: 'Account does not habitually run at zero / overdrawn.' },
    { sub_step_id: 'ca_narrative_concerns', title: 'CA narrative review', description: "Claude's CA-grade narrative flags no additional risks." },
  ],
  L3_VISION: [
    { sub_step_id: 'house_living_condition', title: 'House living condition', description: "Claude Opus rates the house photos good or fair." },
    { sub_step_id: 'business_infrastructure', title: 'Business infrastructure', description: 'Business-premises photos show a real, active operation.' },
    {
      sub_step_id: 'stock_vs_loan',
      title: 'Stock / collateral vs loan',
      description:
        'Visible stock — or fixed equipment for a service business — covers enough of the loan amount.',
    },
    {
      sub_step_id: 'cattle_health',
      title: 'Cattle health',
      description: 'Livestock appear healthy and well-kept.',
      skipIf: (sub) => {
        const biz = (sub['business'] as Record<string, unknown> | undefined) ?? {}
        const t = (biz['business_type'] as string | undefined) ?? ''
        if (!t) return null
        return t === 'cattle_dairy' || t === 'mixed'
          ? null
          : `not a dairy business (classified: ${t})`
      },
    },
    {
      sub_step_id: 'loan_amount_reduction',
      title: 'Loan amount recommendation',
      description:
        'Vision model\'s collateral-based loan recommendation is within 20% of the proposed ticket.',
    },
    {
      sub_step_id: 'stock_aggregate_drift',
      title: 'Per-item totals vs aggregate',
      description:
        'Sum of itemised line totals stays within 20% of the scorer\'s aggregate stock / equipment values.',
    },
  ],
  L4_AGREEMENT: [
    {
      sub_step_id: 'loan_agreement_missing',
      title: 'Loan agreement uploaded',
      description:
        'A signed loan-agreement PDF (LAGR / LOAN_AGREEMENT / LAPP / DPN) is attached to the case.',
    },
    { sub_step_id: 'loan_agreement_annexure', title: 'Agreement annexure present', description: 'The signed loan agreement includes an asset annexure.' },
    { sub_step_id: 'asset_annexure_empty', title: 'Annexure lists assets', description: 'Annexure enumerates at least one financed asset.' },
    { sub_step_id: 'hypothecation_clause', title: 'Hypothecation clause', description: 'Standard hypothecation language is present in the agreement.' },
  ],
  L5_SCORING: [
    {
      sub_step_id: 'scoring_section_a',
      title: 'Section A \u2014 Credit Assessment & Eligibility (45 pts)',
      description: '13 items: income, CIBIL, DPD, write-offs, FOIR, DSCR, deviation sign-off.',
    },
    {
      sub_step_id: 'scoring_section_b',
      title: 'Section B \u2014 QR & Banking Check (35 pts)',
      description: '11 items: QR scan, income proofs, banking span, ABB ratio, bounces.',
    },
    {
      sub_step_id: 'scoring_section_c',
      title: 'Section C \u2014 Assets & Living Standard (13 pts)',
      description: '5 items: loan purpose, ownership proofs, additional assets visible.',
    },
    {
      sub_step_id: 'scoring_section_d',
      title: 'Section D \u2014 Reference Checks & TVR (7 pts)',
      description: '3 items: BCM cross-verification, TVR, independent fraud call from HO.',
    },
    {
      sub_step_id: 'scoring_grade',
      title: 'Audit grade A+ / A / B',
      description: 'Overall ≥ 70% (grade B or better) for the case to clear the 32-point audit.',
    },
  ],
  L5_5_DEDUPE_TVR: [
    {
      sub_step_id: 'dedupe_clear',
      title: 'Customer dedupe report',
      description:
        'Finpage Customer_Dedupe export is uploaded and shows no row colliding ' +
        'with the applicant identity (Aadhaar / PAN / mobile / DOB+name).',
    },
    {
      sub_step_id: 'tvr_present',
      title: 'Tele-Verification Report (TVR) audio',
      description:
        'A TVR audio recording (mp3 / wav / m4a) is attached so the assessor ' +
        'call with the applicant can be reviewed.',
    },
    {
      sub_step_id: 'nach_present',
      title: 'NACH e-mandate (Nupay registration)',
      description:
        'Signed NACH / Nupay e-mandate is attached so EMI auto-debit is set up ' +
        'before disbursal — UMRN, customer account, frequency MNTH and RCUR ' +
        'sequence type should be visible on the form.',
    },
    {
      sub_step_id: 'pdc_present',
      title: 'PDC (post-dated cheque) — Claude vision verified',
      description:
        'Borrower’s post-dated cheque image is attached as the back-up ' +
        'EMI-recovery instrument alongside the NACH e-mandate. A single Claude ' +
        'Sonnet vision call confirms the image actually depicts a bank cheque ' +
        '(reads bank, IFSC, account number, account-holder name, signature). ' +
        'Missing or vision-rejected → CRITICAL; MD can waive with a written ' +
        'justification.',
    },
    {
      sub_step_id: 'pdc_matches_bank',
      title: 'PDC ↔ bank statement match',
      description:
        'IFSC + account-tail (last 4 digits) on the cheque cross-checked ' +
        'against the bank statement extraction. Hard mismatch → CRITICAL ' +
        '(cheque from a different account than EMI debits will hit, useless ' +
        'as a recovery instrument). Account-holder name fuzz < 70% → ' +
        'WARNING. Skipped silently when either side is missing the field.',
    },
  ],
}

type Verdict = 'pass' | 'warn' | 'fail' | 'info'

// ---------------------------------------------------------------------------
// Primitives
// ---------------------------------------------------------------------------

function Tick({ verdict }: { verdict: Verdict }) {
  const glyph = { pass: '✓', warn: '!', fail: '✗', info: '·' }[verdict]
  const color = {
    pass: 'text-emerald-600',
    warn: 'text-amber-600',
    fail: 'text-red-600',
    info: 'text-pfl-slate-400',
  }[verdict]
  return (
    <span
      className={cn(
        'inline-block w-4 text-center font-bold text-[14px] leading-none shrink-0',
        color,
      )}
      aria-label={verdict}
    >
      {glyph}
    </span>
  )
}

function StatusPill({
  label,
  tone,
}: {
  label: string
  tone: 'pass' | 'fail' | 'warn' | 'info'
}) {
  const palette = {
    pass: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    fail: 'bg-red-50 text-red-700 border-red-200',
    warn: 'bg-amber-50 text-amber-800 border-amber-200',
    info: 'bg-pfl-slate-100 text-pfl-slate-600 border-pfl-slate-200',
  }[tone]
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide',
        palette,
      )}
    >
      {label}
    </span>
  )
}

function SeverityPill({
  severity,
  status,
}: {
  severity: LevelIssueRead['severity']
  status?: LevelIssueRead['status']
}) {
  // Once an MD has approved the override, the concern is no longer blocking;
  // collapse the visual to dark green regardless of original severity so the
  // viewer sees at a glance the concern has been resolved.
  if (status === 'MD_APPROVED') {
    return (
      <span
        className={cn(
          'inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider',
          'bg-emerald-100 text-emerald-800 border-emerald-300',
        )}
      >
        {severity}
      </span>
    )
  }
  const c: Record<LevelIssueRead['severity'], string> = {
    INFO: 'bg-sky-50 text-sky-700 border-sky-200',
    WARNING: 'bg-amber-50 text-amber-800 border-amber-200',
    CRITICAL: 'bg-red-50 text-red-700 border-red-200',
  }
  return (
    <span
      className={cn(
        'inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider',
        c[severity],
      )}
    >
      {severity}
    </span>
  )
}

function IssueStatusPill({ status }: { status: LevelIssueRead['status'] }) {
  const c: Record<LevelIssueRead['status'], string> = {
    OPEN: 'bg-pfl-slate-100 text-pfl-slate-700',
    ASSESSOR_RESOLVED: 'bg-amber-50 text-amber-800 border border-amber-200',
    MD_APPROVED: 'bg-emerald-50 text-emerald-700',
    MD_REJECTED: 'bg-red-50 text-red-700',
  }
  // Spell out what each state actually means. "ASSESSOR_RESOLVED" used to
  // literally render as "ASSESSOR RESOLVED", which wrongly implied the
  // issue was done — in reality the MD still has to approve or reject
  // before the gate clears. Label now makes the handoff explicit.
  const label: Record<LevelIssueRead['status'], string> = {
    OPEN: 'Open',
    ASSESSOR_RESOLVED: 'Justified · awaiting MD',
    MD_APPROVED: 'MD approved',
    MD_REJECTED: 'MD rejected',
  }
  const tooltip: Record<LevelIssueRead['status'], string> = {
    OPEN: 'No one has touched this issue yet — the assessor needs to write a justification or escalate.',
    ASSESSOR_RESOLVED:
      'Assessor submitted a justification. The gate stays blocked until the MD approves or rejects.',
    MD_APPROVED: 'MD approved — the block has been overridden for this case.',
    MD_REJECTED: 'MD rejected — the block is upheld; the case cannot progress.',
  }
  return (
    <span
      title={tooltip[status]}
      className={cn(
        'rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider whitespace-nowrap',
        c[status],
      )}
    >
      {label[status]}
    </span>
  )
}

// Helpers that used to live here have moved to evidence/_format.ts so
// the fire-path panel + the pass-path dispatcher consume one source of
// truth. SourceArtifactCard moved to evidence/SourceArtifactCard.tsx;
// the source-file viewer is now the right column of EvidenceTwoColumn.

// ---------------------------------------------------------------------------
// L5 scoring smart cards — section / grade summaries have structured
// ``failing_rows`` / ``weakest_sections`` / ``top_misses`` on evidence;
// render them as real tables + a score bar instead of dumping the LLM-
// joined description prose. Per-row issues (scoring_NN) render the
// underlying ScoreRow as a compact fact card.
// ---------------------------------------------------------------------------

function _scoringPalette(pct: number): { bar: string; text: string; bg: string } {
  if (pct >= 70)
    return {
      bar: 'bg-emerald-500',
      text: 'text-emerald-700',
      bg: 'bg-emerald-50/50',
    }
  if (pct >= 50)
    return { bar: 'bg-amber-500', text: 'text-amber-700', bg: 'bg-amber-50/50' }
  return { bar: 'bg-red-500', text: 'text-red-700', bg: 'bg-red-50/50' }
}

function ScoreBar({
  earned,
  max,
  pct,
}: {
  earned: number | null
  max: number | null
  pct: number | null
}) {
  const safePct = typeof pct === 'number' ? Math.max(0, Math.min(100, pct)) : 0
  const p = _scoringPalette(safePct)
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-[11px]">
        <span className="font-mono tabular-nums text-pfl-slate-700">
          <span className="text-[13px] font-bold text-pfl-slate-900">
            {earned ?? '—'}
          </span>{' '}
          <span className="text-pfl-slate-400">/</span> {max ?? '—'}
        </span>
        <span className={cn('font-semibold', p.text)}>
          {typeof pct === 'number' ? `${pct.toFixed(1)}%` : '—'}
        </span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-pfl-slate-200 overflow-hidden">
        <div
          className={cn('h-full rounded-full', p.bar)}
          style={{ width: `${safePct}%` }}
        />
      </div>
    </div>
  )
}

function ScoringRowTable({
  rows,
  caption,
}: {
  rows: Array<Record<string, unknown>>
  caption: string
}) {
  if (rows.length === 0) return null
  return (
    <div>
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1.5">
        {caption}
      </div>
      <div className="flex flex-col gap-1.5">
        {rows.map((r, i) => {
          const sno = r['sno'] as number | undefined
          const parameter = (r['parameter'] as string | undefined) ?? '—'
          const status = ((r['status'] as string | undefined) ?? '').toLowerCase()
          const weight = r['weight'] as number | undefined
          const evidenceText = (r['evidence'] as string | undefined) ?? ''
          const remarks = (r['remarks'] as string | undefined) ?? ''
          const statusLabel =
            status === 'fail'
              ? 'FAILING'
              : status === 'pending'
              ? 'PENDING'
              : status.toUpperCase()
          const statusCls =
            status === 'fail'
              ? 'bg-red-100 text-red-700 border-red-200'
              : status === 'pending'
              ? 'bg-amber-100 text-amber-800 border-amber-200'
              : 'bg-pfl-slate-100 text-pfl-slate-700 border-pfl-slate-200'
          return (
            <div
              key={i}
              className="rounded border border-pfl-slate-200 bg-white p-2 text-[12.5px]"
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-[11px] text-pfl-slate-500">
                  #{typeof sno === 'number' ? String(sno).padStart(2, '0') : '??'}
                </span>
                <span className="font-semibold text-pfl-slate-900">
                  {parameter}
                </span>
                <span
                  className={cn(
                    'rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider',
                    statusCls,
                  )}
                >
                  {statusLabel}
                </span>
                {typeof weight === 'number' && (
                  <span className="text-[10.5px] text-pfl-slate-500">
                    weight {weight}
                  </span>
                )}
              </div>
              {(evidenceText || remarks) && (
                <div className="mt-1 text-[12px] text-pfl-slate-700 leading-snug">
                  {evidenceText} {remarks}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ScoringSummaryCard({
  ev,
  isGrade,
}: {
  ev: Record<string, unknown>
  isGrade: boolean
}) {
  const earned = ev['earned'] as number | null | undefined
  const max = ev['max_score'] as number | null | undefined
  const pct = ev['pct'] as number | null | undefined
  const failingRows = (ev['failing_rows'] as Array<Record<string, unknown>> | undefined) ?? []
  const weakest =
    (ev['weakest_sections'] as Array<Record<string, unknown>> | undefined) ?? []
  const topMisses =
    (ev['top_misses'] as Array<Record<string, unknown>> | undefined) ?? []
  const sectionTitle = ev['section_title'] as string | undefined
  const grade = ev['grade'] as string | undefined
  return (
    <div className="flex flex-col gap-3">
      {/* Hero score */}
      <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-3 flex flex-col gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500">
            {isGrade ? 'Overall audit' : 'Section score'}
          </span>
          {sectionTitle && (
            <span className="text-[11.5px] font-semibold text-pfl-slate-800">
              {sectionTitle}
            </span>
          )}
          {grade && (
            <span className="ml-auto rounded bg-white border border-pfl-slate-200 px-2 py-0.5 text-[11px] font-bold font-mono">
              grade {grade}
            </span>
          )}
        </div>
        <ScoreBar
          earned={typeof earned === 'number' ? earned : null}
          max={typeof max === 'number' ? max : null}
          pct={typeof pct === 'number' ? pct : null}
        />
      </div>

      {/* Weakest sections (grade issue only) */}
      {isGrade && weakest.length > 0 && (
        <div>
          <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1.5">
            Weakest sections
          </div>
          <div className="flex flex-col gap-1">
            {weakest.map((s, i) => {
              const sid = (s['section_id'] as string | undefined) ?? '?'
              const title = (s['title'] as string | undefined) ?? '—'
              const se = s['earned'] as number | undefined
              const sm = s['max_score'] as number | undefined
              const sp = s['pct'] as number | undefined
              const pal = _scoringPalette(sp ?? 0)
              return (
                <div
                  key={i}
                  className={cn(
                    'rounded border px-2 py-1.5 text-[12px] flex items-center gap-2',
                    pal.bg,
                    'border-pfl-slate-200',
                  )}
                >
                  <span className="font-semibold text-pfl-slate-900">
                    Section {sid}
                  </span>
                  <span className="text-pfl-slate-600">·</span>
                  <span className="text-pfl-slate-700">{title}</span>
                  <span className="ml-auto font-mono tabular-nums text-[11.5px]">
                    {se ?? '—'} / {sm ?? '—'}{' '}
                    <span className={cn('font-semibold', pal.text)}>
                      ({typeof sp === 'number' ? sp.toFixed(1) : '—'}%)
                    </span>
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Failing / pending rows */}
      <ScoringRowTable
        rows={isGrade ? topMisses : failingRows}
        caption={isGrade ? 'Top misses' : 'Causing the drop'}
      />
    </div>
  )
}

function ScoringRowCard({
  row,
}: {
  row: Record<string, unknown> | undefined
}) {
  if (!row) return null
  const sno = row['sno'] as number | undefined
  const parameter = (row['parameter'] as string | undefined) ?? '—'
  const section = (row['section'] as string | undefined) ?? null
  const weight = row['weight'] as number | undefined
  const expected = (row['expected'] as string | undefined) ?? null
  const evidenceText = (row['evidence'] as string | undefined) ?? ''
  const remarks = (row['remarks'] as string | undefined) ?? ''
  const status = ((row['status'] as string | undefined) ?? '').toLowerCase()
  const score = row['score'] as number | undefined
  const statusCls =
    status === 'fail'
      ? 'bg-red-100 text-red-700 border-red-200'
      : status === 'pending'
      ? 'bg-amber-100 text-amber-800 border-amber-200'
      : 'bg-pfl-slate-100 text-pfl-slate-700 border-pfl-slate-200'
  return (
    <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-3 flex flex-col gap-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono text-[11px] text-pfl-slate-500">
          #{typeof sno === 'number' ? String(sno).padStart(2, '0') : '??'}
        </span>
        <span className="font-semibold text-pfl-slate-900">{parameter}</span>
        <span
          className={cn(
            'rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider',
            statusCls,
          )}
        >
          {status.toUpperCase() || 'UNKNOWN'}
        </span>
        {typeof weight === 'number' && (
          <span className="text-[10.5px] text-pfl-slate-500">weight {weight}</span>
        )}
        {typeof score === 'number' && (
          <span className="ml-auto font-mono text-[11px] text-pfl-slate-600">
            scored {score}
          </span>
        )}
      </div>
      <div className="grid grid-cols-[max-content,1fr] gap-x-3 gap-y-1 text-[12px]">
        {section && (
          <>
            <span className="font-medium text-pfl-slate-600">Section</span>
            <span className="text-pfl-slate-800">{section}</span>
          </>
        )}
        {expected && (
          <>
            <span className="font-medium text-pfl-slate-600">Expected</span>
            <span className="text-pfl-slate-800">{expected}</span>
          </>
        )}
        {evidenceText && (
          <>
            <span className="font-medium text-pfl-slate-600">Evidence</span>
            <span className="text-pfl-slate-800 whitespace-pre-wrap">
              {evidenceText}
            </span>
          </>
        )}
        {remarks && (
          <>
            <span className="font-medium text-pfl-slate-600">Remarks</span>
            <span className="text-pfl-slate-800 whitespace-pre-wrap">
              {remarks}
            </span>
          </>
        )}
      </div>
    </div>
  )
}

/**
 * IssueEvidencePanel — fire-path concern body. Routes through the
 * smart-card registry so a 30-year underwriter sees the same grammar
 * (claim left, source right) as the pass-path dispatcher. L5 scoring
 * issues short-circuit to their bespoke layout until PR3 owns the L5
 * revamp.
 */
function IssueEvidencePanel({
  issue,
  caseId,
}: {
  issue: LevelIssueRead
  caseId: string
}) {
  const ev = (issue.evidence ?? {}) as Record<string, unknown>
  const sources = extractIssueSourceRefs(issue)
  const keys = Object.keys(ev).filter((k) => !HIDDEN_EVIDENCE_KEYS.has(k))
  if (keys.length === 0 && !issue.artifact_id && sources.length === 0) return null

  const verdict: EvidenceVerdict =
    issue.severity === 'CRITICAL' ? 'fail' : 'warn'

  // Issue description renders inside the LEFT column as a "Description
  // of issue" subsection — IssueRow no longer renders it as a separate
  // paragraph above the panel (kills the duplication and uses the
  // spare LEFT-column space the new inline source viewer freed up).
  const description = issue.description?.trim() || undefined

  // L5 scoring panel — uses the bespoke ScoringSummary / ScoringRow
  // cards as the LEFT-column body but goes through EvidenceTwoColumn
  // so it gets the same WHAT WAS CHECKED + verdict pill + sources +
  // description shell as every other level. No more visual outlier.
  const isScoringSection = /^scoring_section_/.test(issue.sub_step_id)
  const isScoringGrade = issue.sub_step_id === 'scoring_grade'
  const isScoringRow = /^scoring_\d{2}(_pending)?$/.test(issue.sub_step_id)
  if (isScoringSection || isScoringGrade || isScoringRow) {
    return (
      <EvidenceTwoColumn
        caseId={caseId}
        left={
          <div className="flex flex-col gap-3">
            {(isScoringSection || isScoringGrade) && (
              <ScoringSummaryCard ev={ev} isGrade={isScoringGrade} />
            )}
            {isScoringRow && (
              <ScoringRowCard
                row={ev['row'] as Record<string, unknown> | undefined}
              />
            )}
          </div>
        }
        sources={sources}
        verdict={verdict}
        description={description}
      />
    )
  }

  // Smart-card path — registry decides per-rule rendering, identical
  // to the pass path so a rule's body is the same whether it fired or
  // passed.
  const card = lookupCard(issue.sub_step_id, ev)
  if (card) {
    return (
      <EvidenceTwoColumn
        caseId={caseId}
        left={card.body}
        sources={sources}
        verdict={verdict}
        headline={card.headline}
        description={description}
      />
    )
  }

  // Generic fallback — the matchedPair / isOwnerRule / hasGpsMatch
  // smart layouts are kept here as the LEFT-column body until each of
  // those rules gets a dedicated card in the registry.
  return (
    <EvidenceTwoColumn
      caseId={caseId}
      left={<GenericFireBody evidence={ev} keys={keys} />}
      sources={sources}
      verdict={verdict}
      description={description}
    />
  )
}

/** Generic fire-path body — the legacy matchedPair / isOwnerRule /
 *  hasGpsMatch smart layouts plus a key/value tail for the rest.
 *  Migrated rule-by-rule into dedicated registry cards over PR2/PR3. */
function GenericFireBody({
  evidence: ev,
  keys,
}: {
  evidence: Record<string, unknown>
  keys: string[]
}) {
  const addressPairs: Array<[string, string]> = [
    ['applicant_address', 'co_applicant_address'],
    ['applicant_aadhaar_address', 'gps_derived_address'],
    ['aadhaar_address', 'gps_derived_address'],
  ]
  const matchedPair = addressPairs.find(
    ([a, b]) => typeof ev[a] === 'string' && typeof ev[b] === 'string',
  )

  const isOwnerRule =
    typeof ev['bill_owner'] === 'string' &&
    typeof ev['applicant_name'] === 'string'

  const gpsMatch = ev['gps_match'] as
    | { verdict?: string; score?: number; reason?: string }
    | undefined
  const hasGpsMatch =
    !!gpsMatch && typeof gpsMatch === 'object' && 'verdict' in gpsMatch

  const covered = new Set<string>()
  if (matchedPair) matchedPair.forEach((k) => covered.add(k))
  if (isOwnerRule) {
    for (const k of [
      'bill_owner',
      'bill_father_or_husband',
      'applicant_name',
      'applicant_aadhaar_father',
      'co_applicant_name',
      'guarantor_names',
      'applicant_relation_to_owner',
      'co_applicant_aadhaar_father',
      'co_applicant_relation_to_owner',
    ]) {
      covered.add(k)
    }
  }
  if (hasGpsMatch) covered.add('gps_match')

  // Distance pill — surfaced above the address-pair grid so the assessor /
  // MD can tell "200 m apart, photo-angle issue" from "50 km apart, real
  // mismatch" without leaving the panel. Computed by the L1 engine via
  // google_maps.forward_geocode + haversine; absent silently when geocoding
  // failed (api key missing, ZERO_RESULTS, etc).
  const distanceKmRaw = ev['distance_km']
  const distanceKm =
    typeof distanceKmRaw === 'number' && Number.isFinite(distanceKmRaw)
      ? distanceKmRaw
      : null
  if (distanceKm !== null) covered.add('distance_km')
  // Buckets tuned for rural India microfinance: <1 km is photo-angle /
  // joint-family compound (green), 1-10 km is "same town different lane"
  // (amber), > 10 km is hard mismatch (red).
  const distanceTone =
    distanceKm === null
      ? 'slate'
      : distanceKm < 1
      ? 'green'
      : distanceKm < 10
      ? 'amber'
      : 'red'
  const distanceLabel =
    distanceKm === null
      ? null
      : distanceKm < 1
      ? `${Math.round(distanceKm * 1000)} m apart`
      : `${distanceKm.toFixed(2)} km apart`
  const distanceHint =
    distanceKm === null
      ? null
      : distanceKm < 1
      ? 'within walking distance — likely a photo-angle / joint-family case'
      : distanceKm < 10
      ? 'same town / district — possible photo from a relative’s house'
      : 'addresses are in different localities — substantive mismatch'

  const rest = keys.filter((k) => !covered.has(k))

  return (
    <div className="flex flex-col gap-3">
      {distanceKm !== null && (
        <div
          className={cn(
            'rounded border px-3 py-2 flex items-center gap-3 flex-wrap',
            distanceTone === 'green' &&
              'border-emerald-300 bg-emerald-50/70',
            distanceTone === 'amber' &&
              'border-amber-300 bg-amber-50/70',
            distanceTone === 'red' &&
              'border-red-300 bg-red-50/70',
          )}
        >
          <span
            className={cn(
              'text-[10.5px] font-semibold uppercase tracking-wider',
              distanceTone === 'green' && 'text-emerald-800',
              distanceTone === 'amber' && 'text-amber-800',
              distanceTone === 'red' && 'text-red-800',
            )}
          >
            Distance between addresses
          </span>
          <span
            className={cn(
              'text-[14px] font-bold tabular-nums',
              distanceTone === 'green' && 'text-emerald-900',
              distanceTone === 'amber' && 'text-amber-900',
              distanceTone === 'red' && 'text-red-900',
            )}
          >
            {distanceLabel}
          </span>
          {distanceHint && (
            <span className="text-[11.5px] text-pfl-slate-700 italic">
              {distanceHint}
            </span>
          )}
        </div>
      )}

      {matchedPair && (
        <div className="grid grid-cols-2 gap-3">
          {matchedPair.map((k) => (
            <div
              key={k}
              className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-2"
            >
              <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
                {humanKey(k)}
              </div>
              <div className="text-[12px] text-pfl-slate-800 whitespace-pre-wrap break-words">
                {formatEvidenceValue(ev[k])}
              </div>
            </div>
          ))}
        </div>
      )}

      {isOwnerRule && (
        <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-2 text-[12px]">
          <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1.5">
            Bill vs loan parties
          </div>
          <div className="grid grid-cols-[max-content,1fr] gap-x-3 gap-y-1">
            <span className="font-medium text-pfl-slate-600">Bill owner</span>
            <span className="text-pfl-slate-900">
              {formatEvidenceValue(ev['bill_owner'])}
            </span>
            {!!ev['bill_father_or_husband'] && (
              <>
                <span className="font-medium text-pfl-slate-600">Bill S/O · W/O</span>
                <span className="text-pfl-slate-900">
                  {formatEvidenceValue(ev['bill_father_or_husband'])}
                </span>
              </>
            )}
            <span className="font-medium text-pfl-slate-600">Applicant</span>
            <span className="text-pfl-slate-900">
              {formatEvidenceValue(ev['applicant_name'])}
            </span>
            {!!ev['applicant_aadhaar_father'] && (
              <>
                <span className="font-medium text-pfl-slate-600">
                  Applicant S/O · W/O (Aadhaar)
                </span>
                <span className="text-pfl-slate-900">
                  {formatEvidenceValue(ev['applicant_aadhaar_father'])}
                </span>
              </>
            )}
            {!!ev['co_applicant_name'] && (
              <>
                <span className="font-medium text-pfl-slate-600">Co-applicant</span>
                <span className="text-pfl-slate-900">
                  {formatEvidenceValue(ev['co_applicant_name'])}
                </span>
              </>
            )}
            {Array.isArray(ev['guarantor_names']) &&
              (ev['guarantor_names'] as unknown[]).length > 0 && (
                <>
                  <span className="font-medium text-pfl-slate-600">Guarantors</span>
                  <span className="text-pfl-slate-900">
                    {formatEvidenceValue(ev['guarantor_names'])}
                  </span>
                </>
              )}
          </div>
        </div>
      )}

      {hasGpsMatch && (
        <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-2 text-[12px]">
          <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
            Aadhaar ↔ GPS structured match
          </div>
          <div className="text-pfl-slate-900">
            Verdict:{' '}
            <span className="font-semibold">
              {String(gpsMatch?.verdict ?? '—').toUpperCase()}
            </span>
            {typeof gpsMatch?.score === 'number' && (
              <>
                {' '}· Score <span className="font-mono">{gpsMatch.score}/100</span>
              </>
            )}
          </div>
          {gpsMatch?.reason && (
            <div className="mt-1 text-pfl-slate-600 italic">
              {gpsMatch.reason}
            </div>
          )}
        </div>
      )}

      {rest.length > 0 && (
        <div className="grid grid-cols-[max-content,1fr] gap-x-3 gap-y-1 text-[12px]">
          {rest.map((k) => (
            <React.Fragment key={k}>
              <span className="font-medium text-pfl-slate-600">
                {humanKey(k)}
              </span>
              <span className="text-pfl-slate-800 font-mono break-words">
                {formatEvidenceValue(ev[k])}
              </span>
            </React.Fragment>
          ))}
        </div>
      )}
    </div>
  )
}

// LevelSourceFilesPanel removed — every concern + passing rule now
// renders its own source-files column on the right of EvidenceTwoColumn,
// so the level-wide aggregate became redundant.

function severityVerdict(
  s: LevelIssueRead['severity'],
  status?: LevelIssueRead['status'],
): Verdict {
  if (status === 'MD_APPROVED') return 'pass'
  return s === 'CRITICAL' ? 'fail' : s === 'WARNING' ? 'warn' : 'info'
}

function statusToVerdict(status: VerificationLevelStatus | undefined): Verdict {
  if (status === 'PASSED') return 'pass'
  if (status === 'PASSED_WITH_MD_OVERRIDE') return 'warn'
  if (status === 'BLOCKED' || status === 'FAILED') return 'fail'
  return 'info'
}

// ---------------------------------------------------------------------------
// Parameter mapping (user's rules, plain English)
// ---------------------------------------------------------------------------

type Param = { label: string; value: string; verdict: Verdict; hint?: string }

function paramsForLevel(
  level: VerificationLevelNumber,
  result: VerificationResultRead | undefined,
): Param[] {
  if (!result) return []
  const sub = (result.sub_step_results ?? {}) as Record<string, unknown>
  const asNum = (v: unknown): number | null =>
    typeof v === 'number' ? v : v == null ? null : Number(v)
  const fmtINR = (v: unknown): string => {
    const n = asNum(v)
    return n == null ? '—' : `₹${n.toLocaleString('en-IN')}`
  }
  const strOrDash = (v: unknown): string =>
    typeof v === 'string' && v.length > 0 ? v : '—'

  if (level === 'L1_ADDRESS') {
    const gps = sub['gps_coords'] as [number, number] | null | undefined
    const gpsDerived = sub['gps_derived_address'] as string | null | undefined
    const gpsSource = sub['gps_source'] as string | null | undefined
    const gpsDerivedSource = sub['gps_derived_address_source'] as
      | 'google'
      | 'nominatim'
      | null
      | undefined
    const bureau = (sub['bureau_addresses_considered'] as string[] | undefined) ?? []
    const bank = (sub['bank_addresses_considered'] as string[] | undefined) ?? []
    const lagr = sub['loan_agreement_parties'] as
      | {
          borrower_name?: string | null
          co_applicants?: string[]
          guarantors?: string[]
          witnesses?: string[]
          cached?: boolean
        }
      | null
      | undefined
    return [
      {
        label: 'Applicant Aadhaar scanned',
        value: sub['applicant_aadhaar_id'] ? 'extracted' : 'missing',
        verdict: sub['applicant_aadhaar_id'] ? 'pass' : 'fail',
      },
      {
        label: 'Co-applicant Aadhaar scanned',
        value: sub['co_applicant_aadhaar_id'] ? 'extracted' : 'missing',
        verdict: sub['co_applicant_aadhaar_id'] ? 'pass' : 'warn',
      },
      {
        label: 'Applicant PAN scanned',
        value: sub['applicant_pan_id'] ? 'extracted' : 'missing',
        verdict: sub['applicant_pan_id'] ? 'pass' : 'fail',
      },
      {
        label: 'Co-applicant PAN scanned',
        value: sub['co_applicant_pan_id'] ? 'extracted' : 'missing',
        verdict: sub['co_applicant_pan_id'] ? 'pass' : 'warn',
      },
      {
        label: 'Ration / electricity bill scanned',
        value: sub['ration_bill_id'] ? 'extracted' : 'missing',
        verdict: sub['ration_bill_id'] ? 'pass' : 'warn',
      },
      // Expose the extracted owner + address from the bill as their own rows
      // so the MD doesn't have to open a failing ration_owner_rule issue to
      // see what the scanner read off the bill.
      ...(sub['ration_bill_id']
        ? ([
            {
              label: 'Bill owner name (extracted)',
              value: strOrDash(sub['ration_bill_owner']),
              verdict:
                typeof sub['ration_bill_owner'] === 'string' &&
                (sub['ration_bill_owner'] as string).length > 0
                  ? 'pass'
                  : 'warn',
              hint:
                'Name printed on the ration / electricity bill — fed into the ration_owner_rule check.',
            },
            {
              label: 'Bill address (extracted)',
              value: strOrDash(sub['ration_bill_address']),
              verdict:
                typeof sub['ration_bill_address'] === 'string' &&
                (sub['ration_bill_address'] as string).length > 0
                  ? 'pass'
                  : 'info',
              hint:
                'Premises address printed on the bill — not currently cross-checked against Aadhaar but available as audit evidence.',
            },
          ] as Param[])
        : []),
      {
        label: 'House-visit photo GPS',
        value: gps
          ? `${gps[0].toFixed(5)}, ${gps[1].toFixed(5)}${
              gpsSource === 'watermark'
                ? ' (from burn-in overlay)'
                : gpsSource === 'exif'
                ? ' (from EXIF)'
                : ''
            }`
          : 'not recovered',
        verdict: gps ? 'pass' : 'warn',
        hint:
          'Reads from JPEG EXIF first; falls back to Claude Haiku vision OCR on the GPS Map Camera burn-in overlay when EXIF is absent (WhatsApp strips EXIF).',
      },
      {
        label: 'Reverse-geocode',
        value: gpsDerived
          ? `${gpsDerived}${
              gpsDerivedSource === 'google'
                ? ' (via Google Maps)'
                : gpsDerivedSource === 'nominatim'
                ? ' (via OpenStreetMap)'
                : ''
            }`
          : '—',
        verdict: gpsDerived ? 'pass' : 'warn',
        hint:
          'Resolves (lat, lon) → address via Google Maps; falls back to OpenStreetMap Nominatim if the Google Geocoding API is disabled or over quota.',
      },
      ...(() => {
        const commuteStatus = sub['commute_sub_step_status'] as
          | string
          | null
          | undefined
        // Pre-upgrade L1 results don't carry the new keys; skip the 3 new
        // rows entirely so historical cards render unchanged.
        if (commuteStatus == null) {
          return [] as Param[]
        }
        // Defensive: a stale schema or bad migration could hand us a
        // non-tuple shape. `.toFixed()` below would then throw at render
        // time and take down the whole L1 card — guard before coercing.
        const rawBizGps = sub['business_gps_coords']
        const bizGps: [number, number] | null =
          Array.isArray(rawBizGps) &&
          rawBizGps.length === 2 &&
          typeof rawBizGps[0] === 'number' &&
          typeof rawBizGps[1] === 'number'
            ? (rawBizGps as [number, number])
            : null
        const bizGpsSource = sub['business_gps_source'] as
          | 'exif'
          | 'watermark'
          | null
          | undefined
        const travelMin = asNum(sub['commute_travel_minutes'])
        const distKm = asNum(sub['commute_distance_km'])
        const verdict = sub['commute_judge_verdict'] as
          | {
              severity?: 'WARNING' | 'CRITICAL'
              reason?: string
              confidence?: string
            }
          | null
          | undefined

        const businessGpsRow: Param = {
          label: 'Business-visit photo GPS',
          value: bizGps
            ? `${bizGps[0].toFixed(5)}, ${bizGps[1].toFixed(5)}${
                bizGpsSource === 'watermark'
                  ? ' (from burn-in overlay)'
                  : bizGpsSource === 'exif'
                  ? ' (from EXIF)'
                  : ''
              }`
            : 'not recovered',
          verdict: bizGps ? 'pass' : 'fail',
          hint:
            'Reads GPS from JPEG EXIF first; falls back to Claude Haiku vision OCR on the GPS-Map-Camera burn-in overlay when EXIF is stripped (WhatsApp strips EXIF).',
        }

        const bizDerived = sub['business_derived_address'] as
          | string
          | null
          | undefined
        const businessReverseRow: Param = {
          label: 'Reverse-geocode (business)',
          value: strOrDash(bizDerived),
          verdict: bizDerived ? 'pass' : bizGps ? 'warn' : 'info',
          hint:
            'Resolves the business GPS (lat, lon) → address via Google Maps. Fed into the Opus commute judge as context.',
        }

        const commuteValue = (() => {
          if (commuteStatus === 'skipped_missing_business_gps') {
            return '— (business GPS missing)'
          }
          if (commuteStatus === 'skipped_missing_house_gps') {
            return '— (house GPS missing)'
          }
          if (commuteStatus === 'block_no_route') {
            return 'no drivable route found'
          }
          if (commuteStatus === 'warn_dm_unavailable') {
            return 'Distance Matrix unavailable'
          }
          if (travelMin == null || distKm == null) {
            return '—'
          }
          const base = `${travelMin.toFixed(0)} min · ${distKm.toFixed(1)} km (driving)`
          if (travelMin > 30) {
            return `over 30 min (${base})`
          }
          return base
        })()
        const commuteVerdict: Param['verdict'] =
          commuteStatus === 'pass'
            ? 'pass'
            : commuteStatus === 'flag_reviewable' ||
              commuteStatus === 'warn_dm_unavailable' ||
              commuteStatus === 'warn_judge_unavailable'
            ? 'warn'
            : commuteStatus === 'block_no_route' ||
              commuteStatus === 'block_absurd'
            ? 'fail'
            : 'info'
        const commuteRow: Param = {
          label: 'House → Business commute',
          value: commuteValue,
          verdict: commuteVerdict,
          hint:
            'Google Distance Matrix, driving mode without live traffic. Cases over 30 min are reviewed by Claude Opus using applicant profile (occupation, loan amount, area, bureau history, bank income pattern).',
        }

        const aiReviewRow: Param | null = verdict
          ? {
              label: 'Commute AI review',
              value: `${verdict.severity === 'CRITICAL' ? 'BLOCK' : 'FLAG'}: ${
                verdict.reason ?? ''
              }`,
              verdict: verdict.severity === 'CRITICAL' ? 'fail' : 'warn',
              hint:
                'Claude Opus reviewed the applicant profile and judged whether the over-30-min commute is reviewable (FLAG) or implausible (BLOCK).',
            }
          : null

        return aiReviewRow
          ? [businessGpsRow, businessReverseRow, commuteRow, aiReviewRow]
          : [businessGpsRow, businessReverseRow, commuteRow]
      })(),
      {
        label: 'Equifax addresses considered',
        value: `${bureau.length} found`,
        verdict: bureau.length > 0 ? 'pass' : 'info',
      },
      {
        label: 'Bank-statement addresses considered',
        value: `${bank.length} found`,
        verdict: bank.length > 0 ? 'pass' : 'info',
      },
      {
        label: 'Loan-agreement parties scanned',
        value: lagr
          ? [
              lagr.borrower_name ? `borrower: ${lagr.borrower_name}` : null,
              lagr.co_applicants && lagr.co_applicants.length > 0
                ? `co-app: ${lagr.co_applicants.join(', ')}`
                : null,
              lagr.guarantors && lagr.guarantors.length > 0
                ? `guarantor: ${lagr.guarantors.join(', ')}`
                : null,
              lagr.witnesses && lagr.witnesses.length > 0
                ? `witness: ${lagr.witnesses.join(', ')}`
                : null,
            ]
              .filter(Boolean)
              .join(' · ') || 'no named parties'
          : 'agreement not scanned',
        verdict: lagr ? 'pass' : 'info',
        hint:
          'Claude Haiku inline-scans the signed LAGR PDF during L1 (cached per case). This is independent of the L4 verification — L4 can be NOT RUN and we still know who is on the agreement.',
      },
    ]
  }

  if (level === 'L1_5_CREDIT') {
    const applicant = (sub['applicant'] as Record<string, unknown>) ?? {}
    const coapp = (sub['co_applicant'] as Record<string, unknown>) ?? {}
    const analyst = (sub['analyst'] as Record<string, unknown>) ?? {}
    const aScore = asNum(applicant['credit_score'])
    const cScore = asNum(coapp['credit_score'])
    const aSummary = (applicant['summary'] as Record<string, unknown>) ?? {}
    const aOpen = asNum(aSummary['open_accounts']) ?? 0
    const aTotal = asNum(aSummary['total_accounts']) ?? 0
    const aPastDue = asNum(aSummary['past_due_accounts'])
    const overall = strOrDash(analyst['overall_verdict'])
    const rec = strOrDash(analyst['recommendation'])
    const aAccountsCount = asNum(applicant['accounts_count']) ?? 0
    const cAccountsCount = asNum(coapp['accounts_count']) ?? 0
    const rows: Param[] = [
      {
        label: 'Applicant credit score',
        value:
          aScore === null || aScore === undefined
            ? 'NTC / no hit'
            : String(aScore),
        verdict:
          aScore === null || aScore === undefined
            ? 'warn'
            : aScore >= 700
            ? 'pass'
            : aScore >= 600
            ? 'warn'
            : 'fail',
        hint: 'Pass ≥ 700 · warn ≥ 600 · fail < 500',
      },
      {
        label: 'Applicant active accounts',
        value: `${aOpen} open / ${aTotal} total`,
        verdict: aOpen === 0 ? 'pass' : aOpen <= 5 ? 'pass' : 'warn',
      },
    ]
    if (aPastDue !== undefined && aPastDue !== null) {
      rows.push({
        label: 'Applicant past-due accounts',
        value: `${aPastDue}`,
        verdict: aPastDue === 0 ? 'pass' : 'fail',
      })
    }
    rows.push({
      label: 'Applicant accounts analysed',
      value: `${aAccountsCount}`,
      verdict: aAccountsCount > 0 ? 'pass' : 'warn',
    })
    rows.push({
      label: 'Co-applicant credit score',
      value:
        cScore === null || cScore === undefined
          ? 'NTC / no hit'
          : String(cScore),
      verdict:
        cScore === null || cScore === undefined
          ? 'info'
          : cScore >= 700
          ? 'pass'
          : cScore >= 600
          ? 'warn'
          : 'fail',
    })
    rows.push({
      label: 'Co-applicant accounts analysed',
      value: `${cAccountsCount}`,
      verdict: cAccountsCount > 0 ? 'pass' : 'info',
    })
    rows.push({
      label: 'Opus overall verdict',
      value: overall === '—' ? 'not run' : overall,
      verdict:
        overall === 'clean'
          ? 'pass'
          : overall === 'caution'
          ? 'warn'
          : overall === 'adverse'
          ? 'fail'
          : 'info',
    })
    rows.push({
      label: 'Opus recommendation',
      value: rec === '—' ? 'not run' : rec,
      verdict:
        rec === 'proceed'
          ? 'pass'
          : rec === 'escalate_md'
          ? 'warn'
          : rec === 'reject'
          ? 'fail'
          : 'info',
    })
    return rows
  }

  if (level === 'L2_BANKING') {
    const ca = (sub['ca_analyser'] as Record<string, unknown>) ?? {}
    const nach = asNum(ca['nach_bounce_count']) ?? 0
    const payers = asNum(ca['distinct_credit_payers']) ?? 0
    const creditSum = asNum(ca['three_month_credit_sum_inr']) ?? 0
    const avgBal = asNum(ca['avg_monthly_balance_inr']) ?? 0
    const impulsive = asNum(ca['impulsive_debit_total_inr']) ?? 0
    const declared = asNum(sub['declared_monthly_income_inr']) ?? 0
    const emi = asNum(sub['proposed_emi_inr']) ?? 0
    const txCount = asNum(sub['tx_line_count']) ?? 0
    return [
      {
        label: 'NACH / ECS bounces',
        value: `${nach}`,
        verdict: nach === 0 ? 'pass' : 'fail',
      },
      {
        label: 'Average monthly balance',
        value: fmtINR(avgBal),
        verdict:
          avgBal >= 1000
            ? emi > 0 && avgBal < emi * 1.5
              ? 'fail'
              : 'pass'
            : 'fail',
        hint: 'Floor ₹1,000; ≥1.5× proposed EMI',
      },
      {
        label: 'Proposed EMI',
        value: emi > 0 ? fmtINR(emi) : 'unknown',
        verdict: emi > 0 ? 'pass' : 'warn',
      },
      {
        label: '3-month credit sum',
        value: fmtINR(creditSum),
        verdict:
          declared === 0
            ? 'info'
            : creditSum >= declared * 3 * 0.5
            ? 'pass'
            : 'warn',
      },
      {
        label: 'Distinct credit payers',
        value: `${payers}`,
        verdict: declared < 15000 ? 'info' : payers >= 2 ? 'pass' : 'warn',
      },
      {
        label: 'Impulsive / retail debits',
        value: fmtINR(impulsive),
        verdict:
          declared === 0 ? 'info' : impulsive <= declared ? 'pass' : 'warn',
      },
      {
        label: 'Declared monthly income (CAM)',
        value: declared > 0 ? fmtINR(declared) : 'not found',
        verdict: declared > 0 ? 'pass' : 'warn',
      },
      {
        label: 'Declared FOIR (CAM)',
        value: (() => {
          const f = asNum(sub['declared_foir_pct'])
          return f != null && f > 0 ? `${f.toFixed(1)}%` : 'not found'
        })(),
        verdict: (() => {
          const f = asNum(sub['declared_foir_pct']) ?? 0
          if (f <= 0) return 'info'
          if (f > 60) return 'fail'
          if (f > 50) return 'warn'
          return 'pass'
        })(),
        hint:
          'FOIR = proposed EMI ÷ monthly income, as declared on the CAM eligibility sheet. Policy ceiling is typically 50-60%; higher → repayment risk.',
      },
      {
        label: 'Transactions analysed',
        value: `${txCount}`,
        verdict: txCount > 0 ? 'pass' : 'fail',
      },
    ]
  }

  if (level === 'L3_VISION') {
    const h = (sub['house'] as Record<string, unknown>) ?? {}
    const b = (sub['business'] as Record<string, unknown>) ?? {}
    const housePhotos = asNum(sub['house_photo_count']) ?? 0
    const bizPhotos = asNum(sub['business_photo_count']) ?? 0
    const houseOverall = strOrDash(h['overall_rating'])
    const constr = strOrDash(h['construction_type'])
    const flooring = strOrDash(h['flooring'])
    const assets = (h['high_value_assets_visible'] as string[] | undefined) ?? []
    const stock = asNum(b['stock_value_estimate_inr'])
    const infra = strOrDash(b['infrastructure_rating'])
    const cattleHealth = strOrDash(b['cattle_health'])
    const acceptable = new Set(['ok', 'good', 'excellent'])
    return [
      {
        label: 'House photos analysed',
        value: `${housePhotos}`,
        verdict: housePhotos > 0 ? 'pass' : 'fail',
      },
      {
        label: 'House overall rating',
        value: houseOverall,
        verdict: acceptable.has(houseOverall) ? 'pass' : 'fail',
        hint: 'Must be ok / good / excellent',
      },
      {
        label: 'Construction type',
        value: constr,
        verdict: constr === 'pakka' ? 'pass' : constr === 'kachha' ? 'fail' : 'warn',
      },
      {
        label: 'Flooring',
        value: flooring,
        verdict:
          flooring === 'tiled' || flooring === 'marble'
            ? 'pass'
            : flooring === 'cemented'
            ? 'warn'
            : 'fail',
      },
      {
        label: 'High-value assets visible',
        value:
          assets.length > 0
            ? `${assets.length} · ${assets.slice(0, 3).join(', ')}`
            : 'none',
        verdict: assets.length >= 2 ? 'pass' : assets.length === 1 ? 'warn' : 'fail',
      },
      {
        label: 'Business photos analysed',
        value: `${bizPhotos}`,
        verdict: bizPhotos > 0 ? 'pass' : 'warn',
      },
      {
        label: 'Stock value estimate',
        value: stock != null ? fmtINR(stock) : '—',
        verdict: stock == null ? 'info' : stock > 0 ? 'pass' : 'warn',
      },
      {
        label: 'Business infrastructure',
        value: infra,
        verdict: acceptable.has(infra)
          ? 'pass'
          : infra === 'bad'
          ? 'warn'
          : infra === 'worst'
          ? 'fail'
          : 'info',
      },
      {
        label: 'Cattle health',
        value: cattleHealth,
        verdict:
          cattleHealth === 'unhealthy'
            ? 'fail'
            : cattleHealth === 'healthy'
            ? 'pass'
            : 'info',
      },
    ]
  }

  if (level === 'L5_SCORING') {
    const scoring = (sub['scoring'] as Record<string, unknown>) ?? {}
    const earned = asNum(scoring['earned_score']) ?? 0
    const maxScore = asNum(scoring['max_score']) ?? 100
    const pct = asNum(scoring['overall_pct']) ?? 0
    const grade = strOrDash(scoring['grade'])
    const ebVerdict = strOrDash(scoring['eb_verdict'])
    const sections =
      (scoring['sections'] as Array<Record<string, unknown>> | undefined) ?? []
    const gradeVerdict: Verdict =
      grade === 'A+' || grade === 'A'
        ? 'pass'
        : grade === 'B'
        ? 'warn'
        : grade === 'C' || grade === 'D'
        ? 'fail'
        : 'info'
    const rows: Param[] = [
      {
        label: 'Overall audit score',
        value: `${earned} / ${maxScore} · ${pct}%`,
        verdict: pct >= 80 ? 'pass' : pct >= 70 ? 'warn' : 'fail',
        hint: '≥80 A · ≥70 B · ≥60 C · <60 D',
      },
      {
        label: 'Grade',
        value: grade,
        verdict: gradeVerdict,
      },
      {
        label: 'Eligibility vs Banking verdict',
        value: ebVerdict,
        verdict:
          ebVerdict === 'PASS'
            ? 'pass'
            : ebVerdict === 'CONCERN'
            ? 'warn'
            : ebVerdict === 'FAIL'
            ? 'fail'
            : 'info',
      },
    ]
    for (const s of sections) {
      const sid = strOrDash(s['section_id'])
      const title = strOrDash(s['title'])
      const spct = asNum(s['pct']) ?? 0
      const sEarned = asNum(s['earned']) ?? 0
      const sMax = asNum(s['max_score']) ?? 0
      rows.push({
        label: `Section ${sid}: ${title}`,
        value: `${sEarned} / ${sMax} · ${spct}%`,
        verdict: spct >= 70 ? 'pass' : spct >= 50 ? 'warn' : 'fail',
      })
    }
    return rows
  }

  if (level === 'L4_AGREEMENT') {
    const s = (sub['scanner'] as Record<string, unknown>) ?? {}
    const page = s['annexure_page_hint']
    return [
      {
        label: 'Agreement PDF located',
        value: strOrDash(sub['agreement_filename']),
        verdict: sub['agreement_filename'] ? 'pass' : 'fail',
      },
      {
        label: 'Loan ID in agreement',
        value: strOrDash(s['loan_id']),
        verdict: s['loan_id'] ? 'pass' : 'warn',
      },
      {
        label: 'Borrower name in agreement',
        value: strOrDash(s['borrower_name']),
        verdict: s['borrower_name'] ? 'pass' : 'warn',
      },
      {
        label: 'Annexure / schedule section',
        value: s['annexure_present'] ? `present (page ${page ?? '?'})` : 'missing',
        verdict: s['annexure_present'] ? 'pass' : 'fail',
      },
      {
        label: 'Hypothecation clause',
        value: s['hypothecation_clause_present'] ? 'present' : 'missing',
        verdict: s['hypothecation_clause_present'] ? 'pass' : 'fail',
      },
      {
        label: 'Assets listed in annexure',
        value: `${asNum(s['asset_count']) ?? 0}`,
        verdict: (asNum(s['asset_count']) ?? 0) > 0 ? 'pass' : 'fail',
      },
    ]
  }

  return []
}

// ---------------------------------------------------------------------------
// Parameter row
// ---------------------------------------------------------------------------

/**
 * Evidence-gathered section with a compact-checklist default and an
 * "Show details" expand. Rationale: operators care about "did the
 * extraction sweep cover everything?" at a glance; the per-field
 * values rarely drive decisioning and clutter the page. Collapsed
 * view = one-line pass/warn/fail tally plus the labels of any
 * non-pass rows, so the operator still sees what's missing without
 * scrolling 20 rows.
 */
function EvidenceGatheredSection({
  params,
  children,
}: {
  params: Param[]
  children?: React.ReactNode
}) {
  const [expanded, setExpanded] = React.useState(false)

  const counts = React.useMemo(() => {
    const c = { pass: 0, warn: 0, fail: 0, info: 0 }
    for (const p of params) c[p.verdict] = (c[p.verdict] ?? 0) + 1
    return c
  }, [params])

  const nonPassRows = React.useMemo(
    () => params.filter((p) => p.verdict === 'warn' || p.verdict === 'fail'),
    [params],
  )

  return (
    <>
      <div className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-2 flex items-center gap-2 flex-wrap">
        <span>Evidence gathered</span>
        <span className="text-pfl-slate-300">·</span>
        <span className="font-normal normal-case tracking-normal text-pfl-slate-500">
          {params.length} check{params.length === 1 ? '' : 's'}
          {counts.pass > 0 && (
            <>
              {' '}· <span className="text-emerald-700">{counts.pass} pass</span>
            </>
          )}
          {counts.warn > 0 && (
            <>
              {' '}· <span className="text-amber-700">{counts.warn} warn</span>
            </>
          )}
          {counts.fail > 0 && (
            <>
              {' '}· <span className="text-red-700">{counts.fail} fail</span>
            </>
          )}
        </span>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="ml-auto text-pfl-slate-600 hover:text-pfl-slate-900 font-medium normal-case tracking-normal text-[11px]"
        >
          {expanded ? 'Hide details ▴' : 'Show details ▾'}
        </button>
      </div>

      {/* Collapsed summary — one compact card listing only the non-pass
          rows the operator actually needs to act on. All-pass levels
          render an empty green check card. */}
      {!expanded && (
        <div className="border border-pfl-slate-200 rounded bg-white p-3 text-[12.5px]">
          {nonPassRows.length === 0 ? (
            <div className="text-pfl-slate-600 flex items-center gap-2">
              <span className="text-emerald-600">✓</span>
              All {params.length} extraction checks passed.
            </div>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {nonPassRows.map((p, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span
                    className={cn(
                      'mt-0.5 text-[11px] font-bold',
                      p.verdict === 'fail' && 'text-red-600',
                      p.verdict === 'warn' && 'text-amber-600',
                    )}
                    aria-hidden
                  >
                    {p.verdict === 'fail' ? '✗' : '!'}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-pfl-slate-800 font-medium">
                      {p.label}
                    </div>
                    <div className="text-[11.5px] text-pfl-slate-500 truncate">
                      {p.value}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Expanded — full per-field detail, same as before. */}
      {expanded && (
        <>
          <div className="border border-pfl-slate-200 rounded bg-white">
            {params.map((p, i) => (
              <ParamRow key={i} param={p} />
            ))}
          </div>
          {children}
        </>
      )}
    </>
  )
}

function ParamRow({ param }: { param: Param }) {
  return (
    <div className="flex items-center gap-3 py-2 border-b border-pfl-slate-100 last:border-b-0">
      <Tick verdict={param.verdict} />
      <div className="flex-1 min-w-0">
        <div className="text-[13px] text-pfl-slate-800 leading-tight">
          {param.label}
        </div>
        {param.hint && (
          <div className="text-[11px] text-pfl-slate-500 mt-0.5">{param.hint}</div>
        )}
      </div>
      <div
        className={cn(
          'shrink-0 text-right text-[12px] font-mono tabular-nums max-w-[45%] truncate',
          param.verdict === 'fail'
            ? 'text-red-700 font-semibold'
            : param.verdict === 'warn'
            ? 'text-amber-700'
            : param.verdict === 'pass'
            ? 'text-emerald-700'
            : 'text-pfl-slate-600',
        )}
      >
        {param.value}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Findings (level-specific)
// ---------------------------------------------------------------------------

function FindingsList({
  title,
  tone,
  items,
}: {
  title: string
  tone: 'warn' | 'pass'
  items: string[]
}) {
  if (items.length === 0) return null
  return (
    <div>
      <div
        className={cn(
          'text-[11px] font-semibold uppercase tracking-wider mb-1.5',
          tone === 'warn' ? 'text-red-700' : 'text-emerald-700',
        )}
      >
        {title} ({items.length})
      </div>
      <ul className="text-[12.5px] text-pfl-slate-700 space-y-1 list-disc pl-5">
        {items.map((t, i) => (
          <li key={i} className="leading-snug">
            {t}
          </li>
        ))}
      </ul>
    </div>
  )
}

function L2Findings({ detail }: { detail: VerificationLevelDetail }) {
  const ca =
    (detail.result.sub_step_results?.['ca_analyser'] as
      | Record<string, unknown>
      | undefined) ?? {}
  const concerns = (ca['ca_concerns'] as string[] | undefined) ?? []
  const positives = (ca['ca_positives'] as string[] | undefined) ?? []
  if (concerns.length === 0 && positives.length === 0) return null
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4 pt-4 border-t border-pfl-slate-100">
      <FindingsList title="CA concerns" tone="warn" items={concerns} />
      <FindingsList title="CA positives" tone="pass" items={positives} />
    </div>
  )
}

function L3Findings({ detail }: { detail: VerificationLevelDetail }) {
  const h =
    (detail.result.sub_step_results?.['house'] as
      | Record<string, unknown>
      | undefined) ?? {}
  const b =
    (detail.result.sub_step_results?.['business'] as
      | Record<string, unknown>
      | undefined) ?? {}
  const bizType = (b['business_type'] as string | undefined) ?? null
  const bizSubtype = (b['business_subtype'] as string | undefined) ?? null
  const recommendedLoan = (() => {
    const v = b['recommended_loan_amount_inr']
    return typeof v === 'number' && v > 0 ? v : null
  })()
  const equipmentValue = (() => {
    const v = b['visible_equipment_value_inr']
    return typeof v === 'number' && v > 0 ? v : null
  })()
  const stockValue = (() => {
    const v = b['stock_value_estimate_inr']
    return typeof v === 'number' && v > 0 ? v : null
  })()
  const rationale =
    (b['recommended_loan_rationale'] as string | undefined) ?? null
  const Section = ({
    kicker,
    concerns,
    positives,
  }: {
    kicker: string
    concerns: string[]
    positives: string[]
  }) => (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-600 mb-2">
        {kicker}
      </div>
      <div className="space-y-3">
        <FindingsList title="Concerns" tone="warn" items={concerns} />
        <FindingsList title="Positives" tone="pass" items={positives} />
      </div>
    </div>
  )
  return (
    <div className="mt-4 pt-4 border-t border-pfl-slate-100">
      {(bizType || recommendedLoan || stockValue || equipmentValue) && (
        <div className="mb-4 rounded border border-sky-200 bg-sky-50/60 px-3 py-2 text-[12.5px] text-sky-900">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10.5px] font-semibold uppercase tracking-wider text-sky-700">
              Vision model
            </span>
            {bizType && (
              <span className="rounded bg-white px-1.5 py-0.5 text-[11px] font-medium text-pfl-slate-700 border border-sky-200">
                {bizSubtype ? `${bizSubtype} · ` : ''}
                {bizType.replace('_', ' ')}
              </span>
            )}
            {recommendedLoan && (
              <span className="rounded bg-white px-1.5 py-0.5 text-[11px] font-mono text-pfl-slate-800 border border-sky-200">
                recommends ₹{recommendedLoan.toLocaleString('en-IN')}
              </span>
            )}
            {stockValue && (
              <span className="rounded bg-white px-1.5 py-0.5 text-[11px] font-mono text-pfl-slate-700 border border-sky-200">
                stock ₹{stockValue.toLocaleString('en-IN')}
              </span>
            )}
            {equipmentValue && (
              <span className="rounded bg-white px-1.5 py-0.5 text-[11px] font-mono text-pfl-slate-700 border border-sky-200">
                equipment ₹{equipmentValue.toLocaleString('en-IN')}
              </span>
            )}
          </div>
          {rationale && (
            <p className="mt-1.5 leading-snug text-[12px] text-sky-900/90">
              {rationale}
            </p>
          )}
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Section
          kicker="House visit"
          concerns={(h['concerns'] as string[] | undefined) ?? []}
          positives={(h['positives'] as string[] | undefined) ?? []}
        />
        <Section
          kicker="Business premises"
          concerns={(b['concerns'] as string[] | undefined) ?? []}
          positives={(b['positives'] as string[] | undefined) ?? []}
        />
      </div>
    </div>
  )
}

function L4Findings({ detail }: { detail: VerificationLevelDetail }) {
  const s =
    (detail.result.sub_step_results?.['scanner'] as
      | Record<string, unknown>
      | undefined) ?? {}
  const assetsRaw = s['assets']
  const assets = Array.isArray(assetsRaw)
    ? (assetsRaw as Array<Record<string, unknown>>)
    : []
  if (assets.length === 0) {
    return (
      <div className="mt-4 pt-4 border-t border-pfl-slate-100 rounded bg-red-50 border border-red-200 p-3 text-[12.5px] text-red-800 leading-relaxed">
        Zero assets listed — the annexure section is blank. Recovery
        enforceability requires every hypothecated asset enumerated in the
        signed agreement. Assessor must re-upload a corrected LAGR.
      </div>
    )
  }
  return (
    <div className="mt-4 pt-4 border-t border-pfl-slate-100">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-600 mb-2">
        Assets in annexure · {assets.length}
      </div>
      <table className="w-full text-[12px] border-collapse">
        <thead>
          <tr className="text-pfl-slate-500 text-[10px] uppercase tracking-wider">
            <th className="text-left py-1.5 pr-3 border-b border-pfl-slate-200 font-semibold">
              #
            </th>
            <th className="text-left py-1.5 pr-3 border-b border-pfl-slate-200 font-semibold">
              Description
            </th>
            <th className="text-right py-1.5 pr-3 border-b border-pfl-slate-200 font-semibold">
              Value ₹
            </th>
            <th className="text-left py-1.5 border-b border-pfl-slate-200 font-semibold">
              Identifier
            </th>
          </tr>
        </thead>
        <tbody>
          {assets.map((a, i) => (
            <tr key={i} className="border-b border-pfl-slate-100">
              <td className="py-1.5 pr-3 text-pfl-slate-500">{i + 1}</td>
              <td className="py-1.5 pr-3">
                {(a['description'] as string) ?? '—'}
              </td>
              <td className="py-1.5 pr-3 text-right font-mono tabular-nums">
                {a['value_inr'] == null
                  ? '—'
                  : `${Number(a['value_inr']).toLocaleString('en-IN')}`}
              </td>
              <td className="py-1.5 font-mono">
                {(a['identifier'] as string) ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Issue row
// ---------------------------------------------------------------------------

function IssueRow({
  issue,
  ruleTitle = null,
  isMD,
  caseId,
  levelNumber,
  onResolve,
  onDecide,
}: {
  issue: LevelIssueRead
  /** Friendly rule name from RULE_CATALOG — shown in the strip so the MD
   *  doesn't have to decode the mechanical sub_step_id. Null for runtime
   *  issues that aren't in the catalog. */
  ruleTitle?: string | null
  isMD: boolean
  caseId: string
  levelNumber: VerificationLevelNumber
  onResolve: (id: string, note: string) => Promise<void>
  onDecide: (id: string, d: 'MD_APPROVED' | 'MD_REJECTED', r: string) => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const [decision, setDecision] = useState<'MD_APPROVED' | 'MD_REJECTED'>(
    'MD_APPROVED',
  )
  const [rationale, setRationale] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const canAssessorAct = issue.status === 'OPEN'
  const canMDAct = isMD && issue.status === 'ASSESSOR_RESOLVED'
  // PDD (Post-Disbursement Documents) escalation: MD can short-circuit a
  // missing-PDC or PDC-bank-mismatch CRITICAL straight to MD_APPROVED with a
  // written assurance that the document will be collected after disbursal.
  // No assessor handoff needed — saves a round-trip when the MD has already
  // agreed verbally with the operations team.
  const isPdcIssue =
    issue.sub_step_id === 'pdc_present' || issue.sub_step_id === 'pdc_matches_bank'
  const canPddEscalate =
    isMD && isPdcIssue && issue.status === 'OPEN' && issue.severity === 'CRITICAL'
  const [pddNote, setPddNote] = useState('')
  const [pddBusy, setPddBusy] = useState(false)

  // Fetch precedents lazily — only when the issue row is expanded.
  // (Source-photo thumbnails were moved to the L3 header panel and are
  //  no longer rendered inside the per-concern expansion.)
  const { data: precedents } = usePrecedents(
    open ? issue.sub_step_id : null,
    isMD,
  )

  async function handleResolve() {
    setBusy(true)
    setErr(null)
    try {
      await onResolve(issue.id, note)
      setNote('')
      setOpen(false)
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Failed to resolve')
    } finally {
      setBusy(false)
    }
  }
  async function handleDecide() {
    setBusy(true)
    setErr(null)
    try {
      await onDecide(issue.id, decision, rationale)
      setRationale('')
      setOpen(false)
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Failed to record decision')
    } finally {
      setBusy(false)
    }
  }

  async function handlePddEscalate() {
    setPddBusy(true)
    setErr(null)
    try {
      // [PDD] prefix is the audit-trail marker — same convention as the
      // [MITIGATION] / [AI auto-justified] tags the auto-justifier uses,
      // so the report + learning-rules feed know this was a deferred-doc
      // approval rather than a substantive override.
      await onDecide(
        issue.id,
        'MD_APPROVED',
        `[PDD] PDC to be collected post-disbursement. ${pddNote.trim()}`,
      )
      setPddNote('')
      setOpen(false)
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Failed to record PDD approval')
    } finally {
      setPddBusy(false)
    }
  }

  return (
    <div className="border-b border-pfl-slate-100 last:border-b-0">
      <button
        type="button"
        className="w-full flex items-start gap-3 py-2.5 px-1 text-left hover:bg-pfl-slate-50"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <Tick verdict={severityVerdict(issue.severity, issue.status)} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5 flex-wrap">
            <SeverityPill severity={issue.severity} status={issue.status} />
            {ruleTitle && (
              <span className="text-[12.5px] font-semibold text-pfl-slate-900">
                {ruleTitle}
              </span>
            )}
            <span className="text-[11px] font-mono text-pfl-slate-500 truncate">
              {issue.sub_step_id}
            </span>
          </div>
          {!open && (
            <div className="text-[13px] text-pfl-slate-800 leading-snug line-clamp-2">
              {issue.description.split('\n')[0]}
            </div>
          )}
        </div>
        <IssueStatusPill status={issue.status} />
      </button>

      {open && (
        <div className="ml-7 mb-3 mr-1 text-[13px] flex flex-col gap-3">
          {/* Issue description now renders inside the WHAT WAS CHECKED
              container as a "Description of issue" subsection in the
              LEFT column — the inline source viewer made the right
              column taller, so the spare LEFT space absorbs the
              narrative without the previous duplication above the
              panel. */}
          <IssueEvidencePanel issue={issue} caseId={caseId} />

          {/* Past MD decisions on the same sub_step_id — learning context */}
          {isMD &&
            precedents &&
            precedents.items.length > 0 && (
              <div className="border border-pfl-slate-200 rounded-md bg-indigo-50/40 p-3">
                <div className="text-[10.5px] font-semibold uppercase tracking-wider text-indigo-700 mb-2 flex items-center gap-2">
                  Past MD decisions on <span className="font-mono normal-case tracking-normal text-[11px]">{issue.sub_step_id}</span>
                  <span className="text-pfl-slate-400">·</span>
                  <span className="text-emerald-700">
                    {precedents.approved_count} approved
                  </span>
                  <span className="text-pfl-slate-400">·</span>
                  <span className="text-red-700">
                    {precedents.rejected_count} rejected
                  </span>
                </div>
                <div className="flex flex-col gap-1.5">
                  {precedents.items.slice(0, 5).map((p) => (
                    <div
                      key={p.issue_id}
                      className="text-[12px] border-l-2 border-indigo-300 pl-2"
                    >
                      <div className="flex items-center gap-2 flex-wrap">
                        <span
                          className={cn(
                            'text-[10px] font-semibold uppercase tracking-wider rounded px-1 py-0.5',
                            p.decision === 'MD_APPROVED'
                              ? 'text-emerald-700 bg-emerald-50'
                              : 'text-red-700 bg-red-50',
                          )}
                        >
                          {p.decision === 'MD_APPROVED' ? 'APPROVED' : 'REJECTED'}
                        </span>
                        <span className="font-mono text-pfl-slate-500 text-[11px]">
                          {p.loan_id}
                        </span>
                        <span className="text-pfl-slate-600">
                          {p.applicant_name ?? 'unknown'}
                        </span>
                      </div>
                      {p.md_rationale && (
                        <div className="text-pfl-slate-700 mt-0.5 leading-snug">
                          {p.md_rationale}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
                {precedents.items.length > 5 && (
                  <div className="mt-2 text-[11px] italic text-pfl-slate-500">
                    +{precedents.items.length - 5} more precedents hidden.
                  </div>
                )}
              </div>
            )}

          {issue.assessor_note && (
            <div className="border-l-2 border-indigo-300 pl-3 bg-indigo-50/40 py-1.5 rounded-r">
              <div className="text-[10px] uppercase tracking-wider text-indigo-700 font-semibold mb-0.5">
                Assessor
              </div>
              <div className="text-pfl-slate-800">{issue.assessor_note}</div>
            </div>
          )}
          {issue.md_rationale && (
            <div className="border-l-2 border-emerald-400 pl-3 bg-emerald-50/40 py-1.5 rounded-r">
              <div className="text-[10px] uppercase tracking-wider text-emerald-700 font-semibold mb-0.5">
                MD rationale
              </div>
              <div className="text-pfl-slate-800">{issue.md_rationale}</div>
            </div>
          )}
          {canPddEscalate && (
            <div className="flex flex-col gap-2 rounded border border-amber-300 bg-amber-50/80 px-3 py-2.5">
              <div className="flex items-center gap-2">
                <span className="text-[10px] uppercase tracking-wider text-amber-800 font-bold">
                  PDD escalation
                </span>
                <span className="text-[11.5px] text-amber-900">
                  MD short-circuit — no assessor step
                </span>
              </div>
              <p className="text-[12.5px] text-amber-950 leading-snug">
                {issue.sub_step_id === 'pdc_present'
                  ? 'PDC cheque not on file. As MD you can grant Post-Disbursement Documents (PDD) approval — the borrower commits to providing the cheque after disbursal against your written assurance below.'
                  : 'PDC cheque does not match the borrower’s bank statement. As MD you can grant PDD approval — the borrower commits to providing a corrected cheque post-disbursal against your written assurance.'}
              </p>
              <textarea
                className="border border-amber-300 rounded p-2 text-[13px] focus:outline-none focus:border-amber-500 bg-white"
                rows={2}
                value={pddNote}
                onChange={(e) => setPddNote(e.target.value)}
                placeholder="PDD assurance — e.g. cheque to be collected by branch within 7 days of disbursal"
              />
              <button
                type="button"
                className="self-start inline-flex items-center gap-1.5 rounded bg-amber-700 hover:bg-amber-800 text-white px-3 py-1.5 text-[11px] uppercase tracking-wider font-semibold disabled:opacity-40"
                disabled={pddBusy || pddNote.trim().length < 4}
                onClick={handlePddEscalate}
              >
                {pddBusy ? 'Submitting…' : 'Resolve with PDD approval'}
              </button>
            </div>
          )}
          {canAssessorAct && (
            <div className="flex flex-col gap-2">
              <label className="text-[11px] uppercase tracking-wider text-pfl-slate-600 font-semibold">
                Assessor solution / justification
              </label>
              <textarea
                className="border border-pfl-slate-300 rounded p-2 text-[13px] focus:outline-none focus:border-pfl-blue-500 bg-white"
                rows={3}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Describe the solution, re-upload path, or justification"
              />
              <button
                type="button"
                className="self-start rounded bg-pfl-slate-900 text-white px-3 py-1.5 text-[11px] uppercase tracking-wider font-semibold hover:bg-pfl-slate-800 disabled:opacity-40"
                disabled={busy || note.trim().length < 4}
                onClick={handleResolve}
              >
                {busy ? 'Submitting…' : 'Submit resolution'}
              </button>
            </div>
          )}
          {canMDAct && (
            <div className="flex flex-col gap-2 border-t border-pfl-slate-200 pt-3">
              <label className="text-[11px] uppercase tracking-wider text-pfl-slate-600 font-semibold">
                MD decision
              </label>
              <div className="flex gap-4 text-[13px]">
                <label className="inline-flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="radio"
                    className="accent-emerald-600"
                    checked={decision === 'MD_APPROVED'}
                    onChange={() => setDecision('MD_APPROVED')}
                  />
                  Approve (override)
                </label>
                <label className="inline-flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="radio"
                    className="accent-red-600"
                    checked={decision === 'MD_REJECTED'}
                    onChange={() => setDecision('MD_REJECTED')}
                  />
                  Reject (uphold)
                </label>
              </div>
              <textarea
                className="border border-pfl-slate-300 rounded p-2 text-[13px] focus:outline-none focus:border-pfl-blue-500 bg-white"
                rows={2}
                value={rationale}
                onChange={(e) => setRationale(e.target.value)}
                placeholder="MD rationale"
              />
              <button
                type="button"
                className={cn(
                  'self-start rounded px-3 py-1.5 text-[11px] uppercase tracking-wider font-semibold text-white disabled:opacity-40',
                  decision === 'MD_APPROVED'
                    ? 'bg-emerald-700 hover:bg-emerald-800'
                    : 'bg-red-700 hover:bg-red-800',
                )}
                disabled={busy || rationale.trim().length < 4}
                onClick={handleDecide}
              >
                {busy
                  ? 'Submitting…'
                  : decision === 'MD_APPROVED'
                  ? 'Record approval'
                  : 'Record rejection'}
              </button>
            </div>
          )}
          {err && <div className="text-[12px] text-red-700">{err}</div>}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Level card
// ---------------------------------------------------------------------------

function summaryLabelForStatus(
  status: VerificationLevelStatus | undefined,
  critCount: number,
  warnCount: number,
  errorMessage: string | null | undefined,
): { label: string; tone: 'pass' | 'fail' | 'warn' | 'info' } {
  // FAILED = the engine itself errored (exception, network, parse). Surface
  // the reason so the user can distinguish a broken run from a run that
  // merely found issues to triage.
  if (status === 'FAILED') {
    const reason = errorMessage ? ` · ${errorMessage.slice(0, 80)}` : ''
    return { label: `PROCESS FAILED${reason}`, tone: 'fail' }
  }
  if (status === 'RUNNING') return { label: 'RUNNING', tone: 'info' }
  if (status === 'PASSED') return { label: 'PASS', tone: 'pass' }
  if (status === 'PASSED_WITH_MD_OVERRIDE')
    return { label: 'PASS · MD OVERRIDE', tone: 'pass' }
  // BLOCKED means the engine succeeded but raised concerns that require
  // adjudication — label by count, not "FAIL".
  const total = critCount + warnCount
  if (critCount > 0 && warnCount > 0) {
    return {
      label: `${total} ISSUE${total > 1 ? 'S' : ''} · ${critCount} critical · ${warnCount} warning`,
      tone: 'fail',
    }
  }
  if (critCount > 0) {
    return {
      label: `${critCount} CRITICAL ISSUE${critCount > 1 ? 'S' : ''}`,
      tone: 'fail',
    }
  }
  if (warnCount > 0) {
    return {
      label: `${warnCount} WARNING${warnCount > 1 ? 'S' : ''}`,
      tone: 'warn',
    }
  }
  if (status === 'BLOCKED') {
    // Unusual — BLOCKED with zero unresolved issues means everything has been
    // settled but the engine hasn't re-evaluated. Treat as a pending check.
    return { label: 'AWAITING RE-EVAL', tone: 'info' }
  }
  return { label: 'NOT RUN', tone: 'info' }
}

// ---------------------------------------------------------------------------
// Rule-vs-issue reconciliation — drives the right-hand "Logic checks" column.
// ---------------------------------------------------------------------------

type RuleState = {
  entry: RuleCatalogEntry
  /** issue.status mapped to a high-level verdict */
  verdict: 'pass' | 'warn' | 'fail' | 'overridden' | 'na'
  issue: LevelIssueRead | null
  /** When verdict==='na', the reason supplied by the rule's skipIf predicate */
  naReason?: string
}

function reconcileRules(
  catalog: RuleCatalogEntry[],
  issues: LevelIssueRead[],
  sub: Record<string, unknown> = {},
): { rules: RuleState[]; extraIssues: LevelIssueRead[] } {
  const byStep = new Map<string, LevelIssueRead[]>()
  for (const i of issues) {
    const arr = byStep.get(i.sub_step_id) ?? []
    arr.push(i)
    byStep.set(i.sub_step_id, arr)
  }

  const rules: RuleState[] = catalog.map((entry) => {
    // skipIf lets a rule declare itself N/A based on the current run's data
    // (e.g. hide cattle_health for a service business).
    const naReason = entry.skipIf ? entry.skipIf(sub) : null
    if (naReason) {
      // Suppress any orphan issue rows that would otherwise fire — they stay
      // accessible in the raw issue list if needed, but won't surface as a
      // logic-check row.
      byStep.delete(entry.sub_step_id)
      return { entry, verdict: 'na', issue: null, naReason }
    }

    const bucket = byStep.get(entry.sub_step_id) ?? []
    byStep.delete(entry.sub_step_id)
    // Pick the worst unresolved issue — if all are MD-settled, treat as
    // overridden (passed-with-override); otherwise classify by severity.
    const unsettled = bucket.filter(
      (i) => i.status === 'OPEN' || i.status === 'ASSESSOR_RESOLVED',
    )
    const settled = bucket.filter(
      (i) => i.status === 'MD_APPROVED' || i.status === 'MD_REJECTED',
    )
    if (unsettled.length > 0) {
      const critical = unsettled.find((i) => i.severity === 'CRITICAL')
      const warn = unsettled.find((i) => i.severity === 'WARNING')
      return {
        entry,
        verdict: critical ? 'fail' : warn ? 'warn' : 'warn',
        issue: critical || warn || unsettled[0],
      }
    }
    if (settled.length > 0) {
      // MD_APPROVED = pass with override; MD_REJECTED = still a fail.
      const approved = settled.find((i) => i.status === 'MD_APPROVED')
      const rejected = settled.find((i) => i.status === 'MD_REJECTED')
      return {
        entry,
        verdict: rejected ? 'fail' : 'overridden',
        issue: rejected || approved || settled[0],
      }
    }
    return { entry, verdict: 'pass', issue: null }
  })

  // Issues emitted by the engine that weren't in the catalog (runtime
  // failures like ``ca_analyzer_failed``) still need to be shown.
  const extraIssues: LevelIssueRead[] = []
  for (const bucket of byStep.values()) extraIssues.push(...bucket)

  return { rules, extraIssues }
}

// ---------------------------------------------------------------------------
// Issues strip — hoists every unresolved rule issue + runtime (non-catalog)
// issue out of the logic-checks column into a full-width list above the
// passing rules / extraction details. Renders nothing when the level has no
// concerns to surface.
// ---------------------------------------------------------------------------

function IssuesStrip({
  rules,
  extraIssues,
  isMD,
  caseId,
  levelNumber,
  onResolve,
  onDecide,
}: {
  rules: RuleState[]
  extraIssues: LevelIssueRead[]
  isMD: boolean
  caseId: string
  levelNumber: VerificationLevelNumber
  onResolve: (id: string, note: string) => Promise<void>
  onDecide: (id: string, d: 'MD_APPROVED' | 'MD_REJECTED', r: string) => Promise<void>
}) {
  // Every catalog rule that has an active (or MD-settled) issue worth
  // surfacing — excludes rules that passed cleanly or were marked N/A.
  const issueRules = rules.filter(
    (r) => r.issue !== null && r.verdict !== 'na' && r.verdict !== 'pass',
  )

  if (issueRules.length === 0 && extraIssues.length === 0) {
    return null
  }

  const criticalCount = issueRules.filter((r) => r.verdict === 'fail').length
  const warningCount = issueRules.filter((r) => r.verdict === 'warn').length
  const overriddenCount = issueRules.filter((r) => r.verdict === 'overridden').length

  return (
    <div className="border border-red-100 bg-red-50/30 rounded-md">
      <div className="px-3 py-2 border-b border-red-100 flex items-center gap-2 flex-wrap">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-red-800">
          Concerns
        </span>
        <span className="text-red-300">·</span>
        <span className="text-[11.5px] text-pfl-slate-700">
          {criticalCount > 0 && (
            <span className="font-semibold text-red-700 mr-2">
              {criticalCount} critical
            </span>
          )}
          {warningCount > 0 && (
            <span className="font-semibold text-amber-700 mr-2">
              {warningCount} warning
            </span>
          )}
          {extraIssues.length > 0 && (
            <span className="font-semibold text-red-700 mr-2">
              {extraIssues.length} runtime
            </span>
          )}
          {overriddenCount > 0 && (
            <span className="text-indigo-700">
              {overriddenCount} MD-overridden
            </span>
          )}
        </span>
      </div>
      <div className="divide-y divide-red-100/60">
        {issueRules.map((r) => (
          <div key={r.entry.sub_step_id} className="px-3 py-1 bg-white">
            <IssueRow
              issue={r.issue as LevelIssueRead}
              ruleTitle={r.entry.title}
              isMD={isMD}
              caseId={caseId}
              levelNumber={levelNumber}
              onResolve={onResolve}
              onDecide={onDecide}
            />
          </div>
        ))}
        {extraIssues.map((i) => (
          <div key={i.id} className="px-3 py-1 bg-white">
            <IssueRow
              issue={i}
              ruleTitle={null}
              isMD={isMD}
              caseId={caseId}
              levelNumber={levelNumber}
              onResolve={onResolve}
              onDecide={onDecide}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Passing rules — the quiet list of catalog rules that either passed or were
// MD-overridden. Collapsed into a pill by default so the operator's attention
// stays on the concerns above.
// ---------------------------------------------------------------------------

function PassingRulesPanel({
  rules,
  isMD,
  caseId,
  levelNumber,
  onResolve,
  onDecide,
  passEvidenceByRule,
}: {
  rules: RuleState[]
  isMD: boolean
  caseId: string
  levelNumber: VerificationLevelNumber
  onResolve: (id: string, note: string) => Promise<void>
  onDecide: (id: string, d: 'MD_APPROVED' | 'MD_REJECTED', r: string) => Promise<void>
  /** Pass-evidence dicts keyed by sub_step_id. Threaded through to
   *  LogicCheckRow so each row can render its raw JSON in the expanded
   *  body (Task 14 will replace this with the per-rule dispatcher). */
  passEvidenceByRule?: Record<string, Record<string, unknown>>
}) {
  const [expanded, setExpanded] = useState(false)
  const passing = rules.filter((r) => r.verdict === 'pass')
  const overridden = rules.filter((r) => r.verdict === 'overridden')
  const na = rules.filter((r) => r.verdict === 'na')
  const total = passing.length + overridden.length + na.length
  if (total === 0) return null

  const summary = [
    passing.length > 0 && `${passing.length} pass`,
    overridden.length > 0 && `${overridden.length} MD-overridden`,
    na.length > 0 && `${na.length} n/a`,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className="border border-emerald-100 bg-emerald-50/30 rounded-md">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full px-3 py-2 flex items-center gap-2 text-left hover:bg-emerald-50/60"
        aria-expanded={expanded}
      >
        <span className="text-emerald-600">✓</span>
        <span className="text-[11px] font-semibold uppercase tracking-wider text-emerald-800">
          Passing rules
        </span>
        <span className="text-emerald-300">·</span>
        <span className="text-[11.5px] text-pfl-slate-700">{summary}</span>
        {!expanded && passing.length > 0 && (
          <span className="text-[11.5px] text-pfl-slate-500 ml-2 truncate">
            ·{' '}
            {passing
              .slice(0, 4)
              .map((r) => r.entry.title)
              .join(' · ')}
            {passing.length > 4 && ` · +${passing.length - 4} more`}
          </span>
        )}
        <span className="ml-auto text-pfl-slate-500 text-[11px]">
          {expanded ? '▴ hide' : '▾ show'}
        </span>
      </button>
      {expanded && (
        <div className="px-3 pb-3 pt-1 flex flex-col gap-1.5">
          {[...passing, ...overridden, ...na].map((r) => (
            <LogicCheckRow
              key={r.entry.sub_step_id}
              state={r}
              isMD={isMD}
              caseId={caseId}
              levelNumber={levelNumber}
              onResolve={onResolve}
              onDecide={onDecide}
              passEvidence={passEvidenceByRule?.[r.entry.sub_step_id]}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Extraction details — wraps the legacy EvidenceGatheredSection in a
// collapsed pill so the MD only sees the per-field scanner output on demand.
// ---------------------------------------------------------------------------

function ExtractionDetailsPanel({
  params,
  children,
}: {
  params: Param[]
  children?: React.ReactNode
}) {
  const [expanded, setExpanded] = useState(false)
  const counts = { pass: 0, warn: 0, fail: 0, info: 0 }
  for (const p of params) counts[p.verdict] = (counts[p.verdict] ?? 0) + 1

  if (params.length === 0) return null

  return (
    <div className="border border-pfl-slate-200 bg-pfl-slate-50/40 rounded-md">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full px-3 py-2 flex items-center gap-2 text-left hover:bg-pfl-slate-50"
        aria-expanded={expanded}
      >
        <span className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-600">
          Extraction details
        </span>
        <span className="text-pfl-slate-300">·</span>
        <span className="text-[11.5px] text-pfl-slate-600">
          {params.length} check{params.length === 1 ? '' : 's'}
          {counts.pass > 0 && (
            <> · <span className="text-emerald-700">{counts.pass} pass</span></>
          )}
          {counts.warn > 0 && (
            <> · <span className="text-amber-700">{counts.warn} warn</span></>
          )}
          {counts.fail > 0 && (
            <> · <span className="text-red-700">{counts.fail} fail</span></>
          )}
        </span>
        <span className="ml-auto text-pfl-slate-500 text-[11px]">
          {expanded ? '▴ hide' : '▾ show'}
        </span>
      </button>
      {expanded && (
        <div className="px-3 pb-3 pt-1">
          <div className="border border-pfl-slate-200 rounded bg-white">
            {params.map((p, i) => (
              <ParamRow key={i} param={p} />
            ))}
          </div>
          {children}
        </div>
      )}
    </div>
  )
}

function LogicChecksColumn({
  rules,
  extraIssues,
  isMD,
  caseId,
  levelNumber,
  onResolve,
  onDecide,
}: {
  rules: RuleState[]
  extraIssues: LevelIssueRead[]
  isMD: boolean
  caseId: string
  levelNumber: VerificationLevelNumber
  onResolve: (id: string, note: string) => Promise<void>
  onDecide: (
    id: string,
    d: 'MD_APPROVED' | 'MD_REJECTED',
    r: string,
  ) => Promise<void>
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {rules.map((r) => (
        <LogicCheckRow
          key={r.entry.sub_step_id}
          state={r}
          isMD={isMD}
          caseId={caseId}
          levelNumber={levelNumber}
          onResolve={onResolve}
          onDecide={onDecide}
        />
      ))}
      {extraIssues.length > 0 && (
        <div className="mt-2 pt-2 border-t border-pfl-slate-100">
          <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
            Runtime issues
          </div>
          {extraIssues.map((i) => (
            <IssueRow
              key={i.id}
              issue={i}
              isMD={isMD}
              caseId={caseId}
              levelNumber={levelNumber}
              onResolve={onResolve}
              onDecide={onDecide}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function LogicCheckRow({
  state,
  isMD,
  caseId,
  levelNumber,
  onResolve,
  onDecide,
  passEvidence,
}: {
  state: RuleState
  isMD: boolean
  caseId: string
  levelNumber: VerificationLevelNumber
  onResolve: (id: string, note: string) => Promise<void>
  onDecide: (
    id: string,
    d: 'MD_APPROVED' | 'MD_REJECTED',
    r: string,
  ) => Promise<void>
  /** Raw pass-evidence dict for this rule's sub_step_id. Rendered as
   *  JSON in the expanded body for now — Task 14 will replace this
   *  with a per-rule dispatcher / typed cards. */
  passEvidence?: Record<string, unknown>
}) {
  const { entry, verdict, issue, naReason } = state
  const [open, setOpen] = useState(false)
  const tickVerdict: Verdict =
    verdict === 'pass'
      ? 'pass'
      : verdict === 'warn'
      ? 'warn'
      : verdict === 'overridden'
      ? 'info'
      : verdict === 'na'
      ? 'info'
      : 'fail'

  const rowClass = cn(
    'rounded border px-3 py-2 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pfl-blue-600',
    verdict === 'pass' && 'border-emerald-100 bg-emerald-50/30 hover:bg-emerald-50/60',
    verdict === 'warn' && 'border-amber-200 bg-amber-50/50 hover:bg-amber-50/70',
    verdict === 'fail' && 'border-red-200 bg-red-50/60 hover:bg-red-50/80',
    verdict === 'overridden' && 'border-indigo-200 bg-indigo-50/40 hover:bg-indigo-50/60',
    verdict === 'na' && 'border-pfl-slate-200 bg-pfl-slate-50/40 opacity-70 hover:opacity-90',
  )

  return (
    <div
      className={rowClass}
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
    >
      <div className="flex items-start gap-2">
        <span
          className="text-pfl-slate-400 text-[11px] mt-[3px] select-none"
          aria-hidden
        >
          {open ? '▾' : '▸'}
        </span>
        <Tick verdict={tickVerdict} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={cn(
                'text-[12.5px] font-semibold text-pfl-slate-900',
                verdict === 'na' && 'line-through text-pfl-slate-500',
              )}
            >
              {entry.title}
            </span>
            {verdict === 'pass' && (
              <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-700">
                pass
              </span>
            )}
            {verdict === 'warn' && (
              <span className="text-[10px] font-semibold uppercase tracking-wider text-amber-700">
                warning
              </span>
            )}
            {verdict === 'fail' && (
              <span className="text-[10px] font-semibold uppercase tracking-wider text-red-700">
                critical
              </span>
            )}
            {verdict === 'overridden' && (
              <span className="text-[10px] font-semibold uppercase tracking-wider text-indigo-700">
                MD overridden
              </span>
            )}
            {verdict === 'na' && (
              <span className="text-[10px] font-semibold uppercase tracking-wider text-pfl-slate-500">
                n/a
              </span>
            )}
          </div>
          <div className="text-[11.5px] text-pfl-slate-600 mt-0.5 leading-snug">
            {verdict === 'na' && naReason
              ? `Skipped — ${naReason}. Does not count toward the match %.`
              : entry.description}
          </div>
        </div>
      </div>
      {issue && verdict !== 'pass' && verdict !== 'na' && (
        // IssueRow contains its own MD-approve / resolve buttons —
        // stop click/keyboard propagation so those inner controls
        // don't accidentally toggle the outer expand state.
        <div
          className="mt-2 pt-2 border-t border-pfl-slate-200/60"
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        >
          <IssueRow
            issue={issue}
            isMD={isMD}
            caseId={caseId}
            levelNumber={levelNumber}
            onResolve={onResolve}
            onDecide={onDecide}
          />
        </div>
      )}
      {open && (
        <div className="mt-2 ml-6 mr-1 text-[12px]">
          {(() => {
            // Case A: pass_evidence has an entry with skipped_reason
            if (
              passEvidence &&
              typeof passEvidence === 'object' &&
              'skipped_reason' in (passEvidence as Record<string, unknown>) &&
              Object.keys(passEvidence as Record<string, unknown>).length === 1
            ) {
              return (
                <div className="text-pfl-slate-500 italic">
                  Skipped — {String((passEvidence as Record<string, unknown>).skipped_reason)}.
                </div>
              )
            }
            // Case B: pass_evidence has a real payload
            if (passEvidence) {
              return (
                <PassDetailDispatcher
                  subStepId={state.entry.sub_step_id}
                  evidence={passEvidence}
                  caseId={caseId}
                />
              )
            }
            // Case C: no pass_evidence entry at all (truly unknown — happens
            // for legacy extractions that predate the build_pass_evidence
            // helpers)
            return (
              <div className="text-pfl-slate-500 italic">
                No additional pass-detail available for this rule.
              </div>
            )
          })()}
        </div>
      )}
    </div>
  )
}

function LevelCard({
  caseId,
  level,
  isMD,
  expanded,
  onToggle,
}: {
  caseId: string
  level: VerificationLevelNumber
  isMD: boolean
  expanded: boolean
  onToggle: () => void
}) {
  const { data, isLoading, error, mutate } = useVerificationLevelDetail(caseId, level)
  const { mutate: mutateOverview } = useVerificationOverview(caseId)
  const meta = LEVEL_META[level]
  const catalog = RULE_CATALOG[level]
  const is404 = !!error && (error as { status?: number } | null)?.status === 404

  // When the assessor writes a justification or the MD adjudicates, refresh
  // the level detail + overview AND the two role-queue caches so the
  // sidebar badges and the Assessor Queue / MD Approvals pages adjust
  // immediately instead of waiting for SWR's focus-throttle window.
  async function handleResolve(id: string, note: string) {
    await casesApi.verificationResolveIssue(id, note)
    await Promise.all([
      mutate(),
      mutateOverview(),
      globalMutate(['verification-assessor-queue']),
      globalMutate(['verification-md-queue']),
    ])
  }
  async function handleDecide(
    id: string,
    decision: 'MD_APPROVED' | 'MD_REJECTED',
    rationale: string,
  ) {
    await casesApi.verificationDecideIssue(id, decision, rationale)
    await Promise.all([
      mutate(),
      mutateOverview(),
      globalMutate(['verification-assessor-queue']),
      globalMutate(['verification-md-queue']),
    ])
  }

  const hasData = !!data && !error
  const params = hasData ? paramsForLevel(level, data.result) : []
  const reconciled = hasData
    ? reconcileRules(
        catalog,
        data.issues,
        (data.result.sub_step_results ?? {}) as Record<string, unknown>,
      )
    : { rules: [], extraIssues: [] }
  const rulesPass = reconciled.rules.filter((r) => r.verdict === 'pass').length
  const rulesWarn = reconciled.rules.filter((r) => r.verdict === 'warn').length
  const rulesFail = reconciled.rules.filter((r) => r.verdict === 'fail').length
  const rulesOverridden = reconciled.rules.filter(
    (r) => r.verdict === 'overridden',
  ).length
  const rulesNA = reconciled.rules.filter((r) => r.verdict === 'na').length
  // Denominator excludes N/A rules — they don't apply to this case.
  const evaluatedRules = reconciled.rules.length - rulesNA
  const totalRules = evaluatedRules || 1
  const matchPct = Math.round(
    ((rulesPass + rulesOverridden) / totalRules) * 100,
  )
  const unresolved = hasData
    ? data.issues.filter(
        (i) => i.status === 'OPEN' || i.status === 'ASSESSOR_RESOLVED',
      )
    : []
  const unresolvedCritical = unresolved.filter((i) => i.severity === 'CRITICAL')
  const unresolvedWarn = unresolved.filter((i) => i.severity === 'WARNING')
  const addressMismatch = hasData
    ? unresolvedCritical.find((i) => i.sub_step_id === 'gps_vs_aadhaar')
    : undefined
  const summary = summaryLabelForStatus(
    data?.result.status,
    unresolvedCritical.length,
    unresolvedWarn.length,
    data?.result.error_message,
  )
  const overallVerdict = statusToVerdict(data?.result.status)
  const blockedBy =
    unresolvedCritical.length > 0
      ? unresolvedCritical.map((i) => i.sub_step_id).join(', ')
      : ''

  const matchTone: 'pass' | 'warn' | 'fail' =
    matchPct >= 80 ? 'pass' : matchPct >= 50 ? 'warn' : 'fail'

  return (
    <div
      id={`level-${level}`}
      className="border border-pfl-slate-200 rounded-md bg-white overflow-hidden scroll-mt-4"
    >
      <button
        type="button"
        className="w-full text-left px-4 py-3 hover:bg-pfl-slate-50 flex items-center gap-3"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <Tick verdict={overallVerdict} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[14px] font-semibold text-pfl-slate-900">
              {meta.title}
            </span>
            <StatusPill label={summary.label} tone={summary.tone} />
            {hasData && (
              <MatchBadge pct={matchPct} tone={matchTone} />
            )}
            {addressMismatch && (
              <span
                className="inline-flex items-center gap-1 rounded-md border border-red-300 bg-red-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-red-700"
                title={addressMismatch.description}
              >
                <span aria-hidden>⚑</span> Address mismatch
              </span>
            )}
          </div>
          <div className="text-[11.5px] text-pfl-slate-500 mt-0.5 flex flex-wrap items-center gap-x-1 gap-y-0.5">
            <span>{meta.subtitle}</span>
            {hasData && (
              <>
                <span className="text-pfl-slate-300">·</span>
                {/* Extraction checklist summary (formerly the left-column
                    "Evidence gathered" header) lifted onto the header
                    strip so the operator sees coverage at a glance. */}
                <span>
                  <span className="font-mono">{params.length}</span>{' '}checks
                </span>
                {(() => {
                  const evPass = params.filter((p) => p.verdict === 'pass').length
                  const evWarn = params.filter((p) => p.verdict === 'warn').length
                  const evFail = params.filter((p) => p.verdict === 'fail').length
                  return (
                    <>
                      {evPass > 0 && (
                        <span className="text-emerald-700">
                          · <span className="font-mono">{evPass}</span> pass
                        </span>
                      )}
                      {evWarn > 0 && (
                        <span className="text-amber-700">
                          · <span className="font-mono">{evWarn}</span> warn
                        </span>
                      )}
                      {evFail > 0 && (
                        <span className="text-red-700">
                          · <span className="font-mono">{evFail}</span> fail
                        </span>
                      )}
                    </>
                  )
                })()}
                <span className="text-pfl-slate-300">·</span>
                {/* Concerns = unresolved LevelIssues. The raw count was
                    previously only shown as "N issue(s)" at the tail; we
                    pull it forward with colour coding so the operator
                    doesn't read green-coded "pass" counts next to an
                    unresolved-CRITICAL line. */}
                {data.issues.length === 0 ? (
                  <span className="text-emerald-700">
                    <span className="font-mono">0</span> concerns
                  </span>
                ) : (
                  <span
                    className={cn(
                      rulesFail > 0 ? 'text-red-700' : 'text-amber-700',
                    )}
                  >
                    <span className="font-mono">{data.issues.length}</span>{' '}
                    concern{data.issues.length === 1 ? '' : 's'}
                  </span>
                )}
                <span className="text-pfl-slate-300">·</span>
                <span className="font-mono">${data.result.cost_usd ?? '0.000000'}</span>
              </>
            )}
          </div>
        </div>
        <svg
          width="14"
          height="14"
          viewBox="0 0 16 16"
          className={cn(
            'text-pfl-slate-400 transition-transform shrink-0',
            expanded ? 'rotate-180' : '',
          )}
          aria-hidden
        >
          <path
            d="M4 6l4 4 4-4"
            stroke="currentColor"
            strokeWidth="2"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-pfl-slate-100">
          {isLoading && <Skeleton className="h-24 w-full mt-4" />}

          {is404 && (
            <div className="mt-4 text-[13px] italic text-pfl-slate-500">
              Not yet run. Use Start in the summary table above.
            </div>
          )}

          {!isLoading && error && !is404 && (
            <div className="mt-4 text-[13px] text-red-700">
              Failed to load detail.
            </div>
          )}

          {hasData && (
            <div className="pt-3 flex flex-col gap-3">
              {blockedBy && (
                <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-[12.5px] text-red-800">
                  <span className="font-semibold">Blocked by:</span> {blockedBy}.
                  Open the concern below to resolve or route to MD.
                </div>
              )}

              {/* L3 VISUAL-EVIDENCE HEADER — always-visible stock-analysis
                  card + photo gallery so the MD can eyeball stock numbers
                  + source photos on every L3 run without expanding a
                  concern. 55/45 split on xl+, stacked on narrow. */}
              {level === 'L3_VISION' && data.result.sub_step_results && (
                <div className="flex flex-col gap-3">
                  <div className="flex flex-col xl:flex-row gap-3">
                    <div className="xl:flex-[55]">
                      <L3StockAnalysisCard
                        analysis={
                          (data.result.sub_step_results as Record<string, unknown>)
                            .stock_analysis as L3StockAnalysis | null | undefined
                        }
                      />
                    </div>
                    <div className="xl:flex-[45]">
                      <L3PhotoGallery
                        caseId={caseId}
                        visualEvidence={
                          (data.result.sub_step_results as Record<string, unknown>)
                            .visual_evidence as L3VisualEvidence | null | undefined
                        }
                      />
                    </div>
                  </div>
                  {/* Per-item stock breakdown — Phase 2 */}
                  {(() => {
                    const items = (
                      (data.result.sub_step_results as Record<string, unknown> | undefined)
                        ?.stock_analysis as Record<string, unknown> | undefined
                    )?.items as L3ItemRow[] | undefined
                    return (
                      <L3PerItemTable
                        items={items}
                        caseId={caseId}
                        onAutoRefresh={async () => {
                          try {
                            await casesApi.verificationTrigger(caseId, 'L3_VISION')
                          } catch {
                            // 5-min concurrency guard may 409; ignore — the in-flight
                            // run will produce the new schema.
                          }
                          // Re-fetch L3 detail + overview so the new items array surfaces.
                          await globalMutate(['verification-level', caseId, 'L3_VISION'])
                          await globalMutate(['verification-overview', caseId])
                        }}
                      />
                    )
                  })()}
                </div>
              )}

              {/* L1.5 BUREAU WORST-CASE ROLL-UP — leads with a per-party
                  one-liner ("Applicant: 1 settled · 2 SMA · others clean")
                  so a credit officer triages the level in <2 seconds
                  before reading the 12 individual rule rows. */}
              {level === 'L1_5_CREDIT' && (
                <BureauWorstCaseStrip issues={data.issues} />
              )}

              {/* L5 SCORING OVERVIEW — grade + overall pct + EB verdict
                  + per-section bars at the top of the level body so a
                  reviewer reads the headline before walking the 32
                  rubric rows. */}
              {level === 'L5_SCORING' && (
                <L5ScoringOverviewStrip result={data.result} />
              )}

              {/* L5 32-RUBRIC TABLE — unified clickable table grouped
                  by section. Replaces the catalog/issue-strip split
                  for L5 only since the rubric IS the catalog. Each
                  row click expands to an EvidenceTwoColumn shell with
                  the resolver evidence + any cited source artefacts.
                  Suppressed rules render with strikethrough so the
                  audit trail stays visible. */}
              {level === 'L5_SCORING' && (
                <L5ScoringRubricTable
                  caseId={caseId}
                  result={data.result}
                  issues={data.issues}
                />
              )}

              {/* ISSUES STRIP — every unresolved concern hoisted to full
                  width so the MD sees the actionable list with the
                  resolve/decide controls. For L5 this lives BELOW the
                  rubric table so the at-a-glance audit comes first,
                  then the actionable resolution surface below. */}
              <IssuesStrip
                rules={reconciled.rules}
                extraIssues={reconciled.extraIssues}
                isMD={isMD}
                caseId={caseId}
                levelNumber={level}
                onResolve={handleResolve}
                onDecide={handleDecide}
              />

              {/* PASSING RULES — hidden for L5 since the unified rubric
                  table above already covers every pass row. Collapsed
                  pill on every other level. */}
              {level !== 'L5_SCORING' && (
                <PassingRulesPanel
                  rules={reconciled.rules}
                  isMD={isMD}
                  caseId={caseId}
                  levelNumber={level}
                  onResolve={handleResolve}
                  onDecide={handleDecide}
                  passEvidenceByRule={
                    (data.result.sub_step_results as
                      | Record<string, unknown>
                      | undefined)?.pass_evidence as
                      | Record<string, Record<string, unknown>>
                      | undefined
                  }
                />
              )}

              {/* EXTRACTION DETAILS — per-field scanner output wrapped
                  in the same pill treatment. Hidden for L5 since the
                  scoring overview + rubric table already cover the
                  parameter list. Level-specific findings (L2 / L3 /
                  L4) slot in underneath. */}
              {level !== 'L5_SCORING' && (
                <ExtractionDetailsPanel params={params}>
                  {level === 'L2_BANKING' && <L2Findings detail={data} />}
                  {level === 'L3_VISION' && <L3Findings detail={data} />}
                  {level === 'L4_AGREEMENT' && <L4Findings detail={data} />}
                </ExtractionDetailsPanel>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function MatchBadge({ pct, tone }: { pct: number; tone: 'pass' | 'warn' | 'fail' }) {
  const palette = {
    pass: 'bg-emerald-50 text-emerald-800 border-emerald-300',
    warn: 'bg-amber-50 text-amber-800 border-amber-300',
    fail: 'bg-red-50 text-red-800 border-red-300',
  }[tone]
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide',
        palette,
      )}
      title="Fraction of this level's logic checks that passed (including MD-overridden)."
    >
      {pct}% match
    </span>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export function VerificationPanel({
  caseId,
  isAdmin,
  currentStage,
}: {
  caseId: string
  isAdmin: boolean
  currentStage: CaseStage
}) {
  const { user } = useAuth()
  const isMD = user?.role === 'ceo' || user?.role === 'admin'
  const { data, error, isLoading, mutate } = useVerificationOverview(caseId)
  const { data: decision } = useDecisionResult(caseId)
  // CAM-discrepancy state powers the L6 row's "Blocked by N CAM
  // discrepancies" hint when the case is INGESTED but Phase 1 hasn't
  // started — matches the gating that ``start_phase1`` enforces server-
  // side, so the user gets the same "why" the auto-run modal would.
  const { data: discSummary } = useCamDiscrepancies(caseId, { refreshInterval: 0 })

  const [busy, setBusy] = useState<VerificationLevelNumber | null>(null)
  const [triggerErr, setTriggerErr] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Record<VerificationLevelNumber, boolean>>({
    L1_ADDRESS: true,
    L1_5_CREDIT: false,
    L2_BANKING: false,
    L3_VISION: false,
    L4_AGREEMENT: false,
    L5_SCORING: false,
    L5_5_DEDUPE_TVR: false,
  })
  const [l6Expanded, setL6Expanded] = useState(false)
  // The 7-Level Credit Pipeline summary table is a quick at-a-glance digest;
  // once the MD knows the shape of the case the big rows below are what they
  // actually work in. Collapsible so they can hide the digest and focus.
  const [summaryOpen, setSummaryOpen] = useState(true)

  async function handleTrigger(level: VerificationLevelNumber) {
    setBusy(level)
    setTriggerErr(null)
    try {
      await casesApi.verificationTrigger(caseId, level)
      await mutate()
    } catch (e: unknown) {
      setTriggerErr(e instanceof Error ? e.message : 'Trigger failed')
    } finally {
      setBusy(null)
    }
  }

  if (isLoading) return <Skeleton className="h-64 w-full" />
  if (error) {
    return (
      <div className="rounded border border-red-200 bg-red-50 p-3 text-[13px] text-red-700">
        Failed to load verification state.
      </div>
    )
  }

  const levelsByNum: Partial<Record<VerificationLevelNumber, VerificationResultRead>> =
    Object.fromEntries((data?.levels ?? []).map((l) => [l.level_number, l] as const))

  const gateOpen = !!data?.gate_open_for_phase_1
  const allExpanded = LEVELS.every((l) => expanded[l])

  return (
    <div className="flex flex-col gap-4">
      {/* Gate banner */}
      <div
        className={cn(
          'rounded-md border p-3 flex items-start gap-3',
          gateOpen
            ? 'border-emerald-200 bg-emerald-50'
            : 'border-amber-200 bg-amber-50',
        )}
      >
        <Tick verdict={gateOpen ? 'pass' : 'warn'} />
        <div className="flex-1">
          <div
            className={cn(
              'text-[13.5px] font-semibold',
              gateOpen ? 'text-emerald-800' : 'text-amber-900',
            )}
          >
            {gateOpen
              ? 'Gate OPEN — L6 Decisioning may proceed.'
              : 'Gate CLOSED — one or more levels are blocked or unresolved.'}
          </div>
          <div className="text-[11.5px] text-pfl-slate-600 mt-0.5">
            Gate opens when L1–L5 all resolve to PASSED or PASSED_WITH_MD_OVERRIDE.
            L6 · Decisioning runs against the gate-clean artifact set.
          </div>
        </div>
      </div>

      {/* Summary table — collapsible. The entire header row is the toggle,
          with a clear chevron affordance. "Expand all" stays a separate
          action and doesn't propagate its click up to the collapse. */}
      <div className="border border-pfl-slate-200 rounded-md bg-white">
        <div
          role="button"
          tabIndex={0}
          onClick={() => setSummaryOpen((v) => !v)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              setSummaryOpen((v) => !v)
            }
          }}
          aria-expanded={summaryOpen}
          className="flex items-center gap-3 px-4 py-2.5 border-b border-pfl-slate-100 cursor-pointer hover:bg-pfl-slate-50 select-none"
        >
          <span className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500 flex items-center gap-2">
            <span className="text-pfl-slate-600 text-[13px] leading-none">
              {summaryOpen ? '▾' : '▸'}
            </span>
            7-Level Credit Pipeline
          </span>
          {/* Quick per-row glance when the table is collapsed — so the MD
              doesn't have to expand the pipeline just to see shape. */}
          {!summaryOpen && (
            <span className="text-[11px] text-pfl-slate-500 ml-2 truncate">
              {LEVELS.map((n) => {
                const r = levelsByNum[n]
                const st = r?.status ?? 'PENDING'
                const mark =
                  st === 'PASSED' || st === 'PASSED_WITH_MD_OVERRIDE'
                    ? '✓'
                    : st === 'BLOCKED' || st === 'FAILED'
                    ? '✗'
                    : st === 'RUNNING'
                    ? '…'
                    : '·'
                // "L1 · Address" → "L1", "L1.5 · Credit" → "L1.5"
                const shortName = LEVEL_META[n].title.split(' · ')[0]
                return `${mark} ${shortName}`
              }).join(' · ')}
            </span>
          )}
          {summaryOpen && (
            <button
              type="button"
              className="ml-auto text-[11px] uppercase tracking-wider text-pfl-slate-500 hover:text-pfl-slate-900"
              onClick={(e) => {
                // Don't let "expand all" collapse the header it lives inside.
                e.stopPropagation()
                setExpanded(
                  Object.fromEntries(LEVELS.map((l) => [l, !allExpanded])) as Record<
                    VerificationLevelNumber,
                    boolean
                  >,
                )
              }}
            >
              {allExpanded ? 'collapse all' : 'expand all'}
            </button>
          )}
          {!summaryOpen && (
            <span className="ml-auto text-[11px] text-pfl-slate-400">
              click to expand
            </span>
          )}
        </div>
        {summaryOpen && (
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-[10.5px] uppercase tracking-wider text-pfl-slate-500">
                <th className="px-4 py-2 font-semibold w-10">#</th>
                <th className="px-2 py-2 font-semibold">Level</th>
                <th className="px-2 py-2 font-semibold">Status</th>
                <th className="px-2 py-2 font-semibold">Cost</th>
                <th className="px-2 py-2 font-semibold">Last run</th>
                <th className="px-4 py-2 font-semibold text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {LEVELS.map((n) => {
                const row = levelsByNum[n]
                const status = row?.status ?? 'PENDING'
                const verdict = statusToVerdict(status)
                const meta = LEVEL_META[n]
                const isRunning = busy === n || status === 'RUNNING'
                // Pull the per-run issue_count off sub_step_results so the
                // BLOCKED label names the actual number instead of a vague
                // "HAS ISSUES". Falls back to empty when pre-upgrade results
                // don't carry the key.
                const sub = (row?.sub_step_results ?? {}) as Record<string, unknown>
                const issueCount =
                  typeof sub.issue_count === 'number' ? (sub.issue_count as number) : 0
                const blockedLabel =
                  issueCount > 0
                    ? `${issueCount} ISSUE${issueCount === 1 ? '' : 'S'}`
                    : 'HAS ISSUES'
                return (
                  <tr
                    key={n}
                    className="border-t border-pfl-slate-100 hover:bg-pfl-slate-50"
                  >
                    <td className="px-4 py-2.5">
                      <Tick verdict={verdict} />
                    </td>
                    <td className="px-2 py-2.5">
                      <div className="font-semibold text-pfl-slate-900">{meta.title}</div>
                      <div className="text-[11px] text-pfl-slate-500">
                        {meta.subtitle}
                      </div>
                    </td>
                    <td className="px-2 py-2.5">
                      <StatusPill
                        label={
                          status === 'FAILED'
                            ? 'PROCESS FAILED'
                            : status === 'PASSED'
                            ? 'PASS'
                            : status === 'PASSED_WITH_MD_OVERRIDE'
                            ? 'PASS · MD'
                            : status === 'RUNNING'
                            ? 'RUNNING'
                            : status === 'BLOCKED'
                            ? blockedLabel
                            : 'NOT RUN'
                        }
                        tone={
                          verdict === 'pass'
                            ? 'pass'
                            : verdict === 'fail'
                            ? 'fail'
                            : verdict === 'warn'
                            ? 'warn'
                            : 'info'
                        }
                      />
                    </td>
                    <td className="px-2 py-2.5 font-mono text-[12px] text-pfl-slate-600 tabular-nums">
                      {row?.cost_usd ?? '—'}
                    </td>
                    <td className="px-2 py-2.5 text-[11.5px] text-pfl-slate-500">
                      {row?.completed_at
                        ? new Date(row.completed_at).toLocaleString()
                        : '—'}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        type="button"
                        className="rounded bg-pfl-slate-900 text-white px-3 py-1 text-[11px] uppercase tracking-wider font-semibold hover:bg-pfl-slate-800 disabled:opacity-40"
                        disabled={isRunning}
                        onClick={() => handleTrigger(n)}
                        data-testid={`trigger-${n}`}
                      >
                        {isRunning ? 'Running…' : row ? 'Re-run' : 'Start'}
                      </button>
                    </td>
                  </tr>
                )
              })}
              {/* L6 · Decisioning — synthesised in the frontend from the
                   existing Phase 1 DecisionResult record so the user sees the
                   whole credit pipeline on one table. L6 data comes from a
                   different backend path (DecisionResult, not
                   VerificationResult). */}
              {(() => {
                const dStatus = (decision?.status ?? 'NOT RUN') as string
                const dVerdict: 'pass' | 'warn' | 'fail' | 'info' =
                  dStatus === 'COMPLETED'
                    ? 'pass'
                    : dStatus === 'RUNNING' || dStatus === 'PENDING'
                    ? 'warn'
                    : dStatus === 'FAILED' || dStatus === 'CANCELLED'
                    ? 'fail'
                    : 'info'
                const label =
                  dStatus === 'COMPLETED'
                    ? 'COMPLETED'
                    : dStatus === 'RUNNING'
                    ? 'RUNNING'
                    : dStatus === 'FAILED'
                    ? 'PROCESS FAILED'
                    : dStatus === 'CANCELLED'
                    ? 'CANCELLED'
                    : dStatus === 'PENDING'
                    ? 'PENDING'
                    : 'NOT RUN'
                // Why-not-yet hint: when L6 hasn't started, surface the
                // SAME gate the backend's start_phase1 enforces, so the
                // operator sees the actionable reason inline instead of
                // having to dig into the auto-run modal or hover the Start
                // button. CAM discrepancies block first (server-side gate);
                // L1-L5 gate is the secondary precondition.
                const discBlocked = !!discSummary?.phase1_blocked
                const discCount = discSummary?.unresolved_critical ?? 0
                const blockingHint: string | null =
                  dStatus === 'NOT RUN'
                    ? discBlocked
                      ? `Blocked by ${discCount} CAM discrepanc${
                          discCount === 1 ? 'y' : 'ies'
                        } — resolve in the Discrepancies tab.`
                      : !gateOpen
                      ? 'Waiting for L1–L5 gate to open (one or more levels still BLOCKED).'
                      : null
                    : null
                return (
                  <tr className="border-t border-pfl-slate-100 hover:bg-pfl-slate-50">
                    <td className="px-4 py-2.5">
                      <Tick verdict={dVerdict} />
                    </td>
                    <td className="px-2 py-2.5">
                      <div className="font-semibold text-pfl-slate-900">
                        L6 · Decisioning
                      </div>
                      <div className="text-[11px] text-pfl-slate-500">
                        Post-gate 11-step synthesis (policy, income, KYC, reconciliation, Opus verdict)
                      </div>
                      {blockingHint && (
                        <div className="text-[11px] text-amber-800 font-medium mt-0.5">
                          {blockingHint}
                        </div>
                      )}
                    </td>
                    <td className="px-2 py-2.5">
                      <StatusPill
                        label={label}
                        tone={
                          dVerdict === 'pass'
                            ? 'pass'
                            : dVerdict === 'fail'
                            ? 'fail'
                            : dVerdict === 'warn'
                            ? 'warn'
                            : 'info'
                        }
                      />
                    </td>
                    <td className="px-2 py-2.5 font-mono text-[12px] text-pfl-slate-600 tabular-nums">
                      {decision?.total_cost_usd ?? '—'}
                    </td>
                    <td className="px-2 py-2.5 text-[11.5px] text-pfl-slate-500">
                      {decision?.completed_at
                        ? new Date(decision.completed_at).toLocaleString()
                        : '—'}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        type="button"
                        className="rounded bg-pfl-slate-900 text-white px-3 py-1 text-[11px] uppercase tracking-wider font-semibold hover:bg-pfl-slate-800 disabled:opacity-40"
                        onClick={() => setL6Expanded(true)}
                        data-testid="trigger-L6_DECISIONING"
                      >
                        Open
                      </button>
                    </td>
                  </tr>
                )
              })()}
            </tbody>
          </table>
        </div>
        )}
        {summaryOpen && triggerErr && (
          <div className="px-4 py-2 text-[12px] text-red-700 border-t border-red-200 bg-red-50">
            {triggerErr}
          </div>
        )}
      </div>

      {/* Per-level cards */}
      <div className="flex flex-col gap-3">
        {LEVELS.map((n) => (
          <LevelCard
            key={n}
            caseId={caseId}
            level={n}
            isMD={isMD}
            expanded={expanded[n]}
            onToggle={() =>
              setExpanded((prev) => ({ ...prev, [n]: !prev[n] }))
            }
          />
        ))}

        {/* L6 · Decisioning card — wraps the existing DecisioningPanel so the
            complete credit pipeline (L1 → L6) reads top-to-bottom on one
            tab. */}
        <div className="border border-pfl-slate-200 rounded-md bg-white overflow-hidden">
          <button
            type="button"
            className="w-full text-left px-4 py-3 hover:bg-pfl-slate-50 flex items-center gap-3"
            onClick={() => setL6Expanded((e) => !e)}
            aria-expanded={l6Expanded}
          >
            <Tick
              verdict={
                decision?.status === 'COMPLETED'
                  ? 'pass'
                  : decision?.status === 'FAILED' || decision?.status === 'CANCELLED'
                  ? 'fail'
                  : decision?.status === 'RUNNING' || decision?.status === 'PENDING'
                  ? 'warn'
                  : 'info'
              }
            />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[14px] font-semibold text-pfl-slate-900">
                  L6 · Decisioning
                </span>
                <StatusPill
                  label={
                    decision?.status === 'COMPLETED'
                      ? 'COMPLETED'
                      : decision?.status === 'RUNNING'
                      ? 'RUNNING'
                      : decision?.status === 'FAILED'
                      ? 'PROCESS FAILED'
                      : decision?.status === 'CANCELLED'
                      ? 'CANCELLED'
                      : decision?.status === 'PENDING'
                      ? 'PENDING'
                      : 'NOT RUN'
                  }
                  tone={
                    decision?.status === 'COMPLETED'
                      ? 'pass'
                      : decision?.status === 'FAILED' ||
                        decision?.status === 'CANCELLED'
                      ? 'fail'
                      : decision?.status === 'RUNNING' ||
                        decision?.status === 'PENDING'
                      ? 'warn'
                      : 'info'
                  }
                />
                {decision?.final_decision && (
                  <StatusPill
                    label={decision.final_decision}
                    tone={
                      decision.final_decision === 'APPROVE' ||
                      decision.final_decision === 'APPROVE_WITH_CONDITIONS'
                        ? 'pass'
                        : decision.final_decision === 'REJECT'
                        ? 'fail'
                        : 'warn'
                    }
                  />
                )}
              </div>
              <div className="text-[11.5px] text-pfl-slate-500 mt-0.5">
                Post-gate synthesis — policy gates, CA-analyser,
                reconciliation, Opus final verdict
                {decision?.total_cost_usd != null && (
                  <>
                    {' · '}
                    <span className="font-mono">${decision.total_cost_usd}</span>
                  </>
                )}
              </div>
            </div>
            <svg
              width="14"
              height="14"
              viewBox="0 0 16 16"
              className={cn(
                'text-pfl-slate-400 transition-transform shrink-0',
                l6Expanded ? 'rotate-180' : '',
              )}
              aria-hidden
            >
              <path
                d="M4 6l4 4 4-4"
                stroke="currentColor"
                strokeWidth="2"
                fill="none"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          {l6Expanded && (
            <div className="px-4 pb-4 pt-3 border-t border-pfl-slate-100">
              <DecisioningPanel
                caseId={caseId}
                currentStage={currentStage}
                isAdmin={isAdmin}
              />
            </div>
          )}
        </div>
      </div>

      <span className="hidden" aria-hidden>
        {isAdmin ? 'admin' : 'user'}
      </span>
    </div>
  )
}
