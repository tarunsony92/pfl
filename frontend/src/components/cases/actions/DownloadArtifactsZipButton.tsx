'use client'

/**
 * DownloadArtifactsZipButton — bundles every classified artifact on the case
 * (including anything the assessor has added since the original upload) into
 * a fresh ZIP for offline review or hand-off.
 *
 * Backend: GET /cases/:id/artifacts/zip — already exists.
 */

import React, { useState } from 'react'
import { DownloadIcon, Loader2Icon } from 'lucide-react'
import { cn } from '@/lib/cn'
import { cases as casesApi } from '@/lib/api'

interface Props {
  caseId: string
  loanId: string | null
}

export function DownloadArtifactsZipButton({ caseId, loanId }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleClick() {
    setBusy(true)
    setError(null)
    try {
      const res = await casesApi.downloadArtifactsZip(caseId)
      if (!res.ok) {
        setError(res.message || `HTTP ${res.status}`)
        return
      }
      const url = URL.createObjectURL(res.blob)
      const a = document.createElement('a')
      a.href = url
      a.download = res.filename || `${loanId ?? caseId}_artifacts.zip`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Download failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="inline-flex flex-col items-end gap-0.5">
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className={cn(
          'inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-semibold border transition-colors',
          'border-pfl-slate-300 text-pfl-slate-700 hover:bg-pfl-slate-50',
          busy && 'opacity-60 cursor-wait',
        )}
        title="Download every classified artifact on this case as a single ZIP. Includes anything the assessor has added since the original upload."
      >
        {busy ? (
          <Loader2Icon className="h-3.5 w-3.5 animate-spin" aria-hidden />
        ) : (
          <DownloadIcon className="h-3.5 w-3.5" aria-hidden />
        )}
        {busy ? 'Bundling…' : 'Download artifacts ZIP'}
      </button>
      {error && (
        <span className="text-[10.5px] text-red-700 max-w-[260px] text-right truncate">
          {error}
        </span>
      )}
    </div>
  )
}
