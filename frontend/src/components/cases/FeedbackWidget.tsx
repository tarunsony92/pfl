'use client'

/**
 * FeedbackWidget — human verdict (Approve / Needs Revision / Reject) + notes.
 *
 * Placed below all tabs on the case detail page. Visible to all authenticated users.
 * Submits feedback to POST /cases/{id}/feedback and auto-refreshes the list via SWR.
 *
 * M4: §7 phase 1 — feedback for AI learning.
 */

import React, { useState } from 'react'
import useSWR from 'swr'
import { CheckIcon, EditIcon, XIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { toast } from '@/components/ui/use-toast'
import { cases as casesApi } from '@/lib/api'
import { cn } from '@/lib/cn'
import type { FeedbackRead } from '@/lib/types'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Verdict = 'APPROVE' | 'NEEDS_REVISION' | 'REJECT'

interface FeedbackWidgetProps {
  caseId: string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const VERDICT_CONFIG: Record<
  Verdict,
  {
    label: string
    icon: React.ReactNode
    activeClass: string
    inactiveClass: string
  }
> = {
  APPROVE: {
    label: 'Approve',
    icon: <CheckIcon className="h-4 w-4" aria-hidden="true" />,
    activeClass: 'bg-green-600 text-white border-green-600',
    inactiveClass: 'border-pfl-slate-300 text-pfl-slate-700 hover:border-green-400 hover:text-green-700',
  },
  NEEDS_REVISION: {
    label: 'Needs Revision',
    icon: <EditIcon className="h-4 w-4" aria-hidden="true" />,
    activeClass: 'bg-amber-500 text-white border-amber-500',
    inactiveClass: 'border-pfl-slate-300 text-pfl-slate-700 hover:border-amber-400 hover:text-amber-700',
  },
  REJECT: {
    label: 'Reject',
    icon: <XIcon className="h-4 w-4" aria-hidden="true" />,
    activeClass: 'bg-red-600 text-white border-red-600',
    inactiveClass: 'border-pfl-slate-300 text-pfl-slate-700 hover:border-red-400 hover:text-red-700',
  },
}

const VERDICT_BADGE: Record<Verdict, string> = {
  APPROVE: 'bg-green-100 text-green-800',
  NEEDS_REVISION: 'bg-amber-100 text-amber-800',
  REJECT: 'bg-red-100 text-red-800',
}

function formatRelative(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function FeedbackWidget({ caseId }: FeedbackWidgetProps) {
  const [selectedVerdict, setSelectedVerdict] = useState<Verdict | null>(null)
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const {
    data: feedbackList,
    isLoading,
    mutate,
  } = useSWR<FeedbackRead[]>(
    caseId ? ['feedback', caseId] : null,
    () => casesApi.listFeedback(caseId),
    { dedupingInterval: 10_000 },
  )

  async function handleSubmit() {
    if (!selectedVerdict) {
      toast({ title: 'Select a verdict', description: 'Please choose Approve, Needs Revision, or Reject.', variant: 'destructive' })
      return
    }
    setSubmitting(true)
    try {
      await casesApi.submitFeedback(caseId, {
        verdict: selectedVerdict,
        notes: notes.trim() || undefined,
        phase: 'phase1',
      })
      toast({ title: 'Feedback submitted', description: `Verdict: ${selectedVerdict.replace('_', ' ')}` })
      setSelectedVerdict(null)
      setNotes('')
      await mutate()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to submit feedback'
      toast({ title: 'Error', description: msg, variant: 'destructive' })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card className="mt-6 border-pfl-slate-200">
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-semibold text-pfl-slate-900">
          Your Feedback <span className="text-xs font-normal text-pfl-slate-500 ml-1">(AI Learning)</span>
        </CardTitle>
        <p className="text-xs text-pfl-slate-500 mt-0.5">
          Help train the AI by submitting your verdict. Each submission is recorded and used to improve future recommendations.
        </p>
      </CardHeader>

      <CardContent>
        {/* Verdict buttons */}
        <div className="flex flex-wrap gap-3 mb-4">
          {(['APPROVE', 'NEEDS_REVISION', 'REJECT'] as Verdict[]).map((v) => {
            const cfg = VERDICT_CONFIG[v]
            const isActive = selectedVerdict === v
            return (
              <button
                key={v}
                type="button"
                onClick={() => setSelectedVerdict(isActive ? null : v)}
                className={cn(
                  'flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pfl-blue-600',
                  isActive ? cfg.activeClass : cfg.inactiveClass,
                )}
                aria-pressed={isActive}
              >
                {cfg.icon}
                {cfg.label}
              </button>
            )
          })}
        </div>

        {/* Notes textarea */}
        <div className="mb-4">
          <label htmlFor="feedback-notes" className="block text-xs font-medium text-pfl-slate-600 mb-1">
            Notes <span className="font-normal text-pfl-slate-400">(optional)</span>
          </label>
          <textarea
            id="feedback-notes"
            className="w-full rounded-md border border-pfl-slate-300 px-3 py-2 text-sm text-pfl-slate-900 placeholder:text-pfl-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pfl-blue-600 resize-y min-h-[80px]"
            placeholder="Add context, concerns, or observations for the AI…"
            maxLength={4000}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <p className="mt-0.5 text-xs text-pfl-slate-400 text-right">{notes.length}/4000</p>
        </div>

        {/* Submit */}
        <div className="flex justify-end">
          <Button
            onClick={handleSubmit}
            disabled={submitting || !selectedVerdict}
            className="min-w-[120px]"
          >
            {submitting ? 'Submitting…' : 'Submit Feedback'}
          </Button>
        </div>

        {/* Recent feedbacks */}
        {feedbackList && feedbackList.length > 0 && (
          <div className="mt-6">
            <p className="text-xs font-semibold text-pfl-slate-500 uppercase tracking-wide mb-3">
              Recent Feedback
            </p>
            <ul className="flex flex-col gap-2">
              {feedbackList.slice(0, 5).map((fb) => (
                <li
                  key={fb.id}
                  className="flex items-start gap-3 rounded-md border border-pfl-slate-100 bg-pfl-slate-50 px-3 py-2"
                >
                  <span
                    className={cn(
                      'inline-flex shrink-0 items-center rounded px-1.5 py-0.5 text-xs font-semibold mt-0.5',
                      VERDICT_BADGE[fb.verdict as Verdict] ?? 'bg-pfl-slate-100 text-pfl-slate-700',
                    )}
                  >
                    {fb.verdict.replace('_', ' ')}
                  </span>
                  <div className="flex-1 min-w-0">
                    {fb.notes && (
                      <p className="text-xs text-pfl-slate-700 truncate">{fb.notes}</p>
                    )}
                    <p className="text-xs text-pfl-slate-400">
                      {formatRelative(fb.created_at)}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {isLoading && (
          <p className="mt-4 text-xs text-pfl-slate-400 italic">Loading feedback…</p>
        )}
      </CardContent>
    </Card>
  )
}
