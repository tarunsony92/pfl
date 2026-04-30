'use client'

/**
 * AddArtifactDialog — file upload dialog for adding a missing artifact.
 *
 * Visible when stage === CHECKLIST_MISSING_DOCS.
 * On confirm: api.cases.addArtifact(caseId, file) → toast → SWR mutate.
 */

import React, { useRef, useState } from 'react'
import { PlusCircleIcon } from 'lucide-react'
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
import { cases as casesApi } from '@/lib/api'
import type { KeyedMutator } from 'swr'
import type { CaseRead } from '@/lib/types'

interface AddArtifactDialogProps {
  caseId: string
  mutateCase: KeyedMutator<CaseRead>
}

export function AddArtifactDialog({ caseId, mutateCase }: AddArtifactDialogProps) {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  async function handleConfirm() {
    if (!file) {
      toast({ title: 'No file selected', variant: 'destructive' })
      return
    }
    setLoading(true)
    try {
      await casesApi.addArtifact(caseId, file)
      toast({ title: 'Artifact added', description: `${file.name} uploaded successfully.` })
      setOpen(false)
      setFile(null)
      await mutateCase()
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      toast({ title: 'Upload failed', description: message, variant: 'destructive' })
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
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <PlusCircleIcon className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
        Add missing artifact
      </Button>

      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add missing artifact</DialogTitle>
            <DialogDescription>
              Upload a file to satisfy a missing checklist document requirement.
            </DialogDescription>
          </DialogHeader>

          <div className="mt-3 flex flex-col gap-3">
            <div>
              <label htmlFor="artifact-file" className="block text-sm font-medium text-pfl-slate-700 mb-1">
                File
              </label>
              <input
                id="artifact-file"
                type="file"
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
              variant="default"
              size="sm"
              disabled={loading || !file}
              onClick={handleConfirm}
            >
              {loading ? 'Uploading…' : 'Upload artifact'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
