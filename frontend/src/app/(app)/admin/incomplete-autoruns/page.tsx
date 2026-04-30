'use client'

/**
 * /admin/incomplete-autoruns — defaulter log.
 *
 * Lists every auto-run started while one or more required artefacts were
 * missing on the case. The completeness gate (FE) records an entry here
 * whenever the user chooses to skip the upload prompt and continue. Admin
 * uses the page to chase repeat offenders ("defaulters").
 */

import useSWR from 'swr'
import { AlertTriangleIcon } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { useRequireAdmin } from '@/lib/useRequireAdmin'
import { incompleteAutoruns, type IncompleteAutorunLogRead } from '@/lib/api'

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 30) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

function offenderCount(rows: IncompleteAutorunLogRead[]): Record<string, number> {
  const out: Record<string, number> = {}
  for (const r of rows) {
    const key = r.user_email || r.user_id
    out[key] = (out[key] ?? 0) + 1
  }
  return out
}

export default function IncompleteAutorunsPage() {
  const { ready } = useRequireAdmin()
  const { data, error, isLoading } = useSWR(
    ready ? ['admin-incomplete-autorun-logs'] : null,
    () => incompleteAutoruns.listLogs({ limit: 200 }),
    { revalidateOnFocus: false },
  )

  const rows = data ?? []
  const counts = offenderCount(rows)

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="flex items-center gap-3">
        <AlertTriangleIcon className="h-5 w-5 text-amber-700" aria-hidden="true" />
        <h1 className="text-xl font-semibold text-pfl-slate-900">Incomplete Auto-Runs</h1>
        <span className="text-sm text-pfl-slate-500">
          {rows.length} entr{rows.length === 1 ? 'y' : 'ies'}
        </span>
      </div>

      <p className="text-[13px] text-pfl-slate-600 max-w-3xl">
        Each row is one auto-run started while a required artefact was still
        missing on the case. The user dismissed the completeness gate and
        proceeded anyway, so the system logged who, which case, and which files
        were absent at the time of skip.
      </p>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-[12.5px] text-red-800">
          {String((error as { message?: string })?.message ?? 'Failed to load log')}
        </div>
      )}

      {isLoading || !ready ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-pfl-slate-300 bg-pfl-slate-50/40 p-10 text-center text-[13px] text-pfl-slate-500">
          No incomplete auto-runs on file. Either every recent auto-run had
          complete documentation, or no one has skipped the gate yet.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-pfl-slate-200">
          <table className="min-w-full divide-y divide-pfl-slate-200 text-sm">
            <thead className="bg-pfl-slate-50">
              <tr>
                <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">When</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">User</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Case</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Missing files</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold text-pfl-slate-700">Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-pfl-slate-100 bg-white">
              {rows.map((r) => {
                const userKey = r.user_email || r.user_id
                const offenderHits = counts[userKey] ?? 1
                return (
                  <tr key={r.id} className="hover:bg-pfl-blue-50/40">
                    <td className="px-4 py-3 text-pfl-slate-700 text-xs whitespace-nowrap">
                      <div className="font-medium text-pfl-slate-900">{relativeTime(r.created_at)}</div>
                      <div className="text-pfl-slate-500">{new Date(r.created_at).toLocaleString()}</div>
                    </td>
                    <td className="px-4 py-3 text-pfl-slate-700">
                      <div className="font-medium">{r.user_full_name || r.user_email || r.user_id.slice(0, 8) + '…'}</div>
                      {r.user_email && r.user_full_name && (
                        <div className="text-xs text-pfl-slate-500">{r.user_email}</div>
                      )}
                      {offenderHits >= 3 && (
                        <span className="mt-1 inline-flex items-center rounded-md bg-red-100 text-red-800 px-1.5 py-0.5 text-[10.5px] font-semibold">
                          repeat offender · {offenderHits} skips
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-pfl-slate-700 text-xs">
                      <a
                        className="font-mono font-semibold text-pfl-blue-700 hover:underline"
                        href={`/cases/${r.case_id}`}
                      >
                        {r.case_loan_id || r.case_id.slice(0, 8) + '…'}
                      </a>
                      {r.case_applicant_name && (
                        <div className="text-pfl-slate-500">{r.case_applicant_name}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      <ul className="flex flex-wrap gap-1">
                        {(r.missing_subtypes || []).map((s) => (
                          <li
                            key={s}
                            className="inline-flex items-center rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 font-mono text-[10.5px] text-amber-900"
                          >
                            {s}
                          </li>
                        ))}
                        {(r.missing_subtypes || []).length === 0 && (
                          <li className="italic text-pfl-slate-400">—</li>
                        )}
                      </ul>
                    </td>
                    <td className="px-4 py-3 text-xs text-pfl-slate-700">
                      {r.reason || <span className="italic text-pfl-slate-400">— no reason given —</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
