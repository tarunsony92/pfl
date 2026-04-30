'use client'

/**
 * /admin/l3-rerun — admin one-shot trigger to roll cases forward to the
 * v2 L3 schema (per-item table). Cases that never get viewed by an
 * assessor stay on the legacy schema; this page surfaces the count and
 * lets an admin kick off background re-runs in one click.
 *
 * Backed by the FastAPI BackgroundTasks runner — no SQS, runs in-process.
 * At ~$0.05/case Opus cost, the page shows a cost estimate before the
 * confirm so admins don't accidentally bill a 1000-case sweep.
 */

import { useCallback, useState } from 'react'
import useSWR from 'swr'
import { Loader2Icon, RefreshCwIcon, AlertCircleIcon } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/use-toast'
import { useRequireAdmin } from '@/lib/useRequireAdmin'
import { adminL3 } from '@/lib/api'

export default function L3RerunPage() {
  const { ready } = useRequireAdmin()
  const [running, setRunning] = useState(false)
  const [confirming, setConfirming] = useState(false)

  const { data, error, isLoading, mutate } = useSWR(
    ready ? ['admin-l3-rerun-preview'] : null,
    () => adminL3.preview(),
    { revalidateOnFocus: false },
  )

  const handleConfirmRerun = useCallback(async () => {
    setRunning(true)
    try {
      const res = await adminL3.rerunStale()
      toast({
        title: `Queued ${res.queued_count} L3 re-run${res.queued_count === 1 ? '' : 's'}`,
        description: `Estimated Opus spend ≈ $${res.estimated_cost_usd.toFixed(2)}. Re-runs execute in the background; refresh in ~30s/case to see progress.`,
      })
      // Optimistically zero the count — next manual refresh will repopulate
      // if any new cases drift back into stale.
      await mutate(
        { stale_count: 0, case_ids: [], estimated_cost_usd: 0 },
        { revalidate: false },
      )
      setConfirming(false)
    } catch (e) {
      toast({
        title: 'Failed to schedule L3 re-runs',
        description: e instanceof Error ? e.message : 'Unexpected error',
        variant: 'destructive',
      })
    } finally {
      setRunning(false)
    }
  }, [mutate])

  if (!ready) {
    return (
      <div className="flex flex-col gap-4 py-8">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-32 w-full" />
      </div>
    )
  }

  const staleCount = data?.stale_count ?? 0
  const previewIds = data?.case_ids ?? []
  const cost = data?.estimated_cost_usd ?? 0

  return (
    <div className="flex flex-col gap-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold text-pfl-slate-900 flex items-center gap-2">
          <RefreshCwIcon className="h-6 w-6 text-pfl-blue-700" />
          L3 Bulk Rerun
        </h1>
        <p className="text-sm text-pfl-slate-600 mt-1 leading-snug">
          Re-run L3 vision for every case still on the legacy schema (no
          per-item table). Each re-run uses Claude Opus, so the cost
          estimate below is approximate.
        </p>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700 flex gap-2 items-start"
        >
          <AlertCircleIcon className="h-4 w-4 mt-0.5 shrink-0" />
          <span>
            {error instanceof Error ? error.message : 'Failed to load stale-case preview.'}
          </span>
        </div>
      )}

      <div className="rounded-md border border-pfl-slate-200 bg-white p-5">
        {isLoading ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-5 w-1/2" />
            <Skeleton className="h-4 w-3/4" />
          </div>
        ) : staleCount === 0 ? (
          <div className="text-[13px] text-pfl-slate-700">
            No stale L3 extractions detected. All cases are on schema v2 — nothing to do.
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex items-baseline gap-3">
              <span className="text-3xl font-bold tabular-nums text-pfl-slate-900">
                {staleCount.toLocaleString('en-IN')}
              </span>
              <span className="text-[13px] text-pfl-slate-600">
                case{staleCount === 1 ? '' : 's'} still on legacy schema
              </span>
            </div>
            <div className="text-[12.5px] text-pfl-slate-600">
              Estimated Opus spend: <span className="font-semibold text-pfl-slate-800">${cost.toFixed(2)}</span>
              <span className="ml-2 text-pfl-slate-400">
                ({staleCount} × ~$0.05/case)
              </span>
            </div>

            {previewIds.length > 0 && (
              <details className="text-[12px] text-pfl-slate-500">
                <summary className="cursor-pointer text-pfl-slate-600 hover:text-pfl-slate-800">
                  Sample case IDs ({Math.min(previewIds.length, 10)} of {staleCount})
                </summary>
                <ul className="mt-2 grid grid-cols-1 gap-1 font-mono text-[11px]">
                  {previewIds.slice(0, 10).map((id) => (
                    <li key={id} className="truncate">{id}</li>
                  ))}
                </ul>
              </details>
            )}

            <div className="flex items-center gap-2 pt-2 border-t border-pfl-slate-100">
              {!confirming ? (
                <Button
                  onClick={() => setConfirming(true)}
                  className="flex items-center gap-1.5"
                >
                  <RefreshCwIcon className="h-4 w-4" />
                  Rerun {staleCount} stale case{staleCount === 1 ? '' : 's'}
                </Button>
              ) : (
                <>
                  <span className="text-[12.5px] text-amber-700 font-medium">
                    Confirm: ${cost.toFixed(2)} of Opus calls?
                  </span>
                  <Button
                    variant="destructive"
                    disabled={running}
                    onClick={handleConfirmRerun}
                    className="flex items-center gap-1.5"
                  >
                    {running && <Loader2Icon className="h-3.5 w-3.5 animate-spin" />}
                    Yes, rerun
                  </Button>
                  <Button
                    variant="outline"
                    disabled={running}
                    onClick={() => setConfirming(false)}
                  >
                    Cancel
                  </Button>
                </>
              )}
              <Button
                variant="outline"
                onClick={() => mutate()}
                disabled={isLoading || running}
                className="ml-auto"
              >
                Refresh
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
