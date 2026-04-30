'use client'

import { useEffect } from 'react'
import { useSWRConfig } from 'swr'
import type { CaseStage } from './enums'

// Stages worth polling — worker is actively processing
const IN_FLIGHT_STAGES: Set<CaseStage> = new Set([
  'CHECKLIST_VALIDATION',
  'CHECKLIST_MISSING_DOCS',  // re-trigger can fire here when user adds artifact
  'PHASE_1_DECISIONING',
  'PHASE_2_AUDITING',
])

export function useCasePolling(caseId: string, currentStage: CaseStage | undefined) {
  const { mutate } = useSWRConfig()
  useEffect(() => {
    if (!currentStage || !IN_FLIGHT_STAGES.has(currentStage)) return
    if (document.hidden) return  // no polling when tab backgrounded

    const interval = setInterval(() => {
      mutate(['case', caseId])
      mutate(['case-extractions', caseId])
      mutate(['case-checklist', caseId])
      mutate(['case-dedupe', caseId])
      mutate(['case-audit', caseId])
    }, 5000)

    const onVisibility = () => {
      if (document.hidden) {
        clearInterval(interval)
      }
    }
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [caseId, currentStage, mutate])
}
