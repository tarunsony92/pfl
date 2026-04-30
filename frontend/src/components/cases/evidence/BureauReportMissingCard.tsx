'use client'
/**
 * BureauReportMissingCard — `bureau_report_missing` (L1.5). Trivial
 * card: did the case carry an Equifax / bureau extraction at all?
 */

export function BureauReportMissingCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const equifaxRows = ev['equifax_rows_found'] as number | undefined
  const expectedSubtype = ev['expected_subtype'] as string | undefined

  return (
    <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-2 text-[12px]">
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1.5">
        Bureau extraction presence
      </div>
      <div className="grid grid-cols-[max-content,1fr] gap-x-3 gap-y-1">
        {expectedSubtype && (
          <>
            <span className="font-medium text-pfl-slate-600">Expected document</span>
            <span className="font-mono text-pfl-slate-900">{expectedSubtype}</span>
          </>
        )}
        <span className="font-medium text-pfl-slate-600">Equifax rows found</span>
        <span className="font-mono text-pfl-slate-900">
          {typeof equifaxRows === 'number' ? equifaxRows : '—'}
        </span>
      </div>
    </div>
  )
}

export function bureauReportMissingHeadline(
  ev: Record<string, unknown>,
): string | undefined {
  const n = ev['equifax_rows_found']
  if (typeof n === 'number') return `${n} rows`
  return undefined
}
