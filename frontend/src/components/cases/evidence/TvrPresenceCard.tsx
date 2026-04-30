'use client'
/**
 * TvrPresenceCard — `tvr_present` (L5.5). Phase 1 only checks presence;
 * audio understanding (transcript + cross-check) is Phase 2.
 */

import { cn } from '@/lib/cn'

export function TvrPresenceCard({
  evidence: ev,
}: {
  evidence: Record<string, unknown>
}) {
  const filename = ev['filename'] as string | undefined
  const sizeBytes = ev['size_bytes'] as number | undefined
  const expectedSubtype = ev['expected_subtype'] as string | undefined

  // Missing path — orchestrator emits expected_subtype + empty source_artifacts
  if (expectedSubtype && !filename) {
    return (
      <div className="flex flex-col gap-2 text-[12px] text-pfl-slate-700">
        <div className="inline-flex w-fit items-center rounded border border-red-200 bg-red-50 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-red-700">
          tvr missing
        </div>
        <p>
          The assessor&apos;s Tele-Verification Report audio (mp3 / wav / m4a)
          hasn&apos;t been uploaded. Attach the call recording so the assessor
          can review and L5.5 can pass.
        </p>
      </div>
    )
  }

  const sizeKb = typeof sizeBytes === 'number' ? Math.round(sizeBytes / 1024) : null
  return (
    <div className="flex flex-col gap-2 text-[12px] text-pfl-slate-700">
      <div className="inline-flex w-fit items-center rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-700">
        tvr uploaded
      </div>
      <div>
        <span className="font-medium font-mono">{filename ?? '—'}</span>
        {sizeKb !== null && (
          <span className="ml-2 text-pfl-slate-500">· {sizeKb} KB</span>
        )}
      </div>
      <p className="text-[11px] text-pfl-slate-500">
        Phase 1 confirms the recording is attached. Audio transcription and
        cross-check are not enabled in this build.
      </p>
    </div>
  )
}

export function tvrPresenceHeadline(
  ev: Record<string, unknown>,
): string | undefined {
  const filename = ev['filename']
  if (filename) return 'TVR audio uploaded'
  if (ev['expected_subtype']) return 'TVR audio not uploaded'
  return undefined
}
