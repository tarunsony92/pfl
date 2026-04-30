'use client'
/**
 * Single rule-id → smart-card map. Both the fire path
 * (IssueEvidencePanel inside VerificationPanel.tsx) and the pass path
 * (PassDetailDispatcher) consult this registry so a new card lights up
 * on both paths the moment it's registered. Replaces the duplicated
 * dispatch chain that used to live in both files.
 *
 * Each entry is a factory `(evidence) => { body, headline? }` returning
 * the LEFT-column content for an EvidenceTwoColumn wrapper. Returning
 * `null` (or the factory not being registered) makes the dispatcher
 * fall through to GenericEvidenceTable.
 */

import React from 'react'
import { AvgBalanceVsEmiCard } from './AvgBalanceVsEmiCard'
import { CommuteCard } from './CommuteCard'
import { BureauAccountRow } from './BureauAccountRow'
import { L3StockVsLoanPassCard } from '../l3/L3StockVsLoanPassCard'
import { L3InfraPassCard } from '../l3/L3InfraPassCard'
import { L3LoanRecPassCard } from '../l3/L3LoanRecPassCard'
import type { L3StockAnalysis } from '@/lib/types'
import { GpsVsAadhaarCard, gpsVsAadhaarHeadline } from './GpsVsAadhaarCard'
import { RationOwnerCard } from './RationOwnerCard'
import { AddressMatchCard, addressMatchHeadline } from './AddressMatchCard'
import { BusinessGpsCard, businessGpsHeadline } from './BusinessGpsCard'
import {
  CreditScoreFloorCard,
  creditScoreFloorHeadline,
} from './CreditScoreFloorCard'
import {
  BureauReportMissingCard,
  bureauReportMissingHeadline,
} from './BureauReportMissingCard'
import { OpusCreditVerdictCard } from './OpusCreditVerdictCard'
import { BankStatementMissingCard } from './BankStatementMissingCard'
import { BankStatementMonthsCoverageCard } from './BankStatementMonthsCoverageCard'
import { NachBouncesCard, nachBouncesHeadline } from './NachBouncesCard'
import {
  CreditsVsIncomeCard,
  creditsVsIncomeHeadline,
} from './CreditsVsIncomeCard'
import { SinglePayerConcentrationCard } from './SinglePayerConcentrationCard'
import {
  ImpulsiveDebitCard,
  impulsiveDebitHeadline,
} from './ImpulsiveDebitCard'
import { ChronicLowBalanceCard } from './ChronicLowBalanceCard'
import { CaNarrativeCard, caNarrativeHeadline } from './CaNarrativeCard'
import { LoanAgreementMissingCard } from './LoanAgreementMissingCard'
import {
  AnnexurePresenceCard,
  annexurePresenceHeadline,
} from './AnnexurePresenceCard'
import { HypothecationClauseCard } from './HypothecationClauseCard'
import {
  AssetAnnexureCard,
  assetAnnexureHeadline,
} from './AssetAnnexureCard'
import { DedupeMatchesCard, dedupeMatchesHeadline } from './DedupeMatchesCard'
import { PdcBankMatchCard, pdcBankMatchHeadline } from './PdcBankMatchCard'
import { TvrPresenceCard, tvrPresenceHeadline } from './TvrPresenceCard'

// ---------------------------------------------------------------------------
// Bureau-account rule set — kept here so the L1.5 worst-case strip and
// both dispatchers consult one source of truth.
// ---------------------------------------------------------------------------

export const BUREAU_ACCOUNT_RULE_IDS: ReadonlySet<string> = new Set([
  'credit_write_off',
  'credit_loss',
  'credit_settled',
  'credit_substandard',
  'credit_doubtful',
  'credit_sma',
  'coapp_credit_write_off',
  'coapp_credit_loss',
  'coapp_credit_settled',
  'coapp_credit_substandard',
  'coapp_credit_doubtful',
  'coapp_credit_sma',
])

export function isBureauAccountRule(subStepId: string): boolean {
  return BUREAU_ACCOUNT_RULE_IDS.has(subStepId)
}

