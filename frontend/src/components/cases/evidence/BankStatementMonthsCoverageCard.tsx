'use client'
/**
 * BankStatementMonthsCoverageCard — `bank_statement_months_coverage` (L2).
 *
 * Visualises the date span of the uploaded bank statement against the
 * 6-month minimum and tells the operator the two resolution paths:
 *   1. Re-upload a longer statement (Add Artifact from the case header)
 *   2. Seek MD approval (use the Assessor solution box below this card)
 *
 * Read fields: ``available_months``, ``required_months``, ``deficit_months``,
 * ``period_start`` (ISO date), ``period_end`` (ISO date), ``tx_line_count``.
 */

function formatDate(iso: string | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

export function BankStatementMonthsCoverageCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const available =
    typeof ev['available_months'] === 'number'
      ? (ev['available_months'] as number)
      : null
  const required =
    typeof ev['required_months'] === 'number'
      ? (ev['required_months'] as number)
      : 6.0
  const deficit =
    typeof ev['deficit_months'] === 'number'
      ? (ev['deficit_months'] as number)
      : available != null
        ? Math.max(0, Math.round((required - available) * 10) / 10)
        : null
  const periodStart = ev['period_start'] as string | undefined
  const periodEnd = ev['period_end'] as string | undefined
  const txCount = ev['tx_line_count'] as number | undefined

  const ratio =
    available != null && required > 0
      ? Math.max(0, Math.min(1, available / required))
      : 0
  const isShort = available != null && available < required

  return (
    <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-2.5 text-[12px]">
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-2">
        Statement coverage period
      </div>

      {/* Headline numbers */}
      <div className="flex items-baseline gap-3 mb-2">
        <span
          className={`text-[20px] font-bold ${isShort ? 'text-red-700' : 'text-emerald-700'}`}
        >
          {available != null ? `${available.toFixed(1)}` : '—'}
          <span className="text-[12px] font-medium ml-0.5">mo</span>
        </span>
        <span className="text-[11px] text-pfl-slate-600">
          available ·{' '}
          <span className="font-medium text-pfl-slate-800">
            {required.toFixed(0)} mo
          </span>{' '}
          required
        </span>
        {isShort && deficit != null && deficit > 0 && (
          <span className="ml-auto inline-flex items-center rounded border border-red-300 bg-red-50 text-red-800 text-[10.5px] font-semibold uppercase tracking-wider px-1.5 py-0.5">
            {deficit.toFixed(1)} mo short
          </span>
        )}
      </div>

      {/* Progress bar against the 6-month minimum */}
      <div
        className="h-2 w-full rounded bg-pfl-slate-200 overflow-hidden mb-2"
        role="progressbar"
        aria-label="Statement coverage progress"
        aria-valuemin={0}
        aria-valuemax={required}
        aria-valuenow={available ?? 0}
      >
        <div
          className={`h-full ${isShort ? 'bg-red-500' : 'bg-emerald-500'}`}
          style={{ width: `${ratio * 100}%` }}
        />
      </div>

      {/* Period dates + tx count */}
      <div className="grid grid-cols-[max-content,1fr] gap-x-3 gap-y-1 text-[11.5px]">
        <span className="font-medium text-pfl-slate-600">From</span>
        <span className="font-mono text-pfl-slate-900">
          {formatDate(periodStart)}
        </span>
        <span className="font-medium text-pfl-slate-600">To</span>
        <span className="font-mono text-pfl-slate-900">
          {formatDate(periodEnd)}
        </span>
        <span className="font-medium text-pfl-slate-600">
          Transaction lines
        </span>
        <span className="font-mono text-pfl-slate-900">
          {typeof txCount === 'number'
            ? txCount.toLocaleString('en-IN')
            : '—'}
        </span>
      </div>

      {/* Resolution path hint */}
      {isShort && (
        <div className="mt-2.5 rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] leading-snug text-amber-900">
          <div className="font-semibold uppercase tracking-wider text-[10px] text-amber-800 mb-0.5">
            How to resolve
          </div>
          <ol className="list-decimal pl-4 space-y-0.5">
            <li>
              <span className="font-medium">Re-upload</span> a longer
              statement (use{' '}
              <span className="font-mono text-[10.5px]">Add Artifact</span>{' '}
              from the case header) and re-run L2 — the gap closes
              automatically once coverage ≥ {required.toFixed(0)} months.
            </li>
            <li>
              Or <span className="font-medium">seek MD approval</span> by
              writing a justification in the{' '}
              <span className="font-medium">Assessor solution</span> box
              below — the MD adjudicates from their queue.
            </li>
          </ol>
        </div>
      )}
    </div>
  )
}
