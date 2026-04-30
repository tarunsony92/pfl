'use client'

type Evidence = {
  infrastructure_rating?: string | null
  infrastructure_details?: string[]
  equipment_visible?: boolean
  photos_evaluated_count?: number
}

export function L3InfraPassCard({ evidence }: { evidence: Evidence }) {
  return (
    <div className="border border-pfl-slate-200 rounded bg-pfl-slate-50 p-3 flex flex-col gap-2">
      <div className="flex items-center gap-2 text-[12px]">
        <span className="text-pfl-slate-500">Infrastructure rating</span>
        <span className="text-pfl-slate-900 font-semibold">
          {evidence.infrastructure_rating ?? '—'}
        </span>
        {evidence.equipment_visible != null && (
          <span className="ml-3 text-pfl-slate-500">
            Equipment visible: {evidence.equipment_visible ? 'yes' : 'no'}
          </span>
        )}
        {evidence.photos_evaluated_count != null && (
          <span className="ml-auto text-[11px] text-pfl-slate-500">
            {evidence.photos_evaluated_count} photos evaluated
          </span>
        )}
      </div>
      {Array.isArray(evidence.infrastructure_details) &&
        evidence.infrastructure_details.length > 0 && (
          <ul className="list-disc ml-4 text-[12px] text-pfl-slate-700 space-y-0.5">
            {evidence.infrastructure_details.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        )}
    </div>
  )
}
