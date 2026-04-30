'use client'

/**
 * ReingestDialog — confirm + trigger re-ingestion for admin users.
 *
 * Enabled only when stage in {INGESTED, CHECKLIST_MISSING_DOCS, CHECKLIST_VALIDATED}.
 * On confirm: api.cases.reingest(caseId) → toast → SWR mutate.
 */

import React, { useState } from 'react'
import { RefreshCwIcon } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/use-toast'
import { cases as casesApi } from '@/lib/api'
import { useAutoRun } from '@/components/autorun/AutoRunProvider'
import type { CaseStage } from '@/lib/enums'
import type { KeyedMutator } from 'swr'
import type { CaseRead } from '@/lib/types'

const REINGEST_ALLOWED_STAGES: CaseStage[] = [
  'INGESTED',
  'CHECKLIST_MISSING_DOCS',
  'CHECKLIST_VALIDATED',
]

interface ReingestDialogProps {
  caseId: string
  currentStage: CaseStage
  mutateCase: KeyedMutator<CaseRead>
}

export function ReingestDialog({ caseId, currentStage, mutateCase }: ReingestDialogProps) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const { startAutoRun } = useAutoRun()

  const isAllowed = REINGEST_ALLOWED_STAGES.includes(currentStage)

  async function handleConfirm() {
    setLoading(true)
    try {
      await casesApi.reingest(caseId)
      toast({ title: 'Re-ingestion triggered', description: 'The case is being re-ingested.' })
      setOpen(false)
      const freshCase = await mutateCase()
      // Re-ingest → extractions re-run → we can immediately start the
      // 7-level pipeline client-side. Individual level calls that hit the
      // backend before ingest finishes will surface as step failures in the
      // modal (which the user can resume once ingestion settles).
      startAutoRun({
        caseId,
        loanId: freshCase?.loan_id ?? null,
        applicantName: freshCase?.applicant_name ?? null,
      })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      toast({ title: 'Re-ingest failed', description: message, variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        disabled={!isAllowed}
        onClick={() => setOpen(true)}
        title={!isAllowed ? `Re-ingest not available in stage ${currentStage}` : undefined}
      >
        <RefreshCwIcon className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
        Re-ingest
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Re-ingest case?</DialogTitle>
            <DialogDescription>
              This will re-run all extraction workers on the existing artifacts. The case stage will
              transition back through the ingestion pipeline.
            </DialogDescription>
          </DialogHeader>

          <div className="mt-4 flex justify-end gap-2">
            <DialogClose asChild>
              <Button variant="ghost" size="sm" disabled={loading}>
                Cancel
              </Button>
            </DialogClose>
            <Button
              variant="default"
              size="sm"
              disabled={loading}
              onClick={handleConfirm}
            >
              {loading ? 'Processing…' : 'Confirm re-ingest'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
