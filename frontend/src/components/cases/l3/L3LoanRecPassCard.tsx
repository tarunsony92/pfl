'use client'
import { formatInr, formatPct } from './helpers'

type Evidence = {
  loan_amount_inr?: number | null
  recommended_loan_amount_inr?: number | null
  cut_pct?: number | null
  trigger_pct?: number
  rationale?: string | null
  photos_evaluated_count?: number
}

export function L3LoanRecPassCard({ evidence }: { evidence: Evidence }) {
  return (
    <div className="border border-pfl-slate-200 rounded bg-pfl-slate-50 p-3 flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-3 text-[12.5px]">
        <div className="border border-pfl-slate-200 rounded bg-white p-2">
          <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-0.5">
            Proposed
          </div>
          <div className="text-pfl-slate-900 font-semibold">
            {formatInr(evidence.loan_amount_inr)}
          </div>
        </div>
        <div className="border border-pfl-slate-200 rounded bg-white p-2">
          <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-0.5">
            Recommended
          </div>
          <div className="text-pfl-slate-900 font-semibold">
            {formatInr(evidence.recommended_loan_amount_inr)}
            {evidence.cut_pct != null && evidence.cut_pct > 0 && (
              <span className="ml-2 text-red-700 text-[11.5px]">
                ({formatPct(evidence.cut_pct)} cut)
              </span>
            )}
          </div>
        </div>
      </div>
      {evidence.rationale && (
        <p className="text-[12px] text-pfl-slate-700 leading-relaxed">
          {evidence.rationale}
        </p>
      )}
      {evidence.photos_evaluated_count != null && (
        <div className="text-[11px] text-pfl-slate-500">
          {evidence.photos_evaluated_count} photos evaluated · trigger floor{' '}
          {formatPct(evidence.trigger_pct ?? 0.8)}
        </div>
      )}
    </div>
  )
}
