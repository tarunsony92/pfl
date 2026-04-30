'use client'

import { L3StockAnalysis } from '@/lib/types'
import { cn } from '@/lib/cn'
import {
  formatInr,
  formatPct,
  coverageTone,
  TONE_PILL_CLASSES,
} from './helpers'

/** Always-visible L3 header card.
 *  Renders the stock_analysis dict from sub_step_results. When the
 *  business scorer errored (analysis === null), shows a muted fallback
 *  with a pointer to the scorer-failure concern. */
export function L3StockAnalysisCard({
  analysis,
}: {
  analysis: L3StockAnalysis | null | undefined
}) {
  if (!analysis) {
    return (
      <div className="border border-pfl-slate-200 rounded-md bg-white p-3">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
          Stock analysis
        </div>
        <div className="text-[12.5px] text-pfl-slate-600">
          Unavailable — the business-premises scorer failed. See the{' '}
          <span className="font-mono text-[11.5px] text-pfl-slate-800">
            business_scorer_failed
          </span>{' '}
          concern below.
        </div>
      </div>
    )
  }

  const tone = coverageTone(
    analysis.coverage_pct,
    analysis.floor_pct_critical,
    analysis.floor_pct_warning,
  )
  const isService = analysis.business_type === 'service'

  return (
    <div className="border border-pfl-slate-200 rounded-md bg-white p-3 flex flex-col gap-2.5">
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500">
          Stock analysis
        </span>
        <span className="text-[11px] text-pfl-slate-500">·</span>
        <span className="text-[12px] font-medium text-pfl-slate-800">
          {analysis.business_type ?? 'unknown'}
          {analysis.business_subtype ? ` · ${analysis.business_subtype}` : ''}
        </span>
        <span
          className={cn(
            'ml-auto inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide',
            TONE_PILL_CLASSES[tone],
          )}
          title="Visible collateral coverage vs the loan amount"
        >
          coverage {formatPct(analysis.coverage_pct)}
        </span>
      </div>

      <div className="grid grid-cols-[max-content,1fr] gap-x-4 gap-y-1 text-[12.5px]">
        <span className="text-pfl-slate-500">Loan amount</span>
        <span className="text-pfl-slate-900 font-semibold">
          {formatInr(analysis.loan_amount_inr)}
        </span>

        <span className="text-pfl-slate-500">Visible collateral</span>
        <span className="text-pfl-slate-900 font-semibold">
          {formatInr(analysis.visible_collateral_inr)}
        </span>

        {isService && analysis.visible_equipment_value_inr != null && (
          <>
            <span className="pl-3 text-pfl-slate-500 text-[11.5px]">· stock</span>
            <span className="text-pfl-slate-700 text-[11.5px]">
              {formatInr(analysis.stock_value_estimate_inr)}
            </span>
            <span className="pl-3 text-pfl-slate-500 text-[11.5px]">· equipment</span>
            <span className="text-pfl-slate-700 text-[11.5px]">
              {formatInr(analysis.visible_equipment_value_inr)}
            </span>
          </>
        )}

        <span className="text-pfl-slate-500">Floor</span>
        <span className="text-pfl-slate-800">
          {formatPct(analysis.floor_pct_critical)} critical
          {analysis.floor_pct_warning != null
            ? ` · ${formatPct(analysis.floor_pct_warning)} warning`
            : ''}
        </span>

        <span className="text-pfl-slate-500">Recommended loan</span>
        <span className="text-pfl-slate-900 font-semibold">
          {formatInr(analysis.recommended_loan_amount_inr)}
          {analysis.cut_pct != null && analysis.cut_pct > 0 && (
            <span className="ml-2 text-red-700 text-[11.5px] font-normal">
              ({formatPct(analysis.cut_pct)} cut)
            </span>
          )}
        </span>
      </div>

      {analysis.reasoning && (
        <p className="text-[12px] text-pfl-slate-700 whitespace-pre-wrap leading-relaxed">
          {analysis.reasoning}
        </p>
      )}
    </div>
  )
}
