'use client'

/**
 * DeletionRowAction — compact per-row action for the cases list table.
 *
 * Renders as a single icon button whose behaviour depends on the
 * current case state:
 *   - Clean case → red trash icon → modal with reason → POST
 *     request-deletion → refetch list.
 *   - Pending request, non-MD viewer → orange "PENDING" pill (read-only,
 *     links to the case-detail page for context).
 *   - Pending request, MD viewer → pill + approve/reject split button
 *     with the same modals the case-detail header uses.
 *
 * Smaller visual footprint than ``DeletionRequestButton`` because the
 * cases list has eight columns and every row needs room — we lean on
 * icons + tooltips and defer the full label to the case-detail header.
 */

import React, { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Trash2Icon, CheckIcon, XIcon, Loader2Icon, ClockIcon } from 'lucide-react'
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
import { useAuth } from '@/components/auth/useAuth'
import type { CaseRead } from '@/lib/types'

interface DeletionRowActionProps {
  caseData: CaseRead
  onChanged?: () => void
}

export function DeletionRowAction({ caseData, onChanged }: DeletionRowActionProps) {
  const { user } = useAuth()
  const isMD = user?.role === 'admin' || user?.role === 'ceo'
  const isPending = !!caseData.deletion_requested_at

  const [requestOpen, setRequestOpen] = useState(false)
  const [approveOpen, setApproveOpen] = useState(false)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [rationale, setRationale] = useState('')
  const [busy, setBusy] = useState<'request' | 'approve' | 'reject' | null>(null)
  const router = useRouter()

  async function handleRequest() {
    if (reason.trim().length < 5) {
      toast({
        title: 'Reason too short',
        description: 'Please give the MD at least a few words (5+ chars).',
        variant: 'destructive',
      })
      return
    }
    setBusy('request')
    try {
      await casesApi.requestDeletion(caseData.id, reason.trim())
      toast({
        title: 'Deletion request filed',
        description: 'An MD will review. Case stays active until approved.',
      })
      setRequestOpen(false)
      setReason('')
      onChanged?.()
    } catch (e) {
      toast({
        title: 'Failed',
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
        description: `${caseData.loan_id} removed from active list.`,
      })
      setApproveOpen(false)
      onChanged?.()
    } catch (e) {
      toast({
        title: 'Failed',
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
        description: 'Please record why (5+ chars).',
        variant: 'destructive',
      })
      return
    }
    setBusy('reject')
    try {
      await casesApi.rejectDeletion(caseData.id, rationale.trim())
      toast({
        title: 'Rejected',
        description: 'Pending request cleared. Case stays active.',
      })
      setRejectOpen(false)
      setRationale('')
      onChanged?.()
    } catch (e) {
      toast({
        title: 'Failed',
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
        <button
          type="button"
          onClick={() => setRequestOpen(true)}
          title={`Request deletion of ${caseData.loan_id}`}
          className="inline-flex items-center justify-center h-7 w-7 rounded border border-pfl-slate-200 text-pfl-slate-500 hover:border-red-400 hover:text-red-700 hover:bg-red-50 transition-colors"
        >
          <Trash2Icon className="h-3.5 w-3.5" aria-hidden />
          <span className="sr-only">Request deletion</span>
        </button>
        <Dialog open={requestOpen} onOpenChange={setRequestOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Request deletion · {caseData.loan_id}</DialogTitle>
              <DialogDescription>
                The case stays active until an MD approves. Record why (5+ chars).
              </DialogDescription>
            </DialogHeader>
            <textarea
              className="w-full mt-3 rounded border border-pfl-slate-300 p-2 text-sm min-h-[80px]"
              placeholder="e.g. Branch uploaded wrong ZIP — re-uploading under correct loan ID."
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
                Submit
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </>
    )
  }

  // Pending state — show amber pending pill, plus MD-only action icons.
  return (
    <div className="inline-flex items-center gap-1">
      {isMD ? (
        <>
          <button
            type="button"
            onClick={() => setApproveOpen(true)}
            title="Approve deletion"
            className="inline-flex items-center justify-center h-7 w-7 rounded border border-red-300 text-red-700 hover:bg-red-50 transition-colors"
          >
            <CheckIcon className="h-3.5 w-3.5" aria-hidden />
            <span className="sr-only">Approve deletion</span>
          </button>
          <button
            type="button"
            onClick={() => setRejectOpen(true)}
            title="Reject deletion request"
            className="inline-flex items-center justify-center h-7 w-7 rounded border border-pfl-slate-300 text-pfl-slate-600 hover:bg-pfl-slate-50 transition-colors"
          >
            <XIcon className="h-3.5 w-3.5" aria-hidden />
            <span className="sr-only">Reject deletion</span>
          </button>
        </>
      ) : (
        <button
          type="button"
          onClick={() => router.push(`/cases/${caseData.id}`)}
          title={
            caseData.deletion_reason
              ? `Deletion pending · ${caseData.deletion_reason}`
              : 'Deletion request pending MD approval'
          }
          className="inline-flex items-center gap-1 rounded px-2 h-7 text-[10.5px] font-semibold border border-amber-400 bg-amber-50 text-amber-800"
        >
          <ClockIcon className="h-3 w-3" aria-hidden /> PENDING
        </button>
      )}

      {/* MD approve modal */}
      <Dialog open={approveOpen} onOpenChange={setApproveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Approve deletion · {caseData.loan_id}</DialogTitle>
            <DialogDescription>
              Soft-deletes the case immediately. It disappears from the active
              list and MD / Assessor queues. Audit log is preserved.
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

      {/* MD reject modal */}
      <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject deletion · {caseData.loan_id}</DialogTitle>
            <DialogDescription>
              Case stays active. Your rationale goes into the audit log.
            </DialogDescription>
          </DialogHeader>
          <textarea
            className="w-full mt-3 rounded border border-pfl-slate-300 p-2 text-sm min-h-[80px]"
            placeholder="e.g. Case already disbursed — cannot delete."
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
    </div>
  )
}
