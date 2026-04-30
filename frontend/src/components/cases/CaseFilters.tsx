'use client'

/**
 * CaseFilters — sticky filter bar for the Cases list page.
 *
 * Props:
 *   filters     — current filter state
 *   onChange    — called with a partial update
 *   onClear     — reset all filters
 *   users       — list of users (admins only); omit/null to hide "Uploaded by"
 */

import React from 'react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { CaseStages } from '@/lib/enums'
import type { CaseStage } from '@/lib/enums'
import type { UserRead } from '@/lib/types'
import type { CaseListFilters } from '@/lib/api'

interface CaseFiltersProps {
  filters: CaseListFilters
  onChange: (partial: Partial<CaseListFilters>) => void
  onClear: () => void
  /** Pass a list of users to show the "Uploaded by" dropdown (admin+ only). */
  users?: UserRead[] | null
}

/** Friendly label for each CaseStage in the dropdown. */
const STAGE_SELECT_LABELS: Record<CaseStage, string> = {
  UPLOADED: 'Uploaded',
  CHECKLIST_VALIDATION: 'Checklist Validation',
  CHECKLIST_MISSING_DOCS: 'Missing Docs',
  CHECKLIST_VALIDATED: 'Checklist Validated',
  INGESTED: 'Ingested',
  PHASE_1_DECISIONING: 'Phase 1 Decisioning',
  PHASE_1_REJECTED: 'Phase 1 Rejected',
  PHASE_1_COMPLETE: 'Phase 1 Complete',
  PHASE_2_AUDITING: 'Phase 2 Auditing',
  PHASE_2_COMPLETE: 'Phase 2 Complete',
  HUMAN_REVIEW: 'Human Review',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  ESCALATED_TO_CEO: 'Escalated to CEO',
}

export function CaseFilters({ filters, onChange, onClear, users }: CaseFiltersProps) {
  return (
    <div
      className="sticky top-0 z-10 bg-white border-b border-pfl-slate-200 px-6 py-3"
      data-testid="case-filters"
    >
      <div className="flex flex-wrap gap-3 items-end">
        {/* Stage select */}
        <div className="flex flex-col gap-1">
          <label
            htmlFor="filter-stage"
            className="text-xs font-medium text-pfl-slate-600"
          >
            Stage
          </label>
          <select
            id="filter-stage"
            value={filters.stage ?? ''}
            onChange={(e) =>
              onChange({ stage: e.target.value || undefined })
            }
            className="h-9 rounded border border-pfl-slate-300 bg-white px-3 text-sm text-pfl-slate-900 focus:outline-none focus:ring-2 focus:ring-pfl-blue-600"
          >
            <option value="">All stages</option>
            {CaseStages.map((s) => (
              <option key={s} value={s}>
                {STAGE_SELECT_LABELS[s]}
              </option>
            ))}
          </select>
        </div>

        {/* Uploaded by — admin-only */}
        {users && users.length > 0 && (
          <div className="flex flex-col gap-1">
            <label
              htmlFor="filter-uploaded-by"
              className="text-xs font-medium text-pfl-slate-600"
            >
              Uploaded by
            </label>
            <select
              id="filter-uploaded-by"
              value={filters.uploaded_by ?? ''}
              onChange={(e) =>
                onChange({ uploaded_by: e.target.value || undefined })
              }
              className="h-9 rounded border border-pfl-slate-300 bg-white px-3 text-sm text-pfl-slate-900 focus:outline-none focus:ring-2 focus:ring-pfl-blue-600"
            >
              <option value="">All users</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name || u.email}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* From date */}
        <div className="flex flex-col gap-1">
          <label
            htmlFor="filter-from"
            className="text-xs font-medium text-pfl-slate-600"
          >
            From
          </label>
          <input
            id="filter-from"
            type="date"
            value={filters.from_date ?? ''}
            onChange={(e) =>
              onChange({ from_date: e.target.value || undefined })
            }
            className="h-9 rounded border border-pfl-slate-300 bg-white px-3 text-sm text-pfl-slate-900 focus:outline-none focus:ring-2 focus:ring-pfl-blue-600"
          />
        </div>

        {/* To date */}
        <div className="flex flex-col gap-1">
          <label
            htmlFor="filter-to"
            className="text-xs font-medium text-pfl-slate-600"
          >
            To
          </label>
          <input
            id="filter-to"
            type="date"
            value={filters.to_date ?? ''}
            onChange={(e) =>
              onChange({ to_date: e.target.value || undefined })
            }
            className="h-9 rounded border border-pfl-slate-300 bg-white px-3 text-sm text-pfl-slate-900 focus:outline-none focus:ring-2 focus:ring-pfl-blue-600"
          />
        </div>

        {/* Loan ID search */}
        <div className="flex flex-col gap-1">
          <label
            htmlFor="filter-search"
            className="text-xs font-medium text-pfl-slate-600"
          >
            Loan ID
          </label>
          <Input
            id="filter-search"
            type="text"
            placeholder="Search loan ID…"
            value={filters.loan_id_prefix ?? ''}
            onChange={(e) =>
              onChange({ loan_id_prefix: e.target.value || undefined })
            }
            className="h-9 w-48"
          />
        </div>

        {/* Clear button */}
        <Button
          variant="outline"
          size="sm"
          onClick={onClear}
          className="self-end"
          data-testid="clear-filters"
        >
          Clear filters
        </Button>
      </div>
    </div>
  )
}
