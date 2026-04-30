import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'

const badgeVariants = cva(
  'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold transition-colors',
  {
    variants: {
      variant: {
        default: 'bg-pfl-blue-100 text-pfl-blue-800',
        // Case stages
        UPLOADED: 'bg-pfl-slate-100 text-pfl-slate-700',
        CHECKLIST_VALIDATION: 'bg-yellow-100 text-yellow-800',
        CHECKLIST_MISSING_DOCS: 'bg-orange-100 text-orange-800',
        CHECKLIST_VALIDATED: 'bg-blue-100 text-blue-800',
        INGESTED: 'bg-indigo-100 text-indigo-800',
        PHASE_1_DECISIONING: 'bg-purple-100 text-purple-800',
        PHASE_1_REJECTED: 'bg-red-100 text-red-700',
        PHASE_1_COMPLETE: 'bg-green-100 text-green-800',
        PHASE_2_AUDITING: 'bg-teal-100 text-teal-800',
        PHASE_2_COMPLETE: 'bg-emerald-100 text-emerald-800',
        HUMAN_REVIEW: 'bg-amber-100 text-amber-800',
        APPROVED: 'bg-green-200 text-green-900',
        REJECTED: 'bg-red-200 text-red-900',
        ESCALATED_TO_CEO: 'bg-pink-100 text-pink-800',
        // Misc
        outline: 'border border-pfl-slate-300 text-pfl-slate-700',
        destructive: 'bg-red-100 text-red-800',
        success: 'bg-green-100 text-green-800',
        warning: 'bg-yellow-100 text-yellow-800',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
