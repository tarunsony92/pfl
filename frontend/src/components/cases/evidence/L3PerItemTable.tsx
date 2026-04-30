'use client'
/**
 * L3PerItemTable — replaces L3PerItemTablePlaceholder. Renders a table
 * of items extracted by the Phase-2 BusinessPremisesScorer (per-item
 * description, qty, category, AI-estimated MRP, line total).
 *
 * Three render paths:
 *   1. items === undefined  -> legacy extraction (schema_version 1.0).
 *      Fires onAutoRefresh on mount; shows "Refreshing per-item
 *      breakdown…" notice.
 *   2. items.length === 0   -> scorer ran but found nothing. Rare.
 *   3. items.length > 0     -> the table.
 *
 * MRP semantics (Phase 2.5):
 *   - catalogue_mrp_inr takes precedence over mrp_estimate_inr
 *   - mrp_estimate_inr === null  -> em-dash, no line total
 *   - mrp_confidence === "low"   -> italic-grey + "(low conf.)" suffix
 *   - mrp_confidence in {high|medium} -> normal styling
 *   - mrp_source drives a source pill next to the MRP value
 *
 * Grand total = Σ priced line totals (catalogue-aware). Unpriced rows
 * are excluded with a "(N items unpriced)" footnote next to the total.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import useSWR from 'swr'
import { cn } from '@/lib/cn'
import { formatInr } from '../l3/helpers'
import { casePhotos } from '@/lib/api'
import { useCasePhotos } from '@/lib/useVerification'

export type L3ItemRow = {
  description: string
  qty: number
  category: 'equipment' | 'stock' | 'consumable' | 'other'
  mrp_estimate_inr: number | null
  mrp_confidence: 'high' | 'medium' | 'low'
  rationale?: string
  // Phase 2.5 additions:
  crop_artifact_id?: string | null
  crop_filename?: string | null
  catalogue_mrp_inr?: number | null
  mrp_source?: 'AI_ESTIMATED' | 'MANUAL' | 'OVERRIDDEN_FROM_AI' | null
  catalogue_entry_id?: string | null
  // Optional bbox fields for future viewer overlay (display unused today)
  source_image?: number | null
  bbox?: [number, number, number, number] | null
}

const CATEGORY_TONE: Record<L3ItemRow['category'], string> = {
  equipment: 'bg-pfl-slate-100 text-pfl-slate-700 border-pfl-slate-300',
  stock: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  consumable: 'bg-amber-50 text-amber-700 border-amber-200',
  other: 'bg-pfl-slate-50 text-pfl-slate-600 border-pfl-slate-200',
}

export function L3PerItemTable({
  items,
  caseId,
  onAutoRefresh,
}: {
  items: L3ItemRow[] | undefined
  caseId: string
  onAutoRefresh?: () => void
}) {
  const fired = useRef(false)

  useEffect(() => {
    if (items !== undefined) return
    if (fired.current) return
    if (!onAutoRefresh) return
    fired.current = true
    onAutoRefresh()
  }, [items, onAutoRefresh])

  // Fetch crop thumbnails when any item has a crop_artifact_id
  const hasAnyCrops = items?.some((it) => it.crop_artifact_id) ?? false
  const { data: cropPhotos } = useSWR(
    hasAnyCrops ? ['l3-crops', caseId] : null,
    () => casePhotos(caseId, 'BUSINESS_PREMISES_CROP'),
  )
  const cropUrlByArtifactId = useMemo(() => {
    const m = new Map<string, string>()
    for (const item of cropPhotos?.items ?? []) {
      if (item.download_url) m.set(item.artifact_id, item.download_url)
    }
    return m
  }, [cropPhotos])

  // source_image is 1-indexed into the photo list in the order the scorer
  // received them. Only fetched when at least one item has bbox + source_image.
  const hasAnyBboxes =
    items?.some((it) => it.bbox && it.source_image) ?? false
  const { data: bizPhotos } = useCasePhotos(
    caseId,
    'BUSINESS_PREMISES_PHOTO',
    hasAnyBboxes,
  )
  const parentPhotos = bizPhotos?.items ?? []

  const [overlay, setOverlay] = useState<null | {
    src: string
    filename: string
    bbox: [number, number, number, number]
    description: string
  }>(null)

  useEffect(() => {
    if (!overlay) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOverlay(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [overlay])

  // Path 1: legacy extraction. Show refreshing notice + fire callback above.
  if (items === undefined) {
    return (
      <div className="rounded border border-dashed border-pfl-slate-300 bg-pfl-slate-50/60 p-4">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-2 w-2 animate-pulse rounded-full bg-pfl-blue-500" />
          <span className="text-[12.5px] font-semibold text-pfl-slate-800">
            Refreshing per-item breakdown…
          </span>
        </div>
        <p className="mt-1 text-[12px] text-pfl-slate-600 leading-snug">
          This case&apos;s L3 vision pass is being re-run with the v2 schema so
          the per-item table can render. Should take ~30 seconds.
        </p>
      </div>
    )
  }

  // Path 2: scorer ran but found no items. Edge case.
  if (items.length === 0) {
    return (
      <div className="rounded border border-pfl-slate-200 bg-white p-4 text-[12px] text-pfl-slate-600">
        No itemised collateral extracted from this scorer pass.
      </div>
    )
  }

  // Path 3: render the table.
  type Computed = L3ItemRow & {
    line_total_inr: number | null
  }
  const computed: Computed[] = items.map((it) => {
    const effectiveMrp = it.catalogue_mrp_inr ?? it.mrp_estimate_inr
    return {
      ...it,
      line_total_inr:
        effectiveMrp !== null && effectiveMrp !== undefined && Number.isFinite(it.qty)
          ? effectiveMrp * it.qty
          : null,
    }
  })
  const grandTotal = computed.reduce(
    (acc, r) => (r.line_total_inr !== null ? acc + r.line_total_inr : acc),
    0,
  )
  const unpriced = computed.filter((r) => r.line_total_inr === null).length

  return (
    <div className="rounded border border-pfl-slate-200 bg-white overflow-hidden">
      <div className="border-b border-pfl-slate-200 bg-pfl-slate-50 px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-pfl-slate-700">
        Per-item collateral · {computed.length} item{computed.length === 1 ? '' : 's'}
      </div>
      <table className="w-full text-[12px]">
        <thead className="bg-pfl-slate-50 text-pfl-slate-600 uppercase text-[10px] tracking-wider">
          <tr>
            <th className="px-2 py-1.5 text-left w-16">Photo</th>
            <th className="px-3 py-1.5 text-left">Description</th>
            <th className="px-3 py-1.5 text-right">Qty</th>
            <th className="px-3 py-1.5 text-left">Category</th>
            <th className="px-3 py-1.5 text-right">MRP (₹)</th>
            <th className="px-3 py-1.5 text-right">Line total (₹)</th>
          </tr>
        </thead>
        <tbody>
          {computed.map((r, i) => {
            const displayMrp = r.catalogue_mrp_inr ?? r.mrp_estimate_inr
            const unpricedRow = displayMrp === null || displayMrp === undefined
            // lowConf drives italic/grey styling; applies when confidence is low
            // regardless of source (covers legacy rows that have no mrp_source)
            const lowConf = r.mrp_confidence === 'low'
            // showLowConfPill: only show the "low conf." text label when the source
            // is AI_ESTIMATED (or absent/legacy — no catalogue entry involved)
            const showLowConfPill =
              r.mrp_confidence === 'low' &&
              (r.mrp_source === 'AI_ESTIMATED' || r.mrp_source == null)
            return (
              <tr
                key={i}
                className="border-t border-pfl-slate-100 hover:bg-pfl-slate-50/40"
                title={r.rationale}
              >
                {/* Crop thumbnail */}
                <td className="px-2 py-1 align-top">
                  {(() => {
                    const cropId = r.crop_artifact_id
                    const url = cropId ? cropUrlByArtifactId.get(cropId) : undefined
                    if (url) {
                      return (
                        <img
                          src={url}
                          alt={r.description}
                          loading="lazy"
                          className="h-12 w-12 rounded border border-pfl-slate-200 object-cover"
                        />
                      )
                    }
                    // Fallback: small placeholder square so the column doesn't collapse
                    return (
                      <div className="h-12 w-12 rounded border border-dashed border-pfl-slate-200 bg-pfl-slate-50/50 flex items-center justify-center text-[9px] uppercase tracking-wider text-pfl-slate-400">
                        no crop
                      </div>
                    )
                  })()}
                </td>
                <td className="px-3 py-1.5 text-pfl-slate-800">
                  {r.description}
                  {(() => {
                    if (!r.bbox || !r.source_image) return null
                    const photo = parentPhotos[r.source_image - 1]
                    if (!photo) return null
                    return (
                      <button
                        type="button"
                        className="ml-2 text-[10.5px] text-pfl-blue-600 hover:underline"
                        onClick={() =>
                          setOverlay({
                            src: photo.download_url,
                            filename: photo.filename,
                            bbox: r.bbox!,
                            description: r.description,
                          })
                        }
                      >
                        view on photo
                      </button>
                    )
                  })()}
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-pfl-slate-700">
                  {r.qty}
                </td>
                <td className="px-3 py-1.5">
                  <span
                    className={cn(
                      'inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider',
                      CATEGORY_TONE[r.category],
                    )}
                  >
                    {r.category}
                  </span>
                </td>
                <td
                  className={cn(
                    'px-3 py-1.5 text-right font-mono',
                    unpricedRow
                      ? 'text-pfl-slate-400'
                      : lowConf
                        ? 'text-pfl-slate-500 italic'
                        : 'text-pfl-slate-900',
                  )}
                >
                  {(() => {
                    if (unpricedRow) {
                      return <span className="text-pfl-slate-400">—</span>
                    }
                    return (
                      <span className={cn(lowConf ? 'text-pfl-slate-500 italic' : 'text-pfl-slate-900')}>
                        {formatInr(displayMrp)}
                      </span>
                    )
                  })()}
                  {/* Source pill */}
                  {r.mrp_source && r.mrp_source !== 'AI_ESTIMATED' && (
                    <span
                      className={cn(
                        'ml-1 inline-flex items-center rounded border px-1 py-0.5 text-[9px] font-bold uppercase tracking-wider',
                        r.mrp_source === 'MANUAL'
                          ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                          : 'border-amber-200 bg-amber-50 text-amber-700', // OVERRIDDEN_FROM_AI
                      )}
                      title={
                        r.mrp_source === 'MANUAL'
                          ? 'Manually curated by an admin'
                          : 'Started as AI estimate, since edited by an admin'
                      }
                    >
                      {r.mrp_source === 'MANUAL' ? 'curated' : 'edited'}
                    </span>
                  )}
                  {showLowConfPill && (
                    <span className="ml-1 text-[10px] uppercase tracking-wider text-amber-600">
                      low conf.
                    </span>
                  )}
                </td>
                <td
                  className={cn(
                    'px-3 py-1.5 text-right font-mono',
                    unpricedRow ? 'text-pfl-slate-400' : 'text-pfl-slate-900',
                  )}
                >
                  {unpricedRow ? '—' : formatInr(r.line_total_inr)}
                </td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-pfl-slate-300 bg-pfl-slate-50">
            <td
              colSpan={5}
              className="px-3 py-2 text-right text-[11px] font-bold uppercase tracking-wider text-pfl-slate-700"
            >
              Grand total
              {unpriced > 0 && (
                <span className="ml-2 font-normal normal-case text-pfl-slate-500">
                  · {unpriced} item{unpriced === 1 ? '' : 's'} unpriced (excluded)
                </span>
              )}
            </td>
            <td className="px-3 py-2 text-right font-mono text-[13px] font-bold text-pfl-slate-900">
              {formatInr(grandTotal)}
            </td>
          </tr>
        </tfoot>
      </table>
      {overlay && <BboxOverlayModal {...overlay} onClose={() => setOverlay(null)} />}
    </div>
  )
}

