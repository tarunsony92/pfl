'use client'
/**
 * BankStatementMissingCard — `bank_statement_missing` (L2). Trivial:
 * did the bank statement extract at all?
 */

export function BankStatementMissingCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const status = (ev['extraction_status'] as string | undefined) ?? '—'
  const txCount = ev['tx_line_count'] as number | undefined
  return (
    <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-2 text-[12px]">
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1.5">
        Bank statement extraction
      </div>
      <div className="grid grid-cols-[max-content,1fr] gap-x-3 gap-y-1">
        <span className="font-medium text-pfl-slate-600">Status</span>
        <span className="font-mono text-pfl-slate-900">{status}</span>
        <span className="font-medium text-pfl-slate-600">Transaction lines</span>
        <span className="font-mono text-pfl-slate-900">
          {typeof txCount === 'number' ? txCount.toLocaleString('en-IN') : '—'}
        </span>
      </div>
    </div>
  )
}
