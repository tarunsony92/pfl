'use client'

/**
 * /admin/negative-areas — admin manages the negative-area pincode list.
 *
 * The list drives L5 rule #11 (negative_area_check). On every L5 run, the
 * orchestrator looks up the case's pincode against the active rows here:
 *   - row exists & is_active=true → rule FAILs
 *   - row missing or is_active=false → rule PASSes
 *   - case has no detected pincode → rule stays PENDING
 *
 * Admins can:
 *   - Add a single pincode with optional reason
 *   - Bulk-paste a list (one per line or comma-separated) — duplicates and
 *     malformed entries are skipped silently with a count
 *   - Toggle a row active/inactive (deactivate = stop blocking new cases)
 *   - Delete a row permanently
 */

import { useCallback, useState } from 'react'
import useSWR from 'swr'
import {
  MapPinOffIcon,
  PlusIcon,
  TrashIcon,
  UploadIcon,
  Loader2Icon,
} from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/use-toast'
import { useRequireAdmin } from '@/lib/useRequireAdmin'
import { adminNegativeArea, type NegativeAreaEntry } from '@/lib/api'
import { cn } from '@/lib/cn'

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 30) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

export default function NegativeAreasPage() {
  const { ready } = useRequireAdmin()
  const [showAdd, setShowAdd] = useState(false)
  const [showBulk, setShowBulk] = useState(false)

  const { data, error, isLoading, mutate } = useSWR(
    ready ? ['admin-negative-areas'] : null,
    () => adminNegativeArea.list(false),
    { revalidateOnFocus: false },
  )

  const handleAdd = useCallback(
    async (pincode: string, reason: string | null) => {
      const created = await adminNegativeArea.create({ pincode, reason })
      await mutate(
        (prev) => [created, ...(prev ?? [])],
        { revalidate: false },
      )
      toast({ title: `Pincode ${pincode} added` })
    },
    [mutate],
  )

  const handleBulk = useCallback(
    async (pincodes: string[], reason: string | null) => {
      const res = await adminNegativeArea.bulkUpload({ pincodes, reason })
      await mutate()
      toast({
        title: `Bulk upload complete`,
        description: `${res.inserted} added · ${res.skipped_duplicates} duplicates skipped${
          res.skipped_invalid.length
            ? ` · ${res.skipped_invalid.length} invalid (${res.skipped_invalid.slice(0, 3).join(', ')}${res.skipped_invalid.length > 3 ? '…' : ''})`
            : ''
        }`,
      })
    },
    [mutate],
  )

  const handleToggle = useCallback(
    async (entry: NegativeAreaEntry) => {
      const updated = await adminNegativeArea.patch(entry.id, {
        is_active: !entry.is_active,
      })
      await mutate(
        (prev) =>
          (prev ?? []).map((e) => (e.id === updated.id ? updated : e)),
        { revalidate: false },
      )
      toast({
        title: updated.is_active ? 'Activated' : 'Deactivated',
        description: `Pincode ${updated.pincode}`,
      })
    },
    [mutate],
  )

  const handleDelete = useCallback(
    async (entry: NegativeAreaEntry) => {
      if (!window.confirm(`Delete pincode ${entry.pincode}? This cannot be undone.`)) {
        return
      }
      await adminNegativeArea.delete(entry.id)
      await mutate(
        (prev) => (prev ?? []).filter((e) => e.id !== entry.id),
        { revalidate: false },
      )
      toast({ title: `Deleted ${entry.pincode}` })
    },
    [mutate],
  )

  if (!ready) {
    return (
      <div className="flex flex-col gap-4 py-8">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    )
  }

  const entries = data ?? []
  const activeCount = entries.filter((e) => e.is_active).length

  return (
    <>
      <div className="flex flex-col gap-6">
        <div className="flex items-start justify-between gap-6 flex-wrap">
          <div>
            <h1 className="text-2xl font-bold text-pfl-slate-900 flex items-center gap-2">
              <MapPinOffIcon className="h-6 w-6 text-pfl-blue-700" />
              Negative Areas
            </h1>
            <p className="text-sm text-pfl-slate-600 mt-1 max-w-3xl leading-snug">
              Pincodes flagged as restricted lending zones. L5 rule #11
              (negative_area_check) reads this list on every case — a case
              whose pincode has an active row here fails the rubric.
              Deactivate a row to stop blocking new cases without losing the
              audit trail.
            </p>
          </div>
          <div className="flex items-stretch gap-2 text-[12px]">
            <div className="rounded-md border border-pfl-slate-200 bg-white px-3 py-2 text-pfl-slate-700">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-pfl-slate-500">
                Total
              </div>
              <div className="text-lg font-bold tabular-nums mt-0.5">
                {entries.length}
              </div>
            </div>
            <div className="rounded-md border border-red-200 bg-white px-3 py-2 text-red-700">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-pfl-slate-500">
                Active
              </div>
              <div className="text-lg font-bold tabular-nums mt-0.5">
                {activeCount}
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button onClick={() => setShowAdd(true)} className="flex items-center gap-1.5">
            <PlusIcon className="h-4 w-4" />
            Add pincode
          </Button>
          <Button
            variant="outline"
            onClick={() => setShowBulk(true)}
            className="flex items-center gap-1.5"
          >
            <UploadIcon className="h-4 w-4" />
            Bulk upload
          </Button>
          {isLoading && <Loader2Icon className="h-4 w-4 animate-spin text-pfl-slate-400 ml-2" />}
        </div>

        {error && (
          <div
            role="alert"
            className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            {error instanceof Error ? error.message : 'Failed to load list.'}
          </div>
        )}

        {!isLoading && entries.length === 0 && !error && (
          <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-10 text-center">
            <MapPinOffIcon className="h-8 w-8 text-pfl-slate-300 mx-auto mb-3" />
            <p className="text-sm text-pfl-slate-500 max-w-sm mx-auto">
              No pincodes on the list yet. Add one or paste a batch with the
              buttons above.
            </p>
          </div>
        )}

        {entries.length > 0 && (
          <div className="rounded-md border border-pfl-slate-200 bg-white overflow-x-auto">
            <table className="w-full text-[12.5px] border-collapse">
              <thead>
                <tr className="border-b border-pfl-slate-200 bg-pfl-slate-50">
                  <Th>Pincode</Th>
                  <Th>Reason</Th>
                  <Th>Source</Th>
                  <Th>Status</Th>
                  <Th>Updated</Th>
                  <Th>Actions</Th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry, idx) => (
                  <tr
                    key={entry.id}
                    className={cn(
                      'border-b border-pfl-slate-100 last:border-b-0',
                      idx % 2 === 1 ? 'bg-pfl-slate-50/30' : 'bg-white',
                      !entry.is_active && 'opacity-60',
                    )}
                  >
                    <td className="px-3 py-2.5 font-mono tabular-nums text-pfl-slate-800">
                      {entry.pincode}
                    </td>
                    <td className="px-3 py-2.5 text-pfl-slate-700 max-w-[280px] truncate" title={entry.reason ?? ''}>
                      {entry.reason ?? <span className="text-pfl-slate-400">—</span>}
                    </td>
                    <td className="px-3 py-2.5 text-pfl-slate-500 text-[11px]">
                      {entry.source}
                    </td>
                    <td className="px-3 py-2.5">
                      <span
                        className={cn(
                          'inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider',
                          entry.is_active
                            ? 'bg-red-50 text-red-700 border-red-200'
                            : 'bg-pfl-slate-100 text-pfl-slate-600 border-pfl-slate-300',
                        )}
                      >
                        {entry.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-pfl-slate-500 whitespace-nowrap">
                      <span title={new Date(entry.updated_at).toLocaleString()}>
                        {relativeTime(entry.updated_at)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => handleToggle(entry)}
                          className="px-2 py-0.5 rounded text-[11px] font-semibold border border-pfl-slate-300 hover:bg-pfl-slate-50"
                        >
                          {entry.is_active ? 'Deactivate' : 'Activate'}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(entry)}
                          className="p-1 rounded text-pfl-slate-400 hover:text-red-600 hover:bg-red-50"
                          title="Delete"
                          aria-label="Delete entry"
                        >
                          <TrashIcon className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showAdd && (
        <AddSingleModal
          onClose={() => setShowAdd(false)}
          onSave={handleAdd}
        />
      )}
      {showBulk && (
        <BulkUploadModal
          onClose={() => setShowBulk(false)}
          onSave={handleBulk}
        />
      )}
    </>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-3 py-2.5 text-left text-[10.5px] font-semibold uppercase tracking-wider text-pfl-slate-500 whitespace-nowrap">
      {children}
    </th>
  )
}

function AddSingleModal({
  onClose,
  onSave,
}: {
  onClose: () => void
  onSave: (pincode: string, reason: string | null) => Promise<void>
}) {
  const [pincode, setPincode] = useState('')
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!/^\d{6}$/.test(pincode.trim())) {
      setErr('Pincode must be exactly 6 digits.')
      return
    }
    setSaving(true)
    setErr(null)
    try {
      await onSave(pincode.trim(), reason.trim() || null)
      onClose()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to save.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md border border-pfl-slate-200">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4 p-5">
          <h2 className="text-base font-semibold text-pfl-slate-900">
            Add negative-area pincode
          </h2>
          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500">
              Pincode <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={pincode}
              onChange={(e) => setPincode(e.target.value)}
              placeholder="6-digit pincode, e.g. 560001"
              maxLength={6}
              className="rounded border border-pfl-slate-300 px-3 py-2 text-[13px] font-mono"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500">
              Reason <span className="text-pfl-slate-400 normal-case">· optional</span>
            </label>
            <input
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Flagged by RBI Q2 2026"
              className="rounded border border-pfl-slate-300 px-3 py-2 text-[13px]"
            />
          </div>
          {err && (
            <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
              {err}
            </div>
          )}
          <div className="flex items-center justify-end gap-2 pt-1">
            <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving && <Loader2Icon className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
              Add
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

function BulkUploadModal({
  onClose,
  onSave,
}: {
  onClose: () => void
  onSave: (pincodes: string[], reason: string | null) => Promise<void>
}) {
  const [text, setText] = useState('')
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const parsedCount = text
    .split(/[\s,;\n]+/)
    .map((s) => s.trim())
    .filter(Boolean).length

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const pincodes = text
      .split(/[\s,;\n]+/)
      .map((s) => s.trim())
      .filter(Boolean)
    if (pincodes.length === 0) {
      setErr('Paste at least one pincode.')
      return
    }
    setSaving(true)
    setErr(null)
    try {
      await onSave(pincodes, reason.trim() || null)
      onClose()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to upload.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-xl border border-pfl-slate-200">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4 p-5">
          <h2 className="text-base font-semibold text-pfl-slate-900">
            Bulk upload pincodes
          </h2>
          <p className="text-[12px] text-pfl-slate-600 leading-snug">
            Paste pincodes one per line, or comma/semicolon-separated.
            Duplicates and entries that aren&apos;t exactly 6 digits are skipped.
          </p>
          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500">
              Pincodes <span className="text-red-500">*</span>
            </label>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="560001\n400002\n110037..."
              rows={8}
              className="rounded border border-pfl-slate-300 px-3 py-2 text-[13px] font-mono resize-none"
            />
            <span className="text-[11px] text-pfl-slate-500">
              {parsedCount} entr{parsedCount === 1 ? 'y' : 'ies'} detected
            </span>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500">
              Common reason <span className="text-pfl-slate-400 normal-case">· applies to all</span>
            </label>
            <input
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Restricted by RBI Q2 2026"
              className="rounded border border-pfl-slate-300 px-3 py-2 text-[13px]"
            />
          </div>
          {err && (
            <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
              {err}
            </div>
          )}
          <div className="flex items-center justify-end gap-2 pt-1">
            <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving || parsedCount === 0}>
              {saving && <Loader2Icon className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
              Upload {parsedCount > 0 && `${parsedCount}`}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
