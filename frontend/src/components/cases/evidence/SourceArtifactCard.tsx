'use client'
/**
 * Source-file card. Shows the artefact metadata (icon + label + filename
 * + size + Preview / Open / Download buttons) immediately; the inline
 * preview body — `<img>` for images, `<iframe>` for PDFs and HTML —
 * renders ONLY after the user clicks Preview. PDFs deep-link to
 * `#page=N` when the evidence carries a page hint (e.g. L4
 * `annexure_page_hint`).
 *
 * Why click-to-preview (not auto-load + lazy):
 *   `loading="lazy"` only delays the GET until the element scrolls into
 *   view — it doesn't prevent the GET. localstack (and some prod-S3
 *   keys) serve PDFs with `Content-Disposition: attachment`, so the
 *   browser triggers a download dialog the moment the iframe enters
 *   the viewport. That happens reliably when the user opens any
 *   verification concern that has source files attached. Gating the
 *   preview behind an explicit click eliminates the auto-fire entirely.
 *
 * History: the auto-loading inline preview lived here from
 * commits `f3e4dd4` (PR2 of the verification revamp) until this commit.
 * The pre-PR2 single-row card is the closest analogue to the new
 * behaviour, with the addition of a one-click Preview toggle.
 */

import { useState } from 'react'
import {
  DownloadIcon,
  ExternalLinkIcon,
  EyeIcon,
  EyeOffIcon,
  FileTextIcon,
  ImageIcon,
} from 'lucide-react'
import type { CaseArtifactRead } from '@/lib/types'
import {
  artifactLabel,
  formatBytes,
  isHtmlArtifact,
  isImageArtifact,
  isPdfArtifact,
  type SourceArtifactRef,
} from './_format'

export function SourceArtifactCard({
  ref_,
  artifact,
}: {
  ref_: SourceArtifactRef
  artifact: CaseArtifactRead | null
}) {
  const [showPreview, setShowPreview] = useState(false)
  if (!artifact) {
    return (
      <div className="rounded border border-amber-200 bg-amber-50 p-3 text-[12.5px] text-amber-900">
        <div className="font-semibold">
          {ref_.relevance ?? ref_.filename ?? 'Missing artefact'}
        </div>
        <div className="font-mono text-[11px] text-amber-800 mt-0.5">
          artifact {ref_.artifact_id.slice(0, 8)} — not available on this case any more.
        </div>
      </div>
    )
  }

  const label = artifactLabel(artifact, ref_.relevance)
  const baseUrl = artifact.download_url ?? null
  const isImg = isImageArtifact(artifact)
  const isPdf = isPdfArtifact(artifact)
  const isHtml = isHtmlArtifact(artifact)
  // PDFs deep-link to the relevant page when the evidence carries one
  // (e.g. L4 `annexure_page_hint`). Browsers honour the #page=N
  // fragment in their built-in PDF viewer.
  const url =
    baseUrl && isPdf && typeof ref_.page === 'number'
      ? `${baseUrl}${baseUrl.includes('#') ? '&' : '#'}page=${ref_.page}`
      : baseUrl
  const downloadUrl = artifact.attachment_url ?? artifact.download_url ?? null

  const canPreview = !!url && (isImg || isPdf || isHtml)

  return (
    <div className="rounded border border-pfl-slate-200 bg-white overflow-hidden">
      <div className="px-3 py-2 flex items-center gap-2 text-[12.5px]">
        {isImg ? (
          <ImageIcon className="h-3.5 w-3.5 text-pfl-slate-500 shrink-0" />
        ) : (
          <FileTextIcon className="h-3.5 w-3.5 text-pfl-slate-500 shrink-0" />
        )}
        <div className="flex flex-col min-w-0 flex-1">
          <span className="font-semibold text-pfl-slate-800 truncate">{label}</span>
          <span className="font-mono text-[11px] text-pfl-slate-500 truncate">
            {artifact.filename}
            {artifact.size_bytes != null && <> · {formatBytes(artifact.size_bytes)}</>}
            {ref_.page != null && <> · page {ref_.page}</>}
            {!isImg && !isPdf && !isHtml && artifact.content_type && (
              <> · {artifact.content_type}</>
            )}
          </span>
        </div>
        <div className="ml-2 flex items-center gap-2 shrink-0">
          {canPreview && (
            <button
              type="button"
              onClick={() => setShowPreview((v) => !v)}
              className="inline-flex items-center gap-1 text-[11px] text-pfl-slate-700 hover:text-pfl-slate-900"
              title={
                showPreview
                  ? 'Hide inline preview'
                  : 'Load inline preview (no auto-download)'
              }
            >
              {showPreview ? (
                <>
                  <EyeOffIcon className="h-3 w-3" /> Hide
                </>
              ) : (
                <>
                  <EyeIcon className="h-3 w-3" /> Preview
                </>
              )}
            </button>
          )}
          {url && (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-[11px] text-pfl-blue-700 hover:underline"
            >
              <ExternalLinkIcon className="h-3 w-3" /> Open
            </a>
          )}
          {downloadUrl && (
            <a
              href={downloadUrl}
              className="inline-flex items-center gap-1 text-[11px] text-pfl-slate-600 hover:text-pfl-slate-900"
            >
              <DownloadIcon className="h-3 w-3" /> Download
            </a>
          )}
          {!url && <span className="text-[11px] text-amber-700">link expired</span>}
        </div>
      </div>
      {canPreview && showPreview && (
        <div className="border-t border-pfl-slate-100 bg-pfl-slate-50/40">
          {isImg && url && (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="block"
            >
              <img
                src={url}
                alt={label}
                className="w-full max-h-80 object-contain bg-white"
              />
            </a>
          )}
          {isPdf && url && (
            <iframe
              src={url}
              title={label}
              className="w-full h-[480px] bg-white"
            />
          )}
          {isHtml && url && (
            <iframe
              src={url}
              title={label}
              className="w-full h-[480px] bg-white"
            />
          )}
        </div>
      )}
    </div>
  )
}
