'use client'

/**
 * UploadSnapshotDialog — admin dialog to upload a new dedupe snapshot (xlsx).
 *
 * On confirm: api.dedupeSnapshots.upload(file) → toast → onUploaded callback.
 */

import React, { useRef, useState } from 'react'
import { UploadCloudIcon } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/use-toast'
import { api } from '@/lib/api'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface UploadSnapshotDialogProps {
  onUploaded: () => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function UploadSnapshotDialog({ onUploaded }: UploadSnapshotDialogProps) {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  async function handleUpload() {
    if (!file) {
      toast({ title: 'No file selected', variant: 'destructive' })
      return
    }
    setLoading(true)
    try {
      const result = await api.dedupeSnapshots.upload(file)
      toast({
        title: 'Snapshot uploaded',
        description: `${file.name} uploaded with ${result.row_count} rows.`,
      })
      setOpen(false)
      setFile(null)
      onUploaded()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Upload failed'
      toast({ title: 'Upload failed', description: msg, variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }

  function handleOpenChange(val: boolean) {
    if (!val) setFile(null)
    setOpen(val)
  }

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        <UploadCloudIcon className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
        Upload New
      </Button>

      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Upload Dedupe Snapshot</DialogTitle>
            <DialogDescription>
              Upload an Excel (.xlsx) file with a &ldquo;Customer_Dedupe&rdquo; sheet. The
              previous active snapshot will be deactivated.
            </DialogDescription>
          </DialogHeader>

          <div className="mt-3 flex flex-col gap-4">
            <div>
              <label htmlFor="snapshot-file" className="block text-sm font-medium text-pfl-slate-700 mb-1">
                File <span aria-hidden="true" className="text-red-500">*</span>
              </label>
              <input
                id="snapshot-file"
                type="file"
                accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ref={fileRef}
                className="block w-full text-sm text-pfl-slate-700 file:mr-3 file:rounded file:border file:border-pfl-slate-300 file:px-3 file:py-1 file:text-xs file:font-medium file:bg-pfl-slate-50 file:text-pfl-slate-700 hover:file:bg-pfl-slate-100 cursor-pointer"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>

            {file && (
              <p className="text-xs text-pfl-slate-500">
                Selected: <span className="font-medium">{file.name}</span>{' '}
                ({(file.size / 1024).toFixed(1)} KB)
              </p>
            )}
          </div>

          <div className="mt-4 flex justify-end gap-2">
            <DialogClose asChild>
              <Button variant="ghost" size="sm" disabled={loading}>
                Cancel
              </Button>
            </DialogClose>
            <Button
              size="sm"
              disabled={loading || !file}
              onClick={handleUpload}
            >
              {loading ? 'Uploading…' : 'Upload snapshot'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
