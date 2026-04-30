'use client'

/**
 * ReuploadDialog — confirm + approve re-upload flow.
 *
 * Click → dialog with reason textarea → confirm → api.cases.approveReupload(caseId, reason)
 * → toast → SWR mutate.
 */

import React, { useState } from 'react'
import { UploadCloudIcon } from 'lucide-react'
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
import type { KeyedMutator } from 'swr'
import type { CaseRead } from '@/lib/types'

interface ReuploadDialogProps {
  caseId: string
  mutateCase: KeyedMutator<CaseRead>
}

export function ReuploadDialog({ caseId, mutateCase }: ReuploadDialogProps) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleConfirm() {
    setLoading(true)
    try {
      await casesApi.approveReupload(caseId, reason || 'Re-upload requested')
      toast({
        title: 'Re-upload approved',
        description: 'The applicant may now upload a new ZIP. The current ZIP will be archived.',
      })
      setOpen(false)
      setReason('')
      await mutateCase()
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      toast({ title: 'Re-upload failed', description: message, variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }

  function handleOpenChange(val: boolean) {
    if (!val) setReason('')
    setOpen(val)
  }

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <UploadCloudIcon className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
        Re-upload ZIP
      </Button>

      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm re-upload</DialogTitle>
            <DialogDescription>
              This archives the current ZIP and allows the applicant to submit a new one.
            </DialogDescription>
          </DialogHeader>

          <div className="mt-3">
            <label htmlFor="reupload-reason" className="block text-sm font-medium text-pfl-slate-700 mb-1">
              Reason (optional)
            </label>
            <textarea
              id="reupload-reason"
              className="w-full rounded border border-pfl-slate-300 px-3 py-2 text-sm text-pfl-slate-900 focus:outline-none focus:ring-2 focus:ring-pfl-blue-600 resize-none"
              rows={3}
              placeholder="e.g. Documents were illegible"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>

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
              {loading ? 'Processing…' : 'Approve re-upload'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
