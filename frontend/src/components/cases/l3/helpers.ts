// Shared formatters and colour-grade helpers for the L3 panel components.
// Lives next to the components so the number formatting stays consistent
// between the header card and the click-to-expand pass cards.

export function formatInr(n: number | null | undefined): string {
  if (n == null) return '—'
  return `₹${n.toLocaleString('en-IN')}`
}

export function formatPct(n: number | null | undefined, digits = 0): string {
  if (n == null) return '—'
  return `${(n * 100).toFixed(digits)}%`
}

export type CoverageTone = 'emerald' | 'amber' | 'red'

/** Emerald / amber / red based on coverage vs floor thresholds.
 *  Service biz has a single critical floor (no warning tier);
 *  non-service has two tiers. */
export function coverageTone(
  coveragePct: number | null | undefined,
  floorCritical: number | null | undefined,
  floorWarning: number | null | undefined,
): CoverageTone {
  if (coveragePct == null || floorCritical == null) return 'amber'
  if (floorWarning != null) {
    // Two-tier (non-service)
    if (coveragePct >= floorWarning) return 'emerald'
    if (coveragePct >= floorCritical) return 'amber'
    return 'red'
  }
  // Single-tier (service)
  return coveragePct >= floorCritical ? 'emerald' : 'red'
}

export const TONE_PILL_CLASSES: Record<CoverageTone, string> = {
  emerald: 'bg-emerald-50 text-emerald-800 border-emerald-300',
  amber: 'bg-amber-50 text-amber-800 border-amber-300',
  red: 'bg-red-50 text-red-800 border-red-300',
}
