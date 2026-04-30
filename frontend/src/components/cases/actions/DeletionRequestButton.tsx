'use client'

/**
 * DeletionRequestButton — case-detail header action for the two-step
 * MD-approval delete flow (backend ``case.request_deletion`` /
 * ``case.approve_deletion`` / ``case.reject_deletion``).
 *
 * Renders different UI depending on the current case + actor state:
 *
 *   1. **Clean case, any user** → "Request deletion" button → modal with
 *      reason textarea → POST request-deletion.
 *   2. **Pending request, non-MD viewer** → orange "Deletion pending"
 *      pill showing requester + reason + ts (read-only).
 *   3. **Pending request, MD viewer (ADMIN / CEO)** → orange pill PLUS
 *      Approve / Reject buttons → modal → POST approve-deletion or
 *      reject-deletion.
 *
 * After every successful action, ``mutateCase`` re-fetches so the
 * header re-renders with the new state immediately.
 */

import React, { useState } from 'react'
import { Trash2Icon, CheckIcon, XIcon, Loader2Icon } from 'lucide-react'
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

interface DeletionRequestButtonProps {
  caseData: CaseRead
  // ADMIN + CEO are treated as "MD" — backend enforces, this just hides
  // the approve/reject buttons from non-MD viewers so they don't get a
  // 403 toast on click.
  isAdmin: boolean
  mutateCase: KeyedMutator<CaseRead>
}

