'use client'

/**
 * SWR hooks for a single case + related resources.
 * Keys are arrays so mutate can target exact keys.
 */

import useSWR from 'swr'
import { cases as casesApi } from './api'
import type {
  AuditLogRead,
  CaseExtractionRead,
  CaseRead,
  ChecklistValidationResultRead,
  DedupeMatchRead,
} from './types'

const STALE_MS = 10_000

export function useCase(id: string) {
  const { data, error, isLoading, mutate } = useSWR<CaseRead>(
    id ? ['case', id] : null,
    () => casesApi.get(id),
    { dedupingInterval: STALE_MS, focusThrottleInterval: STALE_MS },
  )
  return { data, error, isLoading, mutate }
}

export function useCaseExtractions(id: string) {
  const { data, error, isLoading, mutate } = useSWR<CaseExtractionRead[]>(
    id ? ['case-extractions', id] : null,
    () => casesApi.extractions(id),
    { dedupingInterval: STALE_MS },
  )
  return { data, error, isLoading, mutate }
}

export function useCaseChecklist(id: string) {
  const { data, error, isLoading, mutate } = useSWR<ChecklistValidationResultRead>(
    id ? ['case-checklist', id] : null,
    () => casesApi.checklistValidation(id),
    { dedupingInterval: STALE_MS },
  )
  return { data, error, isLoading, mutate }
}

export function useCaseDedupeMatches(id: string) {
  const { data, error, isLoading, mutate } = useSWR<DedupeMatchRead[]>(
    id ? ['case-dedupe', id] : null,
    () => casesApi.dedupeMatches(id),
    { dedupingInterval: STALE_MS },
  )
  return { data, error, isLoading, mutate }
}

export function useCaseAuditLog(id: string) {
  const { data, error, isLoading, mutate } = useSWR<AuditLogRead[]>(
    id ? ['case-audit', id] : null,
    () => casesApi.auditLog(id),
    { dedupingInterval: STALE_MS },
  )
  return { data, error, isLoading, mutate }
}
