'use client'
/**
 * LoanAgreementMissingCard — `loan_agreement_missing` (L4). Trivial
 * absence card.
 */

export function LoanAgreementMissingCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const filename = ev['agreement_filename'] as string | undefined
  return (
    <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-2 text-[12px]">
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1.5">
        Loan agreement presence
      </div>
      <div className="grid grid-cols-[max-content,1fr] gap-x-3 gap-y-1">
        <span className="font-medium text-pfl-slate-600">Filename</span>
        <span className="font-mono text-pfl-slate-900">
          {filename ?? '— not on file —'}
        </span>
      </div>
    </div>
  )
}
