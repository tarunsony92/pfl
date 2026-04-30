'use client'

/**
 * SWR hook wrapping api.cases.list().
 * Key: ['cases', filters] — refreshes on filter change.
 * Staleness: 10s per spec §10.
 */

import useSWR from 'swr'
import { cases as casesApi } from './api'
import type { CaseListFilters } from './api'
import type { CaseListResponse } from './types'

const STALE_MS = 10_000

export function useCases(filters: CaseListFilters = {}) {
  const key = ['cases', filters] as const

  const { data, error, isLoading, isValidating, mutate } = useSWR<CaseListResponse>(
    key,
    () => casesApi.list(filters),
    {
      dedupingInterval: STALE_MS,
      focusThrottleInterval: STALE_MS,
      keepPreviousData: true,
    },
  )

  return {
    data,
    error,
    isLoading,
    isValidating,
    mutate,
  }
}
