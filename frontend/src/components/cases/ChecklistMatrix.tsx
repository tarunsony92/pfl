'use client'

/**
 * ChecklistMatrix — two-column table of present vs missing documents.
 *
 * Props:
 *   result  — ChecklistValidationResultRead (may be undefined)
 *   isLoading
 */

import React from 'react'
import { CheckCircle2Icon, XCircleIcon, ClipboardListIcon } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import type { ChecklistValidationResultRead } from '@/lib/types'

interface ChecklistMatrixProps {
  result?: ChecklistValidationResultRead
  isLoading?: boolean
  notRun?: boolean
}

type DocRecord = Record<string, unknown>

function docName(doc: DocRecord): string {
  return (
    (doc.name as string) ??
    (doc.doc_name as string) ??
    (doc.label as string) ??
    (doc.subtype as string) ??
    JSON.stringify(doc)
  )
}

function docReason(doc: DocRecord): string | null {
  return (doc.reason as string | null) ?? (doc.missing_reason as string | null) ?? null
}

function docArtifactId(doc: DocRecord): string | null {
  return (doc.artifact_id as string | null) ?? null
}

export function ChecklistMatrix({ result, isLoading, notRun }: ChecklistMatrixProps) {
  if (isLoading) {
    return (
      <div className="flex flex-col gap-2" data-testid="checklist-skeleton">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  }

  if (notRun || !result) {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-pfl-slate-500">
        <ClipboardListIcon className="h-10 w-10 opacity-40" aria-hidden="true" />
        <p className="font-medium">Checklist validation not yet run</p>
      </div>
    )
  }

  const { is_complete, present_docs, missing_docs, validated_at } = result

  return (
    <div className="flex flex-col gap-4">
      {/* Header strip */}
      <div className="flex items-center gap-3">
        <Badge variant={is_complete ? 'success' : 'destructive'} className="text-sm px-3 py-1">
          {is_complete ? 'COMPLETE' : 'INCOMPLETE'}
        </Badge>
        <span className="text-xs text-pfl-slate-400">
          Validated:{' '}
          {new Date(validated_at).toLocaleString(undefined, {
            dateStyle: 'medium',
            timeStyle: 'short',
          })}
        </span>
      </div>

      {/* Two-column table */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Present */}
        <div>
          <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-green-700">
            <CheckCircle2Icon className="h-4 w-4" aria-hidden="true" />
            Present ({present_docs.length})
          </h3>
          {present_docs.length === 0
            ? <p className="text-xs text-pfl-slate-400 italic">None</p>
            : (
              <ul className="flex flex-col gap-1.5">
                {present_docs.map((doc, i) => {
                  const name = docName(doc as DocRecord)
                  const artifactId = docArtifactId(doc as DocRecord)
                  return (
                    <li
                      key={i}
                      className="flex items-start gap-2 rounded bg-green-50 border border-green-100 px-3 py-2"
                    >
                      <CheckCircle2Icon className="mt-0.5 h-3.5 w-3.5 text-green-600 shrink-0" aria-hidden="true" />
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-pfl-slate-800 break-all">{name}</p>
                        {artifactId && (
                          <p className="text-xs text-pfl-slate-400 font-mono mt-0.5 truncate">
                            {artifactId}
                          </p>
                        )}
                      </div>
                    </li>
                  )
                })}
              </ul>
            )
          }
        </div>

        {/* Missing */}
        <div>
          <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-red-700">
            <XCircleIcon className="h-4 w-4" aria-hidden="true" />
            Missing ({missing_docs.length})
          </h3>
          {missing_docs.length === 0
            ? <p className="text-xs text-pfl-slate-400 italic">None</p>
            : (
              <ul className="flex flex-col gap-1.5">
                {missing_docs.map((doc, i) => {
                  const name = docName(doc as DocRecord)
                  const reason = docReason(doc as DocRecord)
                  return (
                    <li
                      key={i}
                      className="flex items-start gap-2 rounded bg-red-50 border border-red-100 px-3 py-2"
                    >
                      <XCircleIcon className="mt-0.5 h-3.5 w-3.5 text-red-500 shrink-0" aria-hidden="true" />
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-pfl-slate-800 break-all">{name}</p>
                        {reason && (
                          <p className="text-xs text-pfl-slate-500 mt-0.5">{reason}</p>
                        )}
                      </div>
                    </li>
                  )
                })}
              </ul>
            )
          }
        </div>
      </div>
    </div>
  )
}
