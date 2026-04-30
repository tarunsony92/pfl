'use client'

/**
 * SWR hooks for the 4-level verification gate.
 *
 * Keys are arrays so ``mutate`` can target exact keys after a trigger/resolve.
 */

import useSWR from 'swr'
import { cases as casesApi, casePhotos, fetchPrecedents, verification as verificationApi } from './api'
import type {
  CasePhotosResponse,
  MDQueueResponse,
  PrecedentsResponse,
  VerificationLevelDetail,
  VerificationLevelNumber,
  VerificationOverview,
} from './types'

const STALE_MS = 8_000

export function useVerificationOverview(caseId: string) {
  const { data, error, isLoading, mutate } = useSWR<VerificationOverview>(
    caseId ? ['verification-overview', caseId] : null,
    () => casesApi.verificationOverview(caseId),
    { dedupingInterval: STALE_MS, focusThrottleInterval: STALE_MS },
  )
  return { data, error, isLoading, mutate }
}

export function useVerificationLevelDetail(
  caseId: string,
  level: VerificationLevelNumber,
) {
  const { data, error, isLoading, mutate } = useSWR<VerificationLevelDetail>(
    caseId ? ['verification-level', caseId, level] : null,
    () => casesApi.verificationLevelDetail(caseId, level),
    { dedupingInterval: STALE_MS },
  )
  return { data, error, isLoading, mutate }
}

export function useMDQueue(enabled = true) {
  const { data, error, isLoading, mutate } = useSWR<MDQueueResponse>(
    enabled ? ['verification-md-queue'] : null,
    () => verificationApi.mdQueue(),
    { dedupingInterval: STALE_MS, focusThrottleInterval: STALE_MS },
  )
  return { data, error, isLoading, mutate }
}

export function useAssessorQueue(enabled = true) {
  const { data, error, isLoading, mutate } = useSWR<MDQueueResponse>(
    enabled ? ['verification-assessor-queue'] : null,
    () => verificationApi.assessorQueue(),
    { dedupingInterval: STALE_MS, focusThrottleInterval: STALE_MS },
  )
  return { data, error, isLoading, mutate }
}

export function useCasePhotos(
  caseId: string,
  subtype: 'HOUSE_VISIT_PHOTO' | 'BUSINESS_PREMISES_PHOTO',
  enabled = true,
) {
  const { data, error, isLoading } = useSWR<CasePhotosResponse>(
    caseId && enabled ? ['case-photos', caseId, subtype] : null,
    () => casePhotos(caseId, subtype),
    { dedupingInterval: 30_000 },
  )
  return { data, error, isLoading }
}

export function usePrecedents(subStepId: string | null, enabled = true) {
  const { data, error, isLoading } = useSWR<PrecedentsResponse>(
    subStepId && enabled ? ['precedents', subStepId] : null,
    () => fetchPrecedents(subStepId!),
    { dedupingInterval: 30_000 },
  )
  return { data, error, isLoading }
}
