'use client'

/**
 * SWR hooks for Phase 1 decisioning data.
 */

import useSWR from 'swr'
import { cases as casesApi } from './api'
import type { DecisionResultRead, DecisionStepRead } from './types'

const STALE_MS = 5_000
// Poll every 3 seconds when actively running
const POLL_INTERVAL_RUNNING = 3_000

export function useDecisionResult(caseId: string) {
  const { data, error, isLoading, mutate } = useSWR<DecisionResultRead>(
    caseId ? ['case-phase1', caseId] : null,
    () => casesApi.phase1Get(caseId),
    {
      dedupingInterval: STALE_MS,
      // Poll while PENDING or RUNNING
      refreshInterval: (data) => {
        if (!data) return 0
        const s = data.status
        if (s === 'PENDING' || s === 'RUNNING') return POLL_INTERVAL_RUNNING
        return 0
      },
      // Silence 404 errors — means no decisioning run yet
      onError: () => { /* suppress */ },
    },
  )
  return { data, error, isLoading, mutate }
}

export function useDecisionSteps(caseId: string, enabled = true) {
  const { data, error, isLoading, mutate } = useSWR<DecisionStepRead[]>(
    caseId && enabled ? ['case-phase1-steps', caseId] : null,
    () => casesApi.phase1Steps(caseId),
    {
      dedupingInterval: STALE_MS,
      refreshInterval: (data) => {
        if (!data || data.length === 0) return POLL_INTERVAL_RUNNING
        const running = data.some((s) => s.status === 'PENDING' || s.status === 'RUNNING')
        return running ? POLL_INTERVAL_RUNNING : 0
      },
    },
  )
  return { data, error, isLoading, mutate }
}
