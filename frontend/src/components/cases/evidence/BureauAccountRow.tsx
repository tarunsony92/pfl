'use client'

import { formatInr } from '../l3/helpers'

type WorstAccount = {
  institution?: string | null
  status?: string | null
  date_opened?: string | null
  balance?: number | null
  type?: string | null
  product_type?: string | null
}

type Evidence = {
  worst_account?: WorstAccount | null
  statuses_seen?: string[] | null
  party?: 'applicant' | 'co_applicant' | string | null
}

/**
 * `BureauAccountRow` — smart-layout for L1.5 bureau status scanners
 * (`credit_write_off`, `credit_loss`, `credit_settled`,
 * `credit_substandard`, `credit_doubtful`, `credit_sma`, and their
 * `coapp_*` mirrors). Renders a compact card with a party pill, a
 * one-line summary of the worst matched account, and a "+N more" chip
 * listing any remaining raw status strings.
 */
export function BureauAccountRow({ evidence }: { evidence: Evidence }) {
  const party = evidence.party ?? null
  const partyLabel =
    party === 'co_applicant' || party === 'coapp'
      ? 'Co-applicant'
      : party === 'applicant'
        ? 'Applicant'
        : party != null
          ? String(party)
          : null

  const worst = evidence.worst_account ?? null
  const hasWorst =
    !!worst &&
    (worst.institution != null ||
      worst.status != null ||
      worst.date_opened != null ||
      worst.balance != null)

  const statuses = Array.isArray(evidence.statuses_seen)
    ? evidence.statuses_seen.filter((s) => typeof s === 'string')
    : []
  const extraStatuses = hasWorst
    ? statuses.filter((s) => s !== worst?.status)
    : statuses
  const moreCount = extraStatuses.length

  return (
    <div className="border border-pfl-slate-200 rounded bg-pfl-slate-50 p-3 flex flex-col gap-2">
      <div className="flex items-center gap-2 text-[12px]">
        {partyLabel && (
          <span className="inline-flex items-center rounded-md border border-pfl-slate-300 bg-white px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-700">
            {partyLabel}
          </span>
        )}
        {hasWorst ? (
          <span className="text-pfl-slate-800 leading-snug">
            <span className="font-semibold text-pfl-slate-900">
              {worst?.institution ?? 'Unknown institution'}
            </span>
            {worst?.status && (
              <>
                <span className="mx-1.5 text-pfl-slate-400">·</span>
                <span className="font-medium">{worst.status}</span>
              </>
            )}
            {worst?.date_opened && (
              <>
                <span className="mx-1.5 text-pfl-slate-400">·</span>
                <span className="text-pfl-slate-600">
                  opened {worst.date_opened}
                </span>
              </>
            )}
            {typeof worst?.balance === 'number' && (
              <>
                <span className="mx-1.5 text-pfl-slate-400">·</span>
                <span className="text-pfl-slate-700">
                  {formatInr(worst.balance)}
                </span>
              </>
            )}
          </span>
        ) : (
          <span className="text-pfl-slate-500 italic">
            No worst-account detail available.
          </span>
        )}
        {moreCount > 0 && (
          <span
            className="ml-auto inline-flex items-center rounded-md border border-pfl-slate-300 bg-white px-2 py-0.5 text-[11px] font-medium text-pfl-slate-700"
            title={extraStatuses.join(', ')}
          >
            +{moreCount} more
          </span>
        )}
      </div>
      {(worst?.type || worst?.product_type) && (
        <div className="flex items-center gap-2 text-[11px] text-pfl-slate-600">
          {worst?.type && <span>Type: {worst.type}</span>}
          {worst?.product_type && <span>Product: {worst.product_type}</span>}
        </div>
      )}
    </div>
  )
}
