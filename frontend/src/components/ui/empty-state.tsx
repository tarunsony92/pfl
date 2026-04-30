import React from 'react'
import { cn } from '@/lib/cn'

interface EmptyStateProps {
  /** Lucide icon component or any React node */
  icon?: React.ReactNode
  heading: string
  subtext?: string
  /** Optional CTA button / link element */
  action?: React.ReactNode
  className?: string
}

/**
 * Reusable empty-state card.
 *
 * Usage:
 * ```tsx
 * <EmptyState
 *   icon={<FolderOpenIcon className="h-8 w-8" />}
 *   heading="No cases found"
 *   subtext="Adjust your filters or create a new case."
 *   action={<Button onClick={onClear}>Clear filters</Button>}
 * />
 * ```
 */
export function EmptyState({ icon, heading, subtext, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-pfl-slate-200 bg-pfl-slate-50 px-6 py-12 text-center',
        className,
      )}
      role="status"
      aria-label={heading}
    >
      {icon && (
        <span className="text-pfl-slate-300" aria-hidden="true">
          {icon}
        </span>
      )}
      <div className="flex flex-col items-center gap-1">
        <p className="text-sm font-semibold text-pfl-slate-700">{heading}</p>
        {subtext && <p className="max-w-xs text-xs text-pfl-slate-500">{subtext}</p>}
      </div>
      {action && <div className="mt-1">{action}</div>}
    </div>
  )
}
