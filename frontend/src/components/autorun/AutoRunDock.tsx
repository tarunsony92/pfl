'use client'

/**
 * AutoRunDock — fixed bottom-right dock listing any minimized auto-runs.
 * Clicking a dock pill re-opens the modal. A done run pulses green then
 * sticks as a tick until the user dismisses.
 */

import React from 'react'
import Link from 'next/link'
import { cn } from '@/lib/cn'
import { useAutoRun } from './AutoRunProvider'

export function AutoRunDock() {
  const { state, openModal, dismiss, getStatus, getProgress } = useAutoRun()
  const runs = Object.values(state.runs)
  const visible = runs.filter((r) => r.minimized)
  if (visible.length === 0) return null

  return (
    <div
      className="fixed bottom-4 right-4 z-40 flex flex-col gap-2 max-w-xs"
      data-testid="autorun-dock"
    >
      {visible.map((r) => {
        const status = getStatus(r.caseId)
        const progress = getProgress(r.caseId) ?? 0
        const pct = Math.round(progress * 100)
        return (
          <div
            key={r.caseId}
            className={cn(
              'flex items-center gap-3 rounded-lg border bg-white shadow-md px-3 py-2.5 hover:shadow-lg transition-shadow',
              status === 'done' && 'border-emerald-300',
              status === 'done_with_errors' && 'border-amber-300',
              status === 'blocked' && 'border-amber-300',
              status === 'failed' && 'border-red-300',
              status === 'running' && 'border-pfl-blue-300',
            )}
          >
            {/* Ring or tick */}
            {status === 'done' ? (
              <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-emerald-600 text-white">
                <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden>
                  <path
                    d="M3 8l3 3 7-7"
                    stroke="currentColor"
                    strokeWidth="2"
                    fill="none"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
            ) : (
              <CircularRing pct={pct} status={status} />
            )}

            <div className="min-w-0 flex-1">
              <div className="text-xs font-semibold text-pfl-slate-900 truncate">
                {r.applicantName ?? 'Auto-run'}
              </div>
              <div className="text-[10.5px] text-pfl-slate-500 truncate">
                {status === 'done' && 'Pipeline complete'}
                {status === 'done_with_errors' && 'Finished with errors'}
                {status === 'blocked' && 'Missing required documents'}
                {status === 'failed' && 'All steps failed'}
                {status === 'running' && `${pct}% — running in background`}
              </div>
            </div>

            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => openModal(r.caseId)}
                className="text-[10.5px] text-pfl-blue-700 hover:underline font-semibold"
              >
                Open
              </button>
              <Link
                href={`/cases/${r.caseId}`}
                className="text-[10.5px] text-pfl-slate-500 hover:text-pfl-slate-900 hover:underline"
              >
                Case
              </Link>
              <button
                type="button"
                onClick={() => dismiss(r.caseId)}
                className="text-pfl-slate-400 hover:text-pfl-slate-700 text-sm leading-none w-5 text-center"
                aria-label="Dismiss"
              >
                ×
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function CircularRing({
  pct,
  status,
  size = 28,
}: {
  pct: number
  status: 'idle' | 'running' | 'done' | 'done_with_errors' | 'failed' | 'blocked'
  size?: number
}) {
  const stroke = 3
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const dashOffset = circumference * (1 - Math.min(Math.max(pct, 0), 100) / 100)
  const color =
    status === 'done'
      ? 'stroke-emerald-600'
      : status === 'done_with_errors' || status === 'blocked'
      ? 'stroke-amber-500'
      : status === 'failed'
      ? 'stroke-red-600'
      : 'stroke-pfl-blue-600'
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="shrink-0"
      aria-label={`${pct}%`}
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        strokeWidth={stroke}
        className="stroke-pfl-slate-200"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        strokeWidth={stroke}
        strokeLinecap="round"
        className={cn('transition-[stroke-dashoffset] duration-500', color)}
        strokeDasharray={circumference}
        strokeDashoffset={dashOffset}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text
        x="50%"
        y="52%"
        textAnchor="middle"
        dominantBaseline="middle"
        className="fill-pfl-slate-700 font-semibold"
        style={{ fontSize: size < 32 ? 8 : 10 }}
      >
        {pct}%
      </text>
    </svg>
  )
}
