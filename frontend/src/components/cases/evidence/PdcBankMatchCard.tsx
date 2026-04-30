'use client'
/**
 * PdcBankMatchCard — `pdc_matches_bank` (L5.5).
 *
 * Renders the PDC ↔ bank-statement cross-check details on the pass path.
 * Three states:
 *  - severity = 'pass'    → all comparable fields agreed (green tick rows)
 *  - severity = 'skipped' → cheque or statement missing fields, OR bank
 *                            extraction unavailable, OR PDC vision didn't
 *                            succeed. Render the *reason* and any partial
 *                            fields the orchestrator did capture.
 *  - severity = 'warning' / 'critical' fall through the fire path and never
 *    reach this card.
 *
 * Evidence shape comes from PDCMatchResult.to_evidence() in
 * pdc_verifier.py + the L5.5 orchestrator (level_5_5_dedupe_tvr.py).
 */

import { cn } from '@/lib/cn'

type Ev = {
  severity?: string
  skipped_reason?: string
  cheque_ifsc?: string | null
  statement_ifsc?: string | null
  cheque_account_tail?: string | null
  statement_account_tail?: string | null
  cheque_holder?: string | null
  statement_holder?: string | null
  name_similarity?: number
  filename?: string
}

const SKIPPED_REASON_LABEL: Record<string, string> = {
  bank_statement_extraction_unavailable:
    'Bank statement extraction was not available — IFSC and account-tail could not be cross-checked.',
  no_overlapping_fields:
    'Cheque and bank statement did not share any comparable fields (IFSC + account-tail were missing on at least one side).',
  pdc_vision_unavailable:
    'PDC vision read did not succeed (the cheque image was not recognised). Re-upload a clearer cheque so this rule can run.',
}

function ComparisonRow({
  label,
  cheque,
  statement,
  match,
}: {
  label: string
  cheque: string | null | undefined
  statement: string | null | undefined
  match: 'match' | 'mismatch' | 'partial'
}) {
  const Icon =
    match === 'match' ? '✓' : match === 'mismatch' ? '✗' : '·'
  const color = {
    match: 'text-emerald-600',
    mismatch: 'text-red-600',
    partial: 'text-pfl-slate-400',
  }[match]
  return (
    <div className="grid grid-cols-[110px_1fr_1fr_24px] gap-2 items-baseline text-[12px]">
      <div className="text-pfl-slate-500 uppercase tracking-wider text-[10px]">
        {label}
      </div>
      <div className="font-mono text-pfl-slate-700">
        {cheque ?? <span className="italic text-pfl-slate-400">—</span>}
      </div>
      <div className="font-mono text-pfl-slate-700">
        {statement ?? <span className="italic text-pfl-slate-400">—</span>}
      </div>
      <div className={cn('font-bold text-right', color)}>{Icon}</div>
    </div>
  )
}

export function PdcBankMatchCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const e = ev as Ev
  const severity = e.severity ?? 'pass'
  const skippedReason = e.skipped_reason

  const ifscMatch: 'match' | 'mismatch' | 'partial' =
    e.cheque_ifsc && e.statement_ifsc
      ? e.cheque_ifsc === e.statement_ifsc
        ? 'match'
        : 'mismatch'
      : 'partial'
  const tailMatch: 'match' | 'mismatch' | 'partial' =
    e.cheque_account_tail && e.statement_account_tail
      ? e.cheque_account_tail === e.statement_account_tail
        ? 'match'
        : 'mismatch'
      : 'partial'
  const sim = typeof e.name_similarity === 'number' ? e.name_similarity : null
  const nameMatch: 'match' | 'mismatch' | 'partial' =
    e.cheque_holder && e.statement_holder
      ? sim !== null && sim >= 70
        ? 'match'
        : 'mismatch'
      : 'partial'

  const reasonText = skippedReason
    ? SKIPPED_REASON_LABEL[skippedReason] ?? `Skipped — ${skippedReason}.`
    : null

  return (
    <div className="flex flex-col gap-3 text-[12px] text-pfl-slate-700">
      <div
        className={cn(
          'inline-flex w-fit items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider',
          severity === 'pass' && 'border-emerald-200 bg-emerald-50 text-emerald-700',
          severity === 'skipped' && 'border-amber-200 bg-amber-50 text-amber-700',
        )}
      >
        {severity === 'pass' ? 'pdc matches bank statement' : 'pdc match skipped'}
      </div>

      {reasonText && (
        <p className="text-[12px] text-pfl-slate-700">{reasonText}</p>
      )}

      <div className="flex flex-col gap-1.5">
        <div className="grid grid-cols-[110px_1fr_1fr_24px] gap-2 text-[10px] text-pfl-slate-400 uppercase tracking-wider">
          <div></div>
          <div>Cheque (PDC)</div>
          <div>Bank statement</div>
          <div></div>
        </div>
        <ComparisonRow
          label="IFSC"
          cheque={e.cheque_ifsc}
          statement={e.statement_ifsc}
          match={ifscMatch}
        />
        <ComparisonRow
          label="Account ★4"
          cheque={e.cheque_account_tail}
          statement={e.statement_account_tail}
          match={tailMatch}
        />
        <ComparisonRow
          label={`Name${sim !== null ? ` · ${sim}%` : ''}`}
          cheque={e.cheque_holder}
          statement={e.statement_holder}
          match={nameMatch}
        />
      </div>

      {severity === 'pass' && (
        <p className="text-[11px] text-pfl-slate-500">
          IFSC + account-tail (last 4 digits) on the cheque cross-checked
          against the bank statement extraction. Both align — the PDC will
          hit the same account that EMIs are debited from.
        </p>
      )}
    </div>
  )
}

export function pdcBankMatchHeadline(
  ev: Record<string, unknown>,
): string | undefined {
  const severity = (ev as Ev).severity
  const reason = (ev as Ev).skipped_reason
  if (severity === 'skipped' || reason) return 'PDC match — skipped'
  return 'PDC matches bank statement'
}
