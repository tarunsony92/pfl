'use client'
/**
 * DedupeMatchesCard — `dedupe_clear` (L5.5).
 *
 * Three failure modes the orchestrator emits, each with distinct evidence:
 *  - row_count > 0    → matched rows table (the "potential duplicate" path)
 *  - row_count = null + extraction_status FAILED → "extraction failed" notice
 *  - row_count = null + extraction missing → "report not yet parsed" notice
 *  - dedupe artefact missing → "report not uploaded" notice (no evidence rows)
 *
 * Pass path (row_count == 0) renders the "no matches" green pill.
 */

import { cn } from '@/lib/cn'

type Row = {
  customer_id?: string | number | null
  customer_name?: string | null
  full_name?: string | null
  aadhaar?: string | null
  aadhaar_id?: string | null
  pan?: string | null
  pan_card?: string | null
  mobile?: string | null
  mobile_no?: string | null
  dob?: string | null
  [key: string]: unknown
}

const COLS: Array<{ keys: string[]; label: string }> = [
  // Each col tries multiple keys to handle both the existing builder shape
  // (Customer Name / Aadhaar / PAN / Mobile / DOB) and the real Finpage
  // 16-col shape (Customer Id / Full Name / Aadhaar Id / Pan Card / Mobile No / DOB).
  { keys: ['customer_id'], label: 'Customer ID' },
  { keys: ['type'], label: 'Type' },
  { keys: ['customer_name', 'full_name'], label: 'Name' },
  { keys: ['aadhaar', 'aadhaar_id'], label: 'Aadhaar' },
  { keys: ['pan', 'pan_card'], label: 'PAN' },
  { keys: ['voter_card', 'voter_id'], label: 'Voter' },
  { keys: ['driving_license', 'dl'], label: 'DL' },
  { keys: ['passport', 'passport_id'], label: 'Passport' },
  { keys: ['mobile', 'mobile_no'], label: 'Mobile' },
  { keys: ['dob'], label: 'DOB' },
]

function pick(row: Row, keys: string[]): string {
  for (const k of keys) {
    const v = row[k]
    if (v !== null && v !== undefined && v !== '') return String(v)
  }
  return '—'
}

export function DedupeMatchesCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const rowCount = ev['row_count'] as number | null | undefined
  const matchedRows = (ev['matched_rows'] as Row[] | undefined) ?? []
  const extractionStatus = ev['extraction_status'] as string | undefined
  const errorMessage = ev['error_message'] as string | undefined
  const expectedSubtype = ev['expected_subtype'] as string | undefined

  // Case A — DEDUPE_REPORT artefact missing entirely
  if (expectedSubtype && rowCount === null) {
    return (
      <div className="flex flex-col gap-2 text-[12px] text-pfl-slate-700">
        <div className="inline-flex w-fit items-center rounded border border-red-200 bg-red-50 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-red-700">
          report missing
        </div>
        <p>
          The Finpage Customer_Dedupe xlsx isn&apos;t attached to this case. Upload
          it (subtype <code className="font-mono">{expectedSubtype}</code>) so
          identity uniqueness can be verified.
        </p>
      </div>
    )
  }

  // Case B — extraction failed
  if (extractionStatus && extractionStatus !== 'SUCCESS') {
    return (
      <div className="flex flex-col gap-2 text-[12px] text-pfl-slate-700">
        <div className="inline-flex w-fit items-center rounded border border-red-200 bg-red-50 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-red-700">
          extraction {extractionStatus.toLowerCase()}
        </div>
        {errorMessage && (
          <p className="font-mono text-[11px] text-pfl-slate-600">
            {errorMessage}
          </p>
        )}
        <p>Re-trigger ingestion to re-parse the dedupe report.</p>
      </div>
    )
  }

  // Case C — extraction not yet run
  if (rowCount === null) {
    return (
      <div className="flex flex-col gap-2 text-[12px] text-pfl-slate-700">
        <div className="inline-flex w-fit items-center rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-700">
          pending parse
        </div>
        <p>
          Dedupe report uploaded but not yet parsed. Wait for the extraction
          worker, or re-trigger ingestion.
        </p>
      </div>
    )
  }

  // Case D / E — extraction succeeded; render row count + table when > 0
  const cleared = rowCount === 0
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 text-[12px]">
        <span className="text-pfl-slate-700">Match rows:</span>
        <span
          className={cn(
            'font-mono text-[14px] font-bold',
            cleared ? 'text-emerald-700' : 'text-red-700',
          )}
        >
          {rowCount}
        </span>
        <span
          className={cn(
            'ml-2 inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider',
            cleared
              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
              : 'bg-red-50 text-red-700 border-red-200',
          )}
        >
          {cleared ? 'no duplicates' : 'duplicate match'}
        </span>
      </div>
      {matchedRows.length > 0 && (
        <div className="rounded border border-pfl-slate-200 bg-white overflow-hidden">
          <table className="w-full text-[11.5px]">
            <thead className="bg-pfl-slate-50 text-pfl-slate-600 uppercase text-[10px] tracking-wider">
              <tr>
                {COLS.map((c) => (
                  <th key={c.label} className="px-2 py-1 text-left">
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {matchedRows.map((r, i) => (
                <tr key={i} className="border-t border-pfl-slate-100">
                  {COLS.map((c) => (
                    <td
                      key={c.label}
                      className="px-2 py-1 font-mono text-pfl-slate-700"
                    >
                      {pick(r, c.keys)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export function dedupeMatchesHeadline(
  ev: Record<string, unknown>,
): string | undefined {
  const expectedSubtype = ev['expected_subtype']
  if (expectedSubtype) return 'Dedupe report not uploaded'
  const status = ev['extraction_status']
  if (status && status !== 'SUCCESS') return 'Dedupe extraction failed'
  const n = ev['row_count']
  if (n === null || n === undefined) return 'Dedupe parse pending'
  if (typeof n === 'number')
    return n === 0
      ? 'No duplicate identity match'
      : `${n} potential duplicate${n === 1 ? '' : 's'}`
  return undefined
}