/** Coords are normalized 0-1 in the SVG viewBox so they line up with the image
 *  regardless of its rendered size; Escape close is wired in the parent. */
function BboxOverlayModal({
  src,
  filename,
  bbox,
  description,
  onClose,
}: {
  src: string
  filename: string
  bbox: [number, number, number, number]
  description: string
  onClose: () => void
}) {
  const [x0, y0, x1, y1] = bbox
  const width = Math.max(0, x1 - x0)
  const height = Math.max(0, y1 - y0)
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
      role="dialog"
      aria-label={`Bbox overlay: ${description}`}
      onClick={onClose}
    >
      <div
        className="max-w-5xl max-h-full flex flex-col gap-2"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="relative">
          <img
            src={src}
            alt={filename}
            className="max-h-[80vh] w-auto object-contain rounded block"
          />
          <svg
            className="absolute inset-0 w-full h-full pointer-events-none"
            viewBox="0 0 1 1"
            preserveAspectRatio="none"
            data-testid="bbox-overlay-svg"
          >
            <rect
              x={x0}
              y={y0}
              width={width}
              height={height}
              stroke="rgb(220,38,38)"
              strokeWidth="3"
              fill="rgba(220,38,38,0.15)"
              vectorEffect="non-scaling-stroke"
            />
          </svg>
        </div>
        <div className="text-[12px] text-white/80 flex justify-between items-center gap-3">
          <span className="truncate">
            <span className="font-semibold">{description}</span>
            <span className="ml-2 text-white/60">{filename}</span>
          </span>
          <button
            type="button"
            className="text-white underline shrink-0"
            onClick={onClose}
          >
            close
          </button>
        </div>
      </div>
    </div>
  )
}
