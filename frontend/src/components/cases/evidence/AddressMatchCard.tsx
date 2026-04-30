'use client'
/**
 * AddressMatchCard — generic "two addresses, one verdict" card. Serves
 * three L1 rules with a stable shape:
 *   - `applicant_coapp_address_match` — applicant_address + co_applicant_address
 *   - `aadhaar_vs_bureau_address`     — aadhaar_address + bureau_addresses[]
 *   - `aadhaar_vs_bank_address`       — aadhaar_address + bank_addresses[]
 *
 * Headline carries the match threshold + verdict so a 30-year
 * underwriter can triage without expanding.
 */

import { cn } from '@/lib/cn'
import { formatEvidenceValue } from './_format'
import { DistanceBadge } from './DistanceBadge'

export function AddressMatchCard({
  evidence: ev,
  subStepId,
}: {
  evidence: Record<string, unknown>
  subStepId: string
}) {
  const { primaryLabel, primary, secondaryLabel, secondary } = pickPair(ev, subStepId)
  const threshold = ev['match_threshold'] as number | undefined
  const verdict =
    typeof ev['verdict'] === 'string' ? (ev['verdict'] as string) : null
  const verdictCls = (() => {
    if (!verdict) return 'text-pfl-slate-700'
    const v = verdict.toLowerCase()
    if (v.includes('match')) return 'text-emerald-700'
    if (v.includes('partial') || v.includes('weak')) return 'text-amber-700'
    return 'text-red-700'
  })()

  return (
    <div className="flex flex-col gap-3">
      <DistanceBadge evidence={ev} />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <Block label={primaryLabel} value={primary} />
        <Block label={secondaryLabel} value={secondary} />
      </div>
      {(verdict || typeof threshold === 'number') && (
        <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-2 text-[12px] text-pfl-slate-800 flex flex-wrap items-center gap-3">
          {verdict && (
            <span>
              Verdict:{' '}
              <span className={cn('font-bold uppercase', verdictCls)}>
                {verdict}
              </span>
            </span>
          )}
          {typeof threshold === 'number' && (
            <span>
              Threshold: <span className="font-mono">{threshold}</span>
            </span>
          )}
        </div>
      )}
    </div>
  )
}

function pickPair(ev: Record<string, unknown>, subStepId: string) {
  if (subStepId === 'applicant_coapp_address_match') {
    return {
      primaryLabel: 'Applicant address',
      primary: ev['applicant_address'],
      secondaryLabel: 'Co-applicant address',
      secondary: ev['co_applicant_address'],
    }
  }
  if (subStepId === 'aadhaar_vs_bureau_address') {
    return {
      primaryLabel: 'Aadhaar address',
      primary: ev['aadhaar_address'],
      secondaryLabel: 'Bureau address(es)',
      secondary: ev['bureau_addresses'],
    }
  }
  if (subStepId === 'aadhaar_vs_bank_address') {
    return {
      primaryLabel: 'Aadhaar address',
      primary: ev['aadhaar_address'],
      secondaryLabel: 'Bank-statement address(es)',
      secondary: ev['bank_addresses'],
    }
  }
  // Generic last-resort — show the first two string keys.
  const keys = Object.keys(ev).filter((k) => typeof ev[k] === 'string')
  return {
    primaryLabel: keys[0] ?? 'A',
    primary: ev[keys[0] ?? ''],
    secondaryLabel: keys[1] ?? 'B',
    secondary: ev[keys[1] ?? ''],
  }
}

function Block({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-2">
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 mb-1">
        {label}
      </div>
      <div className="text-[12px] text-pfl-slate-800 whitespace-pre-wrap break-words">
        {Array.isArray(value)
          ? renderList(value as unknown[])
          : formatEvidenceValue(value) || '—'}
      </div>
    </div>
  )
}

function renderList(items: unknown[]) {
  if (items.length === 0) return '—'
  return (
    <ul className="list-disc list-inside space-y-0.5">
      {items.map((it, i) => (
        <li key={i}>{formatEvidenceValue(it)}</li>
      ))}
    </ul>
  )
}

export function addressMatchHeadline(
  ev: Record<string, unknown>,
): string | undefined {
  const t = ev['match_threshold']
  if (typeof t === 'number') return `threshold ${t}`
  return undefined
}
