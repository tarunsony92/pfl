'use client'

/**
 * Step 2 — Upload ZIP file.
 *
 * Uses a presigned S3 URL + fields (FormData POST).
 * Shows filename, size, and an upload progress indicator.
 */

import React, { useRef, useState } from 'react'
import { UploadCloudIcon, CheckCircleIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { toast } from '@/components/ui/use-toast'
import type { CaseInitiateResponse } from '@/lib/types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface Step2UploadProps {
  presigned: CaseInitiateResponse
  onNext: () => void
  onBack: () => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Step2Upload({ presigned, onNext, onBack }: Step2UploadProps) {
  const [file, setFile] = useState<File | null>(null)
  const [progress, setProgress] = useState<number | null>(null) // 0-100 or null
  const [uploaded, setUploaded] = useState(false)
  const [uploading, setUploading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null
    setFile(f)
    setProgress(null)
    setUploaded(false)
  }

  async function handleUpload() {
    if (!file) {
      toast({ title: 'No file selected', variant: 'destructive' })
      return
    }
    setUploading(true)
    setProgress(0)

    try {
      const form = new FormData()
      // Append all presigned fields first, then the file last
      for (const [key, value] of Object.entries(presigned.upload_fields)) {
        form.append(key, value)
      }
      form.append('file', file)

      // Use XMLHttpRequest for progress tracking
      await new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', presigned.upload_url, true)

        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            setProgress(Math.round((e.loaded / e.total) * 100))
          }
        }

        xhr.onload = () => {
          // S3 / LocalStack returns 204 or 200 on success
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve()
          } else {
            reject(new Error(`Upload failed: HTTP ${xhr.status}`))
          }
        }

        xhr.onerror = () => reject(new Error('Network error during upload'))
        xhr.send(form)
      })

      setProgress(100)
      setUploaded(true)
      toast({ title: 'Upload complete', description: `${file.name} uploaded successfully.` })
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Upload failed'
      toast({ title: 'Upload failed', description: msg, variant: 'destructive' })
      setProgress(null)
    } finally {
      setUploading(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Step 2 — Upload ZIP</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {/* Drop zone / file input */}
        <div
          className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-pfl-slate-300 bg-pfl-slate-50 py-10 gap-3 cursor-pointer hover:border-pfl-blue-400 transition-colors"
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
          }}
          tabIndex={0}
          role="button"
          aria-label="Click to select a ZIP file"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            const dropped = e.dataTransfer.files?.[0]
            if (dropped) {
              setFile(dropped)
              setProgress(null)
              setUploaded(false)
            }
          }}
        >
          <UploadCloudIcon className="h-10 w-10 text-pfl-slate-400" aria-hidden="true" />
          <p className="text-sm text-pfl-slate-600">
            Drag &amp; drop or <span className="text-pfl-blue-700 font-medium underline">browse</span>
          </p>
          <p className="text-xs text-pfl-slate-400">.zip files only</p>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept=".zip,application/zip"
          className="sr-only"
          onChange={handleFileChange}
          aria-label="File upload"
        />

        {/* File info */}
        {file && (
          <div className="rounded border border-pfl-slate-200 bg-white px-4 py-3 flex items-center justify-between gap-3">
            <div className="flex flex-col">
              <span className="text-sm font-medium text-pfl-slate-900">{file.name}</span>
              <span className="text-xs text-pfl-slate-500">{formatBytes(file.size)}</span>
            </div>
            {uploaded && <CheckCircleIcon className="h-5 w-5 text-green-500 flex-shrink-0" aria-label="Uploaded" />}
          </div>
        )}

        {/* Progress bar */}
        {progress !== null && (
          <div
            role="progressbar"
            aria-valuenow={progress}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Upload progress"
            className="w-full rounded-full bg-pfl-slate-200 overflow-hidden h-2"
          >
            <div
              className="h-2 bg-pfl-blue-600 transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
        )}
        {progress !== null && (
          <p className="text-xs text-pfl-slate-500 text-right">{progress}%</p>
        )}

        {/* Actions */}
        <div className="flex justify-between pt-2">
          <Button variant="ghost" onClick={onBack} disabled={uploading}>
            Back
          </Button>
          <div className="flex gap-2">
            {!uploaded && (
              <Button onClick={handleUpload} disabled={!file || uploading}>
                {uploading ? 'Uploading…' : 'Upload'}
              </Button>
            )}
            {uploaded && (
              <Button onClick={onNext}>
                Next: Finalize
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
