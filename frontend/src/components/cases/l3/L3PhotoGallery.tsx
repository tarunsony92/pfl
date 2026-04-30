'use client'

import { useState } from 'react'
import { L3VisualEvidence } from '@/lib/types'
import { useCasePhotos } from '@/lib/useVerification'

/** Always-visible photo gallery next to the stock-analysis card.
 *  Filters the existing useCasePhotos hook's output down to the
 *  artifact IDs the L3 scorer actually processed. Shows a low-count
 *  warning when fewer than 2 were evaluated in either category. */
export function L3PhotoGallery({
  caseId,
  visualEvidence,
}: {
  caseId: string
  visualEvidence: L3VisualEvidence | null | undefined
}) {
  // Always call the hooks (React rules-of-hooks).
  const { data: housePhotos } = useCasePhotos(caseId, 'HOUSE_VISIT_PHOTO', true)
  const { data: businessPhotos } = useCasePhotos(
    caseId,
    'BUSINESS_PREMISES_PHOTO',
    true,
  )
  const [lightbox, setLightbox] = useState<null | {
    src: string
    filename: string
  }>(null)

  if (!visualEvidence) {
    return (
      <div className="border border-pfl-slate-200 rounded-md bg-white p-3 text-[12px] text-pfl-slate-500">
        Photo gallery unavailable.
      </div>
    )
  }

  const houseIds = new Set(
    visualEvidence.house_photos.map((p) => p.artifact_id),
  )
  const bizIds = new Set(
    visualEvidence.business_photos.map((p) => p.artifact_id),
  )
  const house = (housePhotos?.items ?? []).filter((p) =>
    houseIds.has(p.artifact_id),
  )
  const biz = (businessPhotos?.items ?? []).filter((p) =>
    bizIds.has(p.artifact_id),
  )

  const lowHouse =
    visualEvidence.house_photos.length > 0 &&
    visualEvidence.house_photos_evaluated < 2
  const lowBiz =
    visualEvidence.business_photos.length > 0 &&
    visualEvidence.business_photos_evaluated < 2

  return (
    <>
      <div className="border border-pfl-slate-200 rounded-md bg-white p-3 flex flex-col gap-3">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500">
          Photos
        </div>

        <Section
          title="House visit"
          evaluated={visualEvidence.house_photos_evaluated}
          uploaded={visualEvidence.house_photos.length}
          lowCount={lowHouse}
          photos={house}
          onOpen={(src, filename) => setLightbox({ src, filename })}
          emptyCopy="No house-visit photos uploaded."
        />

        <Section
          title="Business premises"
          evaluated={visualEvidence.business_photos_evaluated}
          uploaded={visualEvidence.business_photos.length}
          lowCount={lowBiz}
          photos={biz}
          onOpen={(src, filename) => setLightbox({ src, filename })}
          emptyCopy="No business-premises photos uploaded."
        />
      </div>

      {lightbox && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
          role="dialog"
          aria-label={`Photo preview: ${lightbox.filename}`}
          onClick={() => setLightbox(null)}
        >
          <div className="max-w-5xl max-h-full flex flex-col gap-2">
            <img
              src={lightbox.src}
              alt={lightbox.filename}
              className="max-h-[80vh] w-auto object-contain rounded"
            />
            <div className="text-[12px] text-white/80 flex justify-between items-center">
              <span className="truncate">{lightbox.filename}</span>
              <button
                type="button"
                className="text-white underline"
                onClick={(e) => {
                  e.stopPropagation()
                  setLightbox(null)
                }}
              >
                close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function Section({
  title,
  evaluated,
  uploaded,
  lowCount,
  photos,
  onOpen,
  emptyCopy,
}: {
  title: string
  evaluated: number
  uploaded: number
  lowCount: boolean
  photos: Array<{ artifact_id: string; download_url: string; filename: string }>
  onOpen: (src: string, filename: string) => void
  emptyCopy: string
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[11.5px] font-semibold text-pfl-slate-700">
          {title}
        </span>
        <span className="text-[11px] text-pfl-slate-500">
          {uploaded} uploaded · {evaluated} evaluated
        </span>
      </div>
      {lowCount && (
        <div className="mb-2 text-[11px] text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1">
          Only {evaluated} photo evaluated — consider re-inspection for confidence.
        </div>
      )}
      {photos.length === 0 ? (
        <div className="text-[11.5px] text-pfl-slate-500">{emptyCopy}</div>
      ) : (
        <div className="grid grid-cols-3 md:grid-cols-5 gap-2">
          {photos.map((p) => (
            <button
              key={p.artifact_id}
              type="button"
              onClick={() => onOpen(p.download_url, p.filename)}
              className="block border border-pfl-slate-200 rounded bg-white hover:border-pfl-blue-500 transition-colors overflow-hidden aspect-square"
              title={p.filename}
            >
              <img
                src={p.download_url}
                alt={p.filename}
                className="w-full h-full object-cover"
                loading="lazy"
              />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
