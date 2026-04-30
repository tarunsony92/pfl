/**
 * StageBadge — maps a CaseStage to a colored badge.
 *
 * Uses the Badge UI primitive + cn() for conditional classes.
 * Covers all 14 CaseStage values from @/lib/enums.
 */

import React from 'react'
import { cn } from '@/lib/cn'
import type { CaseStage } from '@/lib/enums'

interface StageBadgeProps {
  stage: CaseStage
  /**
   * When > 0, the badge renders red regardless of the pipeline stage —
   * "P1 COMPLETE · 46 issues" is NOT a green outcome, it's a flag for
   * the MD to work through. The badge flips back to the stage-derived
   * colour (green for completed states, amber for in-flight, etc.)
   * only when every issue is resolved.
   */
  openIssueCount?: number
  className?: string
}

/**
 * Short display labels for each stage.
 */
const STAGE_LABELS: Record<CaseStage, string> = {
  UPLOADED: 'UPLOADED',
  CHECKLIST_VALIDATION: 'VALIDATING',
  CHECKLIST_MISSING_DOCS: 'MISSING DOCS',
  CHECKLIST_VALIDATED: 'VALIDATED',
  INGESTED: 'INGESTED',
  PHASE_1_DECISIONING: 'DECISIONING',
  PHASE_1_REJECTED: 'P1 REJECTED',
  PHASE_1_COMPLETE: 'P1 COMPLETE',
  PHASE_2_AUDITING: 'AUDITING',
  PHASE_2_COMPLETE: 'P2 COMPLETE',
  HUMAN_REVIEW: 'HUMAN REVIEW',
  APPROVED: 'APPROVED',
  REJECTED: 'REJECTED',
  ESCALATED_TO_CEO: 'ESCALATED',
}

/**
 * Tailwind classes per stage — bg + text combos.
 */
const STAGE_CLASSES: Record<CaseStage, string> = {
  // Gray — neutral / initial upload
  UPLOADED: 'bg-slate-100 text-slate-700',

  // Amber — in-flight pipeline stages
  CHECKLIST_VALIDATION: 'bg-amber-100 text-amber-800',
  PHASE_1_DECISIONING: 'bg-amber-100 text-amber-800',
  PHASE_2_AUDITING: 'bg-amber-100 text-amber-800',
  HUMAN_REVIEW: 'bg-amber-100 text-amber-800',

  // Red — blocking / rejected
  CHECKLIST_MISSING_DOCS: 'bg-red-100 text-red-700',
  PHASE_1_REJECTED: 'bg-red-100 text-red-700',
  REJECTED: 'bg-red-200 text-red-900',

  // Blue / indigo — completed sub-steps
  CHECKLIST_VALIDATED: 'bg-blue-100 text-blue-800',
  INGESTED: 'bg-indigo-100 text-indigo-800',

  // Green — successful completions
  PHASE_1_COMPLETE: 'bg-green-100 text-green-800',
  PHASE_2_COMPLETE: 'bg-emerald-100 text-emerald-800',
  APPROVED: 'bg-green-200 text-green-900',

  // Pink — escalation
  ESCALATED_TO_CEO: 'bg-pink-100 text-pink-800',
}

export function StageBadge({
  stage,
  openIssueCount,
  className,
}: StageBadgeProps) {
  const hasUnresolvedIssues = (openIssueCount ?? 0) > 0
  const label = STAGE_LABELS[stage] ?? stage
  // Red override wins: a pipeline that shows "COMPLETE" while there are
  // 46 unresolved CRITICALs is misleading. The green colour is earned by
  // zeroing the queue.
  const colorClasses = hasUnresolvedIssues
    ? 'bg-red-100 text-red-700'
    : STAGE_CLASSES[stage] ?? 'bg-slate-100 text-slate-700'

  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold',
        colorClasses,
        className,
      )}
      title={
        hasUnresolvedIssues
          ? `${openIssueCount} unresolved issue${openIssueCount === 1 ? '' : 's'} — badge turns green when the queue is empty`
          : undefined
      }
    >
      {label}
      {hasUnresolvedIssues && (
        <span className="ml-1.5 font-bold">· {openIssueCount}</span>
      )}
    </span>
  )
}