export function DeletionRequestButton({
  caseData,
  isAdmin,
  mutateCase,
}: DeletionRequestButtonProps) {
  const isPending = !!caseData.deletion_requested_at
  const [requestOpen, setRequestOpen] = useState(false)
  const [approveOpen, setApproveOpen] = useState(false)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [rationale, setRationale] = useState('')
  const [busy, setBusy] = useState<'request' | 'approve' | 'reject' | null>(null)

  async function handleRequest() {
    if (reason.trim().length < 5) {
      toast({
        title: 'Reason too short',
        description: 'Please give the MD at least a few words of context (5+ chars).',
        variant: 'destructive',
      })
      return
    }
    setBusy('request')
    try {
      await casesApi.requestDeletion(caseData.id, reason.trim())
      toast({
        title: 'Deletion request filed',
        description:
          'An MD has been notified. The case stays accessible until they approve.',
      })
      setRequestOpen(false)
      setReason('')
      await mutateCase()
    } catch (e) {
      toast({
        title: 'Failed to request deletion',
        description: e instanceof Error ? e.message : 'Unexpected error',
        variant: 'destructive',
      })
    } finally {
      setBusy(null)
    }
  }

  async function handleApprove() {
    setBusy('approve')
    try {
      await casesApi.approveDeletion(caseData.id)
      toast({
        title: 'Case deleted',
        description: 'The case has been soft-deleted and removed from the active list.',
      })
      setApproveOpen(false)
      // The case is now is_deleted=true; the cases-list filter will hide
      // it on the next refetch. Fall back to optimistic mutate; the page
      // route may also redirect on its own after this.
      await mutateCase()
    } catch (e) {
      toast({
        title: 'Failed to approve deletion',
        description: e instanceof Error ? e.message : 'Unexpected error',
        variant: 'destructive',
      })
    } finally {
      setBusy(null)
    }
  }

  async function handleReject() {
    if (rationale.trim().length < 5) {
      toast({
        title: 'Rationale too short',
        description: 'Please record why this deletion is being rejected (5+ chars).',
        variant: 'destructive',
      })
      return
    }
    setBusy('reject')
    try {
      await casesApi.rejectDeletion(caseData.id, rationale.trim())
      toast({
        title: 'Deletion request rejected',
        description: 'The pending request has been cleared. The case stays active.',
      })
      setRejectOpen(false)
      setRationale('')
      await mutateCase()
    } catch (e) {
      toast({
        title: 'Failed to reject deletion',
        description: e instanceof Error ? e.message : 'Unexpected error',
        variant: 'destructive',
      })
    } finally {
      setBusy(null)
    }
  }

  if (!isPending) {
    return (
      <>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setRequestOpen(true)}
          className="border-red-300 text-red-700 hover:bg-red-50"
        >
          <Trash2Icon className="h-3.5 w-3.5 mr-1.5" /> Request deletion
        </Button>
        <Dialog open={requestOpen} onOpenChange={setRequestOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Request case deletion</DialogTitle>
              <DialogDescription>
                The case stays visible until an MD approves. Tell them why this
                file should be removed (5+ characters).
              </DialogDescription>
            </DialogHeader>
            <textarea
              className="w-full mt-3 rounded border border-pfl-slate-300 p-2 text-sm min-h-[88px]"
              placeholder="e.g. Branch uploaded the wrong ZIP — re-uploading under loan ID 10006xxx."
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={500}
              autoFocus
            />
            <div className="mt-3 flex justify-end gap-2">
              <DialogClose asChild>
                <Button variant="outline" size="sm">Cancel</Button>
              </DialogClose>
              <Button
                size="sm"
                onClick={handleRequest}
                disabled={busy === 'request'}
                className="bg-red-700 hover:bg-red-800 text-white"
              >
                {busy === 'request' ? (
                  <Loader2Icon className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                ) : (
                  <Trash2Icon className="h-3.5 w-3.5 mr-1.5" />
                )}
                Submit request
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </>
    )
  }

  // Pending request branch — show pill + (for MD) approve / reject controls.
  return (
    <div className="inline-flex items-center gap-2">
      <span
        className="inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-[11px] font-semibold border border-amber-400 bg-amber-50 text-amber-800"
        title={
          caseData.deletion_reason
            ? `Reason: ${caseData.deletion_reason}`
            : undefined
        }
      >
        <Trash2Icon className="h-3 w-3" /> DELETION PENDING
      </span>

      {isAdmin && (
        <>
          <Button
            size="sm"
            onClick={() => setApproveOpen(true)}
            className="bg-red-700 hover:bg-red-800 text-white"
          >
            <CheckIcon className="h-3.5 w-3.5 mr-1.5" /> Approve delete
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setRejectOpen(true)}
            className="border-pfl-slate-300"
          >
            <XIcon className="h-3.5 w-3.5 mr-1.5" /> Reject
          </Button>

          <Dialog open={approveOpen} onOpenChange={setApproveOpen}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Approve deletion</DialogTitle>
                <DialogDescription>
                  This soft-deletes the case immediately. It will disappear from
                  the active cases list and stop appearing in MD / Assessor
                  queues. Audit log entries are preserved.
                </DialogDescription>
              </DialogHeader>
              {caseData.deletion_reason && (
                <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-3 text-[12.5px] text-pfl-slate-800 mt-2">
                  <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
                    Requester reason
                  </div>
                  {caseData.deletion_reason}
                </div>
              )}
              <div className="mt-3 flex justify-end gap-2">
                <DialogClose asChild>
                  <Button variant="outline" size="sm">Cancel</Button>
                </DialogClose>
                <Button
                  size="sm"
                  onClick={handleApprove}
                  disabled={busy === 'approve'}
                  className="bg-red-700 hover:bg-red-800 text-white"
                >
                  {busy === 'approve' ? (
                    <Loader2Icon className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                  ) : (
                    <CheckIcon className="h-3.5 w-3.5 mr-1.5" />
                  )}
                  Approve & delete
                </Button>
              </div>
            </DialogContent>
          </Dialog>

          <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Reject deletion request</DialogTitle>
                <DialogDescription>
                  The case stays active. Your rationale is recorded in the
                  audit log so the requester knows why.
                </DialogDescription>
              </DialogHeader>
              <textarea
                className="w-full mt-3 rounded border border-pfl-slate-300 p-2 text-sm min-h-[88px]"
                placeholder="e.g. Case is already disbursed — cannot delete."
                value={rationale}
                onChange={(e) => setRationale(e.target.value)}
                maxLength={500}
                autoFocus
              />
              <div className="mt-3 flex justify-end gap-2">
                <DialogClose asChild>
                  <Button variant="outline" size="sm">Cancel</Button>
                </DialogClose>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleReject}
                  disabled={busy === 'reject'}
                >
                  {busy === 'reject' ? (
                    <Loader2Icon className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                  ) : (
                    <XIcon className="h-3.5 w-3.5 mr-1.5" />
                  )}
                  Submit rejection
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        </>
      )}
    </div>
  )
}
