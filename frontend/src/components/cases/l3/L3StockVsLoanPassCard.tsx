'use client'
import { L3StockAnalysis } from '@/lib/types'
import { cn } from '@/lib/cn'
import { formatInr, formatPct, coverageTone, TONE_PILL_CLASSES } from './helpers'

type Evidence = L3StockAnalysis & { photos_evaluated_count?: number }

export function L3StockVsLoanPassCard({ evidence }: { evidence: Evidence }) {
  const tone = coverageTone(
    evidence.coverage_pct,
    evidence.floor_pct_critical,
    evidence.floor_pct_warning,
  )
  const isService = evidence.business_type === 'service'
  return (
    <div className="border border-pfl-slate-200 rounded bg-pfl-slate-50 p-3 flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-3">
        <div className="border border-pfl-slate-200 rounded bg-white p-2">
          <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
            Visible collateral
          </div>
          <table className="w-full text-[12px]">
            <tbody>
              <tr>
                <td className="text-pfl-slate-600">Stock</td>
                <td className="text-right text-pfl-slate-900 font-medium">
                  {formatInr(evidence.stock_value_estimate_inr)}
                </td>
              </tr>
              {isService && (
                <tr>
                  <td className="text-pfl-slate-600">Fixed equipment</td>
                  <td className="text-right text-pfl-slate-900 font-medium">
                    {formatInr(evidence.visible_equipment_value_inr)}
                  </td>
                </tr>
              )}
              <tr className="border-t border-pfl-slate-200">
                <td className="pt-1 text-pfl-slate-700 font-semibold">Total</td>
                <td className="pt-1 text-right text-pfl-slate-900 font-semibold">
                  {formatInr(evidence.visible_collateral_inr)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div className="border border-pfl-slate-200 rounded bg-white p-2">
          <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
            Loan amount
          </div>
          <div className="text-[15px] font-semibold text-pfl-slate-900">
            {formatInr(evidence.loan_amount_inr)}
          </div>
          <div className="mt-2 text-[11.5px] text-pfl-slate-600">
            Floor: {formatPct(evidence.floor_pct_critical)} critical
            {evidence.floor_pct_warning != null
              ? ` · ${formatPct(evidence.floor_pct_warning)} warning`
              : ''}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <span
          className={cn(
            'inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold',
            TONE_PILL_CLASSES[tone],
          )}
        >
          coverage {formatPct(evidence.coverage_pct)}
        </span>
        {evidence.recommended_loan_amount_inr != null && (
          <span className="text-[11.5px] text-pfl-slate-700">
            · recommended {formatInr(evidence.recommended_loan_amount_inr)}
          </span>
        )}
        {evidence.photos_evaluated_count != null && (
          <span className="ml-auto text-[11px] text-pfl-slate-500">
            {evidence.photos_evaluated_count} photo
            {evidence.photos_evaluated_count === 1 ? '' : 's'} evaluated
          </span>
        )}
      </div>

      {evidence.reasoning && (
        <p className="text-[12px] text-pfl-slate-700 leading-relaxed">
          {evidence.reasoning}
        </p>
      )}
    </div>
  )
}