// ---------------------------------------------------------------------------
// Card factory contract
// ---------------------------------------------------------------------------

export type CardOutput = {
  /** The LEFT-column body for the EvidenceTwoColumn wrapper. */
  body: React.ReactNode
  /** Optional 1-line eyebrow rendered at the top-right of the header
   *  ("28 km between addresses", "ratio 1.4×"). Surfaces the headline
   *  fact the row's verdict turns on without forcing the user to
   *  expand. */
  headline?: string
}

export type CardFactory = (
  ev: Record<string, unknown>,
) => CardOutput | null

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

const REGISTRY: Record<string, CardFactory> = {
  // ─── L1 ────────────────────────────────────────────────────────────────
  gps_vs_aadhaar: (ev) => ({
    body: React.createElement(GpsVsAadhaarCard, { evidence: ev }),
    headline: gpsVsAadhaarHeadline(ev),
  }),
  house_business_commute: (ev) => ({
    body: React.createElement(CommuteCard, { evidence: ev }),
  }),
  ration_owner_rule: (ev) => ({
    body: React.createElement(RationOwnerCard, { evidence: ev }),
  }),
  business_visit_gps: (ev) => ({
    body: React.createElement(BusinessGpsCard, { evidence: ev }),
    headline: businessGpsHeadline(ev),
  }),
  applicant_coapp_address_match: (ev) => ({
    body: React.createElement(AddressMatchCard, {
      evidence: ev,
      subStepId: 'applicant_coapp_address_match',
    }),
    headline: addressMatchHeadline(ev),
  }),
  aadhaar_vs_bureau_address: (ev) => ({
    body: React.createElement(AddressMatchCard, {
      evidence: ev,
      subStepId: 'aadhaar_vs_bureau_address',
    }),
    headline: addressMatchHeadline(ev),
  }),
  aadhaar_vs_bank_address: (ev) => ({
    body: React.createElement(AddressMatchCard, {
      evidence: ev,
      subStepId: 'aadhaar_vs_bank_address',
    }),
    headline: addressMatchHeadline(ev),
  }),

  // ─── L1.5 ──────────────────────────────────────────────────────────────
  credit_score_floor: (ev) => ({
    body: React.createElement(CreditScoreFloorCard, { evidence: ev }),
    headline: creditScoreFloorHeadline(ev),
  }),
  coapp_credit_score_floor: (ev) => ({
    body: React.createElement(CreditScoreFloorCard, { evidence: ev }),
    headline: creditScoreFloorHeadline(ev),
  }),
  bureau_report_missing: (ev) => ({
    body: React.createElement(BureauReportMissingCard, { evidence: ev }),
    headline: bureauReportMissingHeadline(ev),
  }),
  opus_credit_verdict: (ev) => ({
    body: React.createElement(OpusCreditVerdictCard, { evidence: ev }),
  }),

  // ─── L2 ────────────────────────────────────────────────────────────────
  avg_balance_vs_emi: (ev) => ({
    body: React.createElement(AvgBalanceVsEmiCard, { evidence: ev }),
  }),
  bank_statement_missing: (ev) => ({
    body: React.createElement(BankStatementMissingCard, { evidence: ev }),
  }),
  bank_statement_months_coverage: (ev) => {
    const available = ev['available_months']
    const required = ev['required_months']
    const headline =
      typeof available === 'number' && typeof required === 'number'
        ? `${available.toFixed(1)} / ${required.toFixed(0)} months`
        : undefined
    return {
      body: React.createElement(BankStatementMonthsCoverageCard, {
        evidence: ev,
      }),
      headline,
    }
  },
  nach_bounces: (ev) => ({
    body: React.createElement(NachBouncesCard, { evidence: ev }),
    headline: nachBouncesHeadline(ev),
  }),
  credits_vs_declared_income: (ev) => ({
    body: React.createElement(CreditsVsIncomeCard, { evidence: ev }),
    headline: creditsVsIncomeHeadline(ev),
  }),
  single_payer_concentration: (ev) => ({
    body: React.createElement(SinglePayerConcentrationCard, { evidence: ev }),
  }),
  impulsive_debit_overspend: (ev) => ({
    body: React.createElement(ImpulsiveDebitCard, { evidence: ev }),
    headline: impulsiveDebitHeadline(ev),
  }),
  chronic_low_balance: (ev) => ({
    body: React.createElement(ChronicLowBalanceCard, { evidence: ev }),
  }),
  ca_narrative_concerns: (ev) => ({
    body: React.createElement(CaNarrativeCard, { evidence: ev }),
    headline: caNarrativeHeadline(ev),
  }),

  // ─── L4 ────────────────────────────────────────────────────────────────
  loan_agreement_missing: (ev) => ({
    body: React.createElement(LoanAgreementMissingCard, { evidence: ev }),
  }),
  loan_agreement_annexure: (ev) => ({
    body: React.createElement(AnnexurePresenceCard, { evidence: ev }),
    headline: annexurePresenceHeadline(ev),
  }),
  hypothecation_clause: (ev) => ({
    body: React.createElement(HypothecationClauseCard, { evidence: ev }),
  }),
  asset_annexure_empty: (ev) => ({
    body: React.createElement(AssetAnnexureCard, { evidence: ev }),
    headline: assetAnnexureHeadline(ev),
  }),

  // ─── L5.5 ──────────────────────────────────────────────────────────────
  dedupe_clear: (ev) => ({
    body: React.createElement(DedupeMatchesCard, { evidence: ev }),
    headline: dedupeMatchesHeadline(ev),
  }),
  tvr_present: (ev) => ({
    body: React.createElement(TvrPresenceCard, { evidence: ev }),
    headline: tvrPresenceHeadline(ev),
  }),
  pdc_matches_bank: (ev) => ({
    body: React.createElement(PdcBankMatchCard, { evidence: ev }),
    headline: pdcBankMatchHeadline(ev),
  }),

  // ─── L3 ────────────────────────────────────────────────────────────────
  stock_vs_loan: (ev) => ({
    body: React.createElement(L3StockVsLoanPassCard, {
      evidence: ev as L3StockAnalysis & { photos_evaluated_count?: number },
    }),
  }),
  business_infrastructure: (ev) => ({
    body: React.createElement(L3InfraPassCard, { evidence: ev }),
  }),
  loan_amount_reduction: (ev) => ({
    body: React.createElement(L3LoanRecPassCard, { evidence: ev }),
  }),
  cattle_health: (ev) => {
    if ('skipped_reason' in ev) {
      return {
        body: React.createElement(
          'div',
          { className: 'text-[12px] text-pfl-slate-600 italic' },
          `Skipped — ${String(ev['skipped_reason'])}. Does not count toward the match %.`,
        ),
      }
    }
    return {
      body: React.createElement(
        'div',
        { className: 'text-[12px] text-pfl-slate-700' },
        `Cattle health rated `,
        React.createElement(
          'span',
          { className: 'font-semibold' },
          String(ev['cattle_health'] ?? '—'),
        ),
        ` across ${String(ev['cattle_count'] ?? '—')} animal(s).`,
      ),
    }
  },
  // `house_living_condition` is still a parked follow-up — render the
  // raw evidence as a fallback. Keeps L3 visually consistent with
  // pre-refactor behaviour until a proper ratings card lands.
  house_living_condition: (ev) => ({
    body: React.createElement(
      'pre',
      {
        className:
          'whitespace-pre-wrap text-pfl-slate-700 text-[11px] leading-snug font-mono',
      },
      JSON.stringify(ev, null, 2),
    ),
  }),
}

/** Dispatch a sub_step_id → card factory result. Returns null when no
 *  smart card is registered for the rule (caller falls through to the
 *  generic key/value table). Bureau-account rules are dispatched
 *  centrally because they share one card across 12 rule ids. */
export function lookupCard(
  subStepId: string,
  ev: Record<string, unknown>,
): CardOutput | null {
  if (isBureauAccountRule(subStepId)) {
    return { body: React.createElement(BureauAccountRow, { evidence: ev }) }
  }
  const factory = REGISTRY[subStepId]
  if (!factory) return null
  return factory(ev)
}
