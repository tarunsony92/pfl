'use client'
/**
 * RationOwnerCard — `ration_owner_rule` (L1).
 *
 * Cross-checks "who owns the ration / electricity bill on file" against
 * the actual loan parties. The Aadhaar S/O field links applicant or
 * co-app to a paternal name; if the bill is in the father / husband's
 * name, the family-attribution is clean. Otherwise the case is blocked
 * until the actual owner is added as co-applicant or guarantor.
 *
 * Keys (fire + pass paths use the same shape — see
 * `build_pass_evidence_l1` in level_1_address.py:1183-1222):
 *   bill_owner, bill_father_or_husband, applicant_name,
 *   applicant_aadhaar_father, co_applicant_name, co_applicant_aadhaar_father,
 *   guarantor_names[], verdict.
 */

import { formatEvidenceValue } from './_format'

type LoanRole = 'applicant' | 'co_applicant' | 'guarantor' | 'not_on_loan'

const LOAN_ROLE_LABEL: Record<LoanRole, string> = {
  applicant: 'Applicant',
  co_applicant: 'Co-applicant',
  guarantor: 'Guarantor',
  not_on_loan: 'Not on the loan',
}

function BillOwnerRoleBadge({ role }: { role: LoanRole }) {
  // The screenshot case (bill owner ASOK KUMAR not on the loan, only
  // tolerated via first-name match against the applicant's father) is
  // exactly what made the lack of this signal confusing — the assessor
  // could not tell at a glance whether the bill owner was actually on
  // the loan as applicant / co-applicant / guarantor or just a relative.
  // Always render this row first.
  const onLoan = role !== 'not_on_loan'
  return (
    <div
      className={
        onLoan
          ? 'inline-flex w-fit items-center gap-1.5 rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-800'
          : 'inline-flex w-fit items-center gap-1.5 rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-800'
      }
    >
      <span aria-hidden="true">{onLoan ? '✓' : '!'}</span>
      <span className="uppercase tracking-wider text-[10px]">Role on loan</span>
      <span>·</span>
      <span>{LOAN_ROLE_LABEL[role]}</span>
    </div>
  )
}

export function RationOwnerCard({ evidence: ev }: { evidence: Record<string, unknown> }) {
  // Generic-surname tolerance: when the backend detected that the bill
  // owner shares a first name with a relative AND the bill surname is a
  // known caste-placeholder ("KUMAR", "DEVI", "SINGH"…), the issue was
  // emitted as a soft WARNING instead of a hard CRITICAL. Render an
  // explicit green callout so the assessor can see *why* the rule didn't
  // block the gate — and the standard Assessor-solution box below the
  // card is the toggle to escalate manually if they have ground truth
  // that this is a stranger.
  const tolerance = ev['generic_surname_tolerance'] as
    | { generic_surname?: string; first_name_matched_against?: string; matched_value?: string }
    | undefined
  const billOwnerRoleRaw = ev['bill_owner_loan_role']
  const billOwnerRole: LoanRole | null =
    billOwnerRoleRaw === 'applicant' ||
    billOwnerRoleRaw === 'co_applicant' ||
    billOwnerRoleRaw === 'guarantor' ||
    billOwnerRoleRaw === 'not_on_loan'
      ? billOwnerRoleRaw
      : null
  return (
    <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-2 text-[12px]">
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1.5">
        Bill vs loan parties
      </div>
      {billOwnerRole && (
        <div className="mb-2">
          <BillOwnerRoleBadge role={billOwnerRole} />
        </div>
      )}
      <div className="grid grid-cols-[max-content,1fr] gap-x-3 gap-y-1">
        <Row label="Bill owner" value={ev['bill_owner']} />
        {!!ev['bill_father_or_husband'] && (
          <Row label="Bill S/O · W/O" value={ev['bill_father_or_husband']} />
        )}
        <Row label="Applicant" value={ev['applicant_name']} />
        {!!ev['applicant_aadhaar_father'] && (
          <Row
            label="Applicant S/O · W/O (Aadhaar)"
            value={ev['applicant_aadhaar_father']}
          />
        )}
        {!!ev['co_applicant_name'] && (
          <Row label="Co-applicant" value={ev['co_applicant_name']} />
        )}
        {!!ev['co_applicant_aadhaar_father'] && (
          <Row
            label="Co-app S/O · W/O (Aadhaar)"
            value={ev['co_applicant_aadhaar_father']}
          />
        )}
        {Array.isArray(ev['guarantor_names']) &&
          (ev['guarantor_names'] as unknown[]).length > 0 && (
            <Row label="Guarantors" value={ev['guarantor_names']} />
          )}
        {!!ev['verdict'] && <Row label="Verdict" value={ev['verdict']} />}
      </div>
      {tolerance?.generic_surname && (
        <div className="mt-2 rounded border border-emerald-300 bg-emerald-50 px-2 py-1.5 text-[11.5px] leading-snug text-emerald-900">
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className="text-[14px]" aria-hidden="true">
              ✓
            </span>
            <span className="font-semibold uppercase tracking-wider text-[10px] text-emerald-800">
              Generic-surname tolerance applied
            </span>
          </div>
          <div>
            Bill owner&apos;s first name matches{' '}
            <span className="font-semibold">
              {tolerance.matched_value ?? '—'}
            </span>{' '}
            ({prettyRelation(tolerance.first_name_matched_against)}); surname{' '}
            <span className="font-mono uppercase">
              {tolerance.generic_surname}
            </span>{' '}
            is a placeholder commonly used in Indian utility-bill data-entry
            to mask caste. Address attribution treated as clean.
          </div>
          <div className="mt-1 text-[11px] text-emerald-800/80">
            Use the <span className="font-semibold">Assessor solution</span>{' '}
            box below to flip this back to a real concern if you have
            ground truth that this is a stranger, not a relative.
          </div>
        </div>
      )}
    </div>
  )
}

function prettyRelation(key: string | undefined): string {
  switch (key) {
    case 'applicant_name':
      return 'the applicant'
    case 'co_applicant_name':
      return 'the co-applicant'
    case 'applicant_aadhaar_father_name':
      return "applicant's father / guardian"
    case 'co_applicant_aadhaar_father_name':
      return "co-applicant's father / guardian"
    default:
      return 'a loan party'
  }
}

function Row({ label, value }: { label: string; value: unknown }) {
  return (
    <>
      <span className="font-medium text-pfl-slate-600">{label}</span>
      <span className="text-pfl-slate-900">{formatEvidenceValue(value)}</span>
    </>
  )
}
