'use client'

/**
 * DiscrepancyBanner — surfaces unresolved CAM discrepancy counts on the
 * Overview tab. Self-quieting: renders nothing when there are no open
 * flags, a red banner when CRITICAL unresolved (Phase 1 blocked), an
 * amber banner when only WARNING unresolved.
 *
 * Clicking the banner scrolls / navigates the user to the Discrepancies
 * tab via the onGoToTab callback (keeps the nav logic out of this leaf
 * component so the parent page can drive Tabs state).
 */

import React from 'react'
import { AlertTriangleIcon, XCircleIcon } from 'lucide-react'
import { useCamDiscrepancies } from '@/lib/useCamDiscrepancies'

interface DiscrepancyBannerProps {
  caseId: string
  onGoToTab?: () => void
}

export function DiscrepancyBanner({ caseId, onGoToTab }: DiscrepancyBannerProps) {
  const { data: summary } = useCamDiscrepancies(caseId, { refreshInterval: 0 })
  if (!summary) return null
  const { unresolved_critical, unresolved_warning, phase1_blocked } = summary
  if (unresolved_critical === 0 && unresolved_warning === 0) return null

  const tone = phase1_blocked
    ? {
        wrapper: 'border-red-300 bg-red-50',
        icon: <XCircleIcon className="h-5 w-5 text-red-700 mt-0.5 shrink-0" aria-hidden="true" />,
        title: 'text-red-900',
        label: `${unresolved_critical} CRITICAL CAM discrepanc${unresolved_critical === 1 ? 'y' : 'ies'} must be resolved`,
        sub: 'Phase 1 decisioning is blocked until every CRITICAL conflict between the finpage-authoritative SystemCam sheet and the manually-filled CM CAM IL sheet is either corrected or justified with an assessor comment.',
      }
    : {
        wrapper: 'border-amber-300 bg-amber-50',
        icon: <AlertTriangleIcon className="h-5 w-5 text-amber-700 mt-0.5 shrink-0" aria-hidden="true" />,
        title: 'text-amber-900',
        label: `${unresolved_warning} CAM warning${unresolved_warning === 1 ? '' : 's'} pending review`,
        sub: 'Phase 1 is NOT blocked. SystemCam (finpage) and CM CAM IL (manual) differ on a non-critical field; resolve or justify before closing the case.',
      }

  return (
    <div
      className={`mb-4 rounded-lg border p-3 flex items-start gap-3 ${tone.wrapper}`}
      data-testid="discrepancy-banner"
      role="alert"
    >
      {tone.icon}
      <div className="flex-1 min-w-0">
        <p className={`text-sm font-semibold ${tone.title}`}>{tone.label}</p>
        <p className="text-xs text-slate-700 mt-0.5">{tone.sub}</p>
      </div>
      {onGoToTab && (
        <button
          type="button"
          className="text-xs font-semibold text-pfl-blue-700 hover:underline shrink-0"
          onClick={onGoToTab}
          data-testid="discrepancy-banner-jump"
        >
          Review →
        </button>
      )}
    </div>
  )
}
