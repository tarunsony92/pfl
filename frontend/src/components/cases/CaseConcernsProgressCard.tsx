'use client'

/**
 * CaseConcernsProgressCard — at-a-glance "how close is this case to the
 * final verdict report?" indicator on the Overview tab.
 *
 * Reads `useVerificationOverview` for live counts of LevelIssue rows by
 * status. The final-report endpoint won't emit a PDF until every concern
 * is settled (MD_APPROVED / MD_REJECTED), so this is the same gate the
 * backend enforces — surfaced as a progress bar.
 */

import React from 'react'
import {
  ShieldCheckIcon,
  CheckCircle2Icon,
  ClockIcon,
  CircleIcon,
  XCircleIcon,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useVerificationOverview } from '@/lib/useVerification'

interface Props {
  caseId: string
}

export function CaseConcernsProgressCard({ caseId }: Props) {
  const { data, isLoading } = useVerificationOverview(caseId)

  const open = data?.open_issue_count ?? 0
  const awaiting = data?.awaiting_md_count ?? 0
  const approved = data?.md_approved_count ?? 0
  const rejected = data?.md_rejected_count ?? 0
  const total = open + awaiting + approved + rejected
  const settled = approved + rejected
  const pct = total === 0 ? 0 : Math.round((settled / total) * 100)
  const allSettled = total > 0 && settled === total

  return (
    <Card className="mb-6">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-semibold text-pfl-slate-900 flex items-center gap-2">
            <ShieldCheckIcon className="h-4 w-4 text-pfl-slate-500" />
            <span>Concerns Resolution</span>
          </CardTitle>
          {!isLoading && total > 0 && (
            <span
              className={
                'text-xs font-semibold tabular-nums ' +
                (allSettled ? 'text-emerald-700' : 'text-pfl-slate-700')
              }
            >
              {settled}/{total} settled · {pct}%
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-[12.5px] text-pfl-slate-500">Loading concerns…</p>
        ) : total === 0 ? (
          <p className="text-[12.5px] text-pfl-slate-600 leading-relaxed">
            No concerns have been raised on this case yet — the verification
            engines have either not been run or every gate passed cleanly.
          </p>
        ) : (
          <>
            {/* Stacked progress bar — green (approved) + red (rejected) on the
                left, amber (awaiting MD) in the middle, slate (open) on the
                right. The split rendering matches the gate semantics: red
                rejections still count as settled even though they block the
                verdict. */}
            <div className="h-2.5 w-full rounded-full bg-pfl-slate-100 overflow-hidden flex">
              <Segment color="bg-emerald-500" pct={pctOf(approved, total)} />
              <Segment color="bg-red-500" pct={pctOf(rejected, total)} />
              <Segment color="bg-amber-400" pct={pctOf(awaiting, total)} />
              <Segment color="bg-pfl-slate-300" pct={pctOf(open, total)} />
            </div>

            {/* Breakdown chips */}
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-[12px]">
              <Chip
                icon={<CheckCircle2Icon className="h-3.5 w-3.5" />}
                label="Approved (MD/AI)"
                count={approved}
                cls="text-emerald-700"
              />
              <Chip
                icon={<XCircleIcon className="h-3.5 w-3.5" />}
                label="Rejected"
                count={rejected}
                cls="text-red-700"
              />
              <Chip
                icon={<ClockIcon className="h-3.5 w-3.5" />}
                label="Awaiting MD"
                count={awaiting}
                cls="text-amber-700"
              />
              <Chip
                icon={<CircleIcon className="h-3.5 w-3.5" />}
                label="Open"
                count={open}
                cls="text-pfl-slate-600"
              />
            </div>

            <p
              className={
                'mt-3 text-[12px] leading-relaxed ' +
                (allSettled ? 'text-emerald-800' : 'text-pfl-slate-600')
              }
            >
              {allSettled ? (
                <>
                  All {total} concerns settled — the case is ready for the final
                  verdict report.
                </>
              ) : (
                <>
                  Of {total} concern{total === 1 ? '' : 's'} raised, {settled}{' '}
                  {settled === 1 ? 'is' : 'are'} settled. {open + awaiting}{' '}
                  still {open + awaiting === 1 ? 'needs' : 'need'} adjudication
                  before the final verdict report can be generated.
                </>
              )}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function pctOf(n: number, total: number): number {
  return total === 0 ? 0 : (n / total) * 100
}

function Segment({ color, pct }: { color: string; pct: number }) {
  if (pct <= 0) return null
  return <div className={color} style={{ width: `${pct}%` }} />
}

function Chip({
  icon,
  label,
  count,
  cls,
}: {
  icon: React.ReactNode
  label: string
  count: number
  cls: string
}) {
  return (
    <span className={'inline-flex items-center gap-1 ' + cls}>
      {icon}
      <span className="tabular-nums font-semibold">{count}</span>
      <span className="text-pfl-slate-500">{label}</span>
    </span>
  )
}
