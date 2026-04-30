/**
 * useCamDiscrepancies — SWR hook for the discrepancy summary of a case.
 *
 * Shared between DiscrepanciesPanel, the Overview banner, and the Phase 1
 * tab's "Start Phase 1" gate tooltip so all three views reflect the same
 * data (and mutate together when one of them resolves a flag).
 */

import useSWR, { type SWRConfiguration } from 'swr'
import { api } from './api'
import type { CamDiscrepancySummary } from './types'

export function useCamDiscrepancies(caseId: string, config?: SWRConfiguration) {
  return useSWR<CamDiscrepancySummary>(
    caseId ? `/cases/${caseId}/cam-discrepancies` : null,
    () => api.cases.camDiscrepancies(caseId),
    config,
  )
}
