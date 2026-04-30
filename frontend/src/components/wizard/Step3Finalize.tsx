'use client'

/**
 * Step 3 — Finalize.
 *
 * Calls api.cases.finalize(caseId) on mount.
 * Shows spinner → success → auto-redirects to /cases/[id] after 2 s.
 */

import React, { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { CheckCircleIcon, Loader2Icon } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { api } from '@/lib/api'
import { useAutoRun } from '@/components/autorun/AutoRunProvider'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface Step3FinalizeProps {
  caseId: string
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Step3Finalize({ caseId }: Step3FinalizeProps) {
  const router = useRouter()
  const { startAutoRun } = useAutoRun()
  const [state, setState] = useState<'pending' | 'success' | 'error'>('pending')
  const [errorMsg, setErrorMsg] = useState<string>('')
  // Guard against React Strict Mode double-fire of the effect: we only want
  // finalize() to run once per caseId; a double-call would trigger a duplicate
  // finalize on the backend and the first run's cleanup would cancel the
  // scheduled redirect before it fires.
  const startedRef = useRef<string | null>(null)

  useEffect(() => {
    if (startedRef.current === caseId) return
    startedRef.current = caseId

    async function finalize() {
      try {
        const caseRead = await api.cases.finalize(caseId)
        setState('success')
        // Kick off the 7-level auto-run as soon as the upload is finalised.
        // The provider queues the calls client-side; the global AutoRunModal
        // opens immediately so the user sees progress through the redirect.
        startAutoRun({
          caseId,
          loanId: caseRead?.loan_id ?? null,
          applicantName: caseRead?.applicant_name ?? null,
        })
        setTimeout(() => {
          router.push(`/cases/${caseId}`)
        }, 2000)
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Finalization failed'
        setErrorMsg(msg)
        setState('error')
      }
    }

    finalize()
  }, [caseId, router, startAutoRun])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Step 3 — Finalizing</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col items-center gap-6 py-10">
        {state === 'pending' && (
          <>
            <Loader2Icon className="h-12 w-12 animate-spin text-pfl-blue-700" aria-hidden="true" />
            <p className="text-sm text-pfl-slate-600">Processing your case, please wait…</p>
          </>
        )}

        {state === 'success' && (
          <>
            <CheckCircleIcon className="h-12 w-12 text-green-500" aria-hidden="true" />
            <div className="flex flex-col items-center gap-1 text-center">
              <p className="text-base font-semibold text-pfl-slate-900">Case finalized!</p>
              <p className="text-sm text-pfl-slate-500">
                Redirecting to case detail in 2 seconds…
              </p>
            </div>
          </>
        )}

        {state === 'error' && (
          <div
            role="alert"
            className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700 text-center max-w-sm"
          >
            <p className="font-semibold mb-1">Finalization failed</p>
            <p>{errorMsg}</p>
            <p className="mt-2 text-xs">
              Your file was uploaded. You can retry finalization from the case detail page.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
