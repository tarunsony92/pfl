'use client'

/**
 * /admin/mrp-catalogue — admin CRUD surface for the canonical MRP table.
 *
 * Rows are auto-populated by L3 vision (source=AI_ESTIMATED) whenever a new
 * (business_type, item_canonical) pair is encountered. Admins can:
 *   - Filter by business_type
 *   - Add manual entries (source=MANUAL)
 *   - Inline-edit the MRP column (PATCH flips source to OVERRIDDEN_FROM_AI)
 *   - Edit all fields via modal
 *   - Delete entries
 *
 * Admin-only (useRequireAdmin guard).
 */

import React, { useCallback, useRef, useState } from 'react'
import useSWR from 'swr'
import {
  DatabaseIcon,
  PencilIcon,
  TrashIcon,
  PlusIcon,
  Loader2Icon,
  XIcon,
  CheckIcon,
} from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { toast } from '@/components/ui/use-toast'
import { useRequireAdmin } from '@/lib/useRequireAdmin'
import { mrpCatalogue } from '@/lib/api'
import type { MrpEntry } from '@/lib/types'
import { cn } from '@/lib/cn'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BUSINESS_TYPES = [
  { value: '', label: 'All types' },
  { value: 'service', label: 'Service' },
  { value: 'product_trading', label: 'Product / Trading' },
  { value: 'cattle_dairy', label: 'Cattle / Dairy' },
  { value: 'manufacturing', label: 'Manufacturing' },
  { value: 'mixed', label: 'Mixed' },
  { value: 'other', label: 'Other' },
  { value: 'unknown', label: 'Unknown' },
]

const CATEGORIES = [
  { value: 'equipment', label: 'Equipment' },
  { value: 'stock', label: 'Stock' },
  { value: 'consumable', label: 'Consumable' },
  { value: 'other', label: 'Other' },
] as const

type Category = 'equipment' | 'stock' | 'consumable' | 'other'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

function CategoryPill({ category }: { category: Category }) {
  const styles: Record<Category, string> = {
    equipment: 'bg-slate-100 text-slate-700 border-slate-200',
    stock: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    consumable: 'bg-amber-50 text-amber-700 border-amber-200',
    other: 'bg-slate-50 text-slate-500 border-slate-200',
  }
  return (
    <span
      className={cn(
        'inline-block rounded border px-1.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider',
        styles[category],
      )}
    >
      {category}
    </span>
  )
}

function SourcePill({ source }: { source: MrpEntry['source'] }) {
  const styles: Record<MrpEntry['source'], string> = {
    AI_ESTIMATED: 'bg-slate-100 text-slate-600 border-slate-200',
    MANUAL: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    OVERRIDDEN_FROM_AI: 'bg-amber-50 text-amber-700 border-amber-200',
  }
  const labels: Record<MrpEntry['source'], string> = {
    AI_ESTIMATED: 'AI',
    MANUAL: 'Manual',
    OVERRIDDEN_FROM_AI: 'Overridden',
  }
  return (
    <span
      className={cn(
        'inline-block rounded border px-1.5 py-0.5 text-[10.5px] font-semibold',
        styles[source],
      )}
    >
      {labels[source]}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Inline MRP edit cell
// ---------------------------------------------------------------------------

function InlineMrpCell({
  entry,
  onSave,
}: {
  entry: MrpEntry
  onSave: (newMrp: number) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(String(entry.mrp_inr))
  const [saving, setSaving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const startEdit = () => {
    setDraft(String(entry.mrp_inr))
    setEditing(true)
    setTimeout(() => inputRef.current?.select(), 0)
  }

  const cancel = () => {
    setEditing(false)
    setDraft(String(entry.mrp_inr))
  }

  const save = async () => {
    const val = parseInt(draft, 10)
    if (!Number.isFinite(val) || val <= 0) {
      toast({ title: 'Invalid MRP', description: 'Must be a positive integer.', variant: 'destructive' })
      return
    }
    if (val === entry.mrp_inr) {
      setEditing(false)
      return
    }
    setSaving(true)
    try {
      await onSave(val)
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }

  if (editing) {
    return (
      <div className="flex items-center gap-1">
        <span className="text-pfl-slate-400 text-[12px]">₹</span>
        <input
          ref={inputRef}
          type="number"
          min={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') save()
            if (e.key === 'Escape') cancel()
          }}
          className="w-24 rounded border border-pfl-blue-400 px-1.5 py-0.5 text-[12.5px] tabular-nums focus:outline-none focus:ring-1 focus:ring-pfl-blue-500"
        />
        {saving ? (
          <Loader2Icon className="h-3.5 w-3.5 animate-spin text-pfl-slate-400" />
        ) : (
          <>
            <button
              type="button"
              onClick={save}
              className="p-0.5 rounded text-emerald-600 hover:bg-emerald-50"
              aria-label="Save"
            >
              <CheckIcon className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={cancel}
              className="p-0.5 rounded text-pfl-slate-400 hover:bg-pfl-slate-100"
              aria-label="Cancel"
            >
              <XIcon className="h-3.5 w-3.5" />
            </button>
          </>
        )}
      </div>
    )
  }

  return (
    <button
      type="button"
      onClick={startEdit}
      className="group flex items-center gap-1.5 rounded px-1 py-0.5 hover:bg-pfl-slate-50 text-left"
      title="Click to edit MRP"
    >
      <span className="font-mono tabular-nums text-[13px] text-pfl-slate-800">
        ₹{entry.mrp_inr.toLocaleString('en-IN')}
      </span>
      <PencilIcon className="h-3 w-3 text-pfl-slate-300 group-hover:text-pfl-slate-500 transition-colors" />
    </button>
  )
}

// ---------------------------------------------------------------------------
// Add / Edit modal
// ---------------------------------------------------------------------------

interface ModalProps {
  initial?: MrpEntry | null
  onClose: () => void
  onSave: (values: {
    business_type: string
    item_description: string
    category: Category
    mrp_inr: number
    rationale: string | null
  }) => Promise<void>
}

function MrpModal({ initial, onClose, onSave }: ModalProps) {
  const isEdit = !!initial
  const [businessType, setBusinessType] = useState(initial?.business_type ?? '')
  const [itemDescription, setItemDescription] = useState(initial?.item_description ?? '')
  const [category, setCategory] = useState<Category>(initial?.category ?? 'equipment')
  const [mrpInr, setMrpInr] = useState(initial ? String(initial.mrp_inr) : '')
  const [rationale, setRationale] = useState(initial?.rationale ?? '')
  const [saving, setSaving] = useState(false)
  const [validationError, setValidationError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setValidationError(null)

    if (!businessType.trim()) {
      setValidationError('Business type is required.')
      return
    }
    if (!itemDescription.trim()) {
      setValidationError('Item description is required.')
      return
    }
    const mrpVal = parseInt(mrpInr, 10)
    if (!Number.isFinite(mrpVal) || mrpVal <= 0) {
      setValidationError('MRP must be a positive integer.')
      return
    }

    setSaving(true)
    try {
      await onSave({
        business_type: businessType.trim(),
        item_description: itemDescription.trim(),
        category,
        mrp_inr: mrpVal,
        rationale: rationale.trim() || null,
      })
      onClose()
    } catch (e) {
      setValidationError(e instanceof Error ? e.message : 'Failed to save.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg border border-pfl-slate-200">
        <div className="flex items-center justify-between px-5 py-4 border-b border-pfl-slate-200">
          <h2 className="text-base font-semibold text-pfl-slate-900">
            {isEdit ? 'Edit MRP entry' : 'Add new MRP entry'}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-pfl-slate-400 hover:bg-pfl-slate-100"
          >
            <XIcon className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4 p-5">
          {!isEdit && (
            <div className="flex flex-col gap-1">
              <label className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500">
                Business type <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={businessType}
                onChange={(e) => setBusinessType(e.target.value)}
                placeholder="e.g. service, product_trading, cattle_dairy"
                className="rounded border border-pfl-slate-300 px-3 py-2 text-[13px] focus:outline-none focus:ring-1 focus:ring-pfl-blue-500"
              />
            </div>
          )}

          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500">
              Item description <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={itemDescription}
              onChange={(e) => setItemDescription(e.target.value)}
              placeholder="e.g. Industrial sewing machine"
              className="rounded border border-pfl-slate-300 px-3 py-2 text-[13px] focus:outline-none focus:ring-1 focus:ring-pfl-blue-500"
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500">
              Category <span className="text-red-500">*</span>
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as Category)}
              className="rounded border border-pfl-slate-300 px-3 py-2 text-[13px] focus:outline-none focus:ring-1 focus:ring-pfl-blue-500"
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500">
              MRP (₹) <span className="text-red-500">*</span>
            </label>
            <input
              type="number"
              min={1}
              value={mrpInr}
              onChange={(e) => setMrpInr(e.target.value)}
              placeholder="e.g. 45000"
              className="rounded border border-pfl-slate-300 px-3 py-2 text-[13px] font-mono focus:outline-none focus:ring-1 focus:ring-pfl-blue-500"
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-pfl-slate-500">
              Rationale
              <span className="ml-1 font-normal normal-case tracking-normal text-pfl-slate-400">
                · optional
              </span>
            </label>
            <textarea
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              placeholder="e.g. Market survey Q1 2024 — 3 quotes averaged"
              rows={3}
              className="rounded border border-pfl-slate-300 px-3 py-2 text-[13px] resize-none focus:outline-none focus:ring-1 focus:ring-pfl-blue-500"
            />
          </div>

          {validationError && (
            <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
              {validationError}
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving && <Loader2Icon className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
              {isEdit ? 'Save changes' : 'Add entry'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Delete confirm
// ---------------------------------------------------------------------------

function DeleteConfirm({
  entry,
  onClose,
  onConfirm,
}: {
  entry: MrpEntry
  onClose: () => void
  onConfirm: () => Promise<void>
}) {
  const [deleting, setDeleting] = useState(false)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-sm border border-pfl-slate-200 p-5 flex flex-col gap-4">
        <h2 className="text-base font-semibold text-pfl-slate-900">Delete entry?</h2>
        <p className="text-[13px] text-pfl-slate-600 leading-snug">
          This will permanently remove{' '}
          <span className="font-semibold text-pfl-slate-800">
            {entry.item_description}
          </span>{' '}
          from the catalogue. The AI will re-create it on its next vision pass.
        </p>
        <div className="flex items-center justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={deleting}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={deleting}
            onClick={async () => {
              setDeleting(true)
              try {
                await onConfirm()
                onClose()
              } finally {
                setDeleting(false)
              }
            }}
          >
            {deleting && <Loader2Icon className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
            Delete
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function MrpCataloguePage() {
  const { ready } = useRequireAdmin()
  const [businessType, setBusinessType] = useState<string>('')
  const [addOpen, setAddOpen] = useState(false)
  const [editEntry, setEditEntry] = useState<MrpEntry | null>(null)
  const [deleteEntry, setDeleteEntry] = useState<MrpEntry | null>(null)

  const swrKey = ['mrp-catalogue', businessType] as const
  const {
    data,
    error,
    isLoading,
    mutate,
  } = useSWR(
    ready ? swrKey : null,
    () => mrpCatalogue.list(businessType || undefined),
    { revalidateOnFocus: false },
  )

  // Inline MRP save (optimistic)
  const handleInlineMrpSave = useCallback(
    async (entry: MrpEntry, newMrp: number) => {
      // Optimistic update
      await mutate(
        async (prev) => {
          try {
            const updated = await mrpCatalogue.patch(entry.id, { mrp_inr: newMrp })
            return (prev ?? []).map((e) => (e.id === updated.id ? updated : e))
          } catch (e) {
            toast({
              title: 'Failed to update MRP',
              description: e instanceof Error ? e.message : 'Unexpected error',
              variant: 'destructive',
            })
            throw e
          }
        },
        {
          optimisticData: (prev) =>
            (prev ?? []).map((e) =>
              e.id === entry.id ? { ...e, mrp_inr: newMrp, source: 'OVERRIDDEN_FROM_AI' as const } : e,
            ),
          rollbackOnError: true,
        },
      )
      toast({ title: 'MRP updated' })
    },
    [mutate],
  )

  // Add entry
  const handleAdd = useCallback(
    async (values: Parameters<ModalProps['onSave']>[0]) => {
      const created = await mrpCatalogue.create(values)
      await mutate((prev) => [created, ...(prev ?? [])], { revalidate: false })
      toast({ title: 'Entry added' })
    },
    [mutate],
  )

  // Edit entry
  const handleEdit = useCallback(
    async (entry: MrpEntry, values: Parameters<ModalProps['onSave']>[0]) => {
      const updated = await mrpCatalogue.patch(entry.id, {
        item_description: values.item_description,
        category: values.category,
        mrp_inr: values.mrp_inr,
        rationale: values.rationale,
      })
      await mutate(
        (prev) => (prev ?? []).map((e) => (e.id === updated.id ? updated : e)),
        { revalidate: false },
      )
      toast({ title: 'Entry updated' })
    },
    [mutate],
  )

  // Delete entry
  const handleDelete = useCallback(
    async (entry: MrpEntry) => {
      await mrpCatalogue.delete(entry.id)
      await mutate((prev) => (prev ?? []).filter((e) => e.id !== entry.id), {
        revalidate: false,
      })
      toast({ title: 'Entry deleted' })
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

  return (
    <>
      <div className="flex flex-col gap-6">
        {/* Header */}
        <div className="flex items-start justify-between gap-6 flex-wrap">
          <div>
            <h1 className="text-2xl font-bold text-pfl-slate-900 flex items-center gap-2">
              <DatabaseIcon className="h-6 w-6 text-pfl-blue-700" />
              MRP Catalogue
            </h1>
            <p className="text-sm text-pfl-slate-600 mt-1 max-w-3xl leading-snug">
              Canonical per-item MRPs. Auto-populated by L3 vision when new items are
              seen; admin edits propagate to every future case view.
            </p>
          </div>
          {/* Stats */}
          <div className="flex items-stretch gap-2 text-[12px]">
            <div className="rounded-md border border-pfl-slate-200 bg-white px-3 py-2 text-pfl-slate-700">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-pfl-slate-500">
                Total
              </div>
              <div className="text-lg font-bold tabular-nums mt-0.5">{entries.length}</div>
            </div>
            <div className="rounded-md border border-amber-200 bg-white px-3 py-2 text-amber-700">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-pfl-slate-500">
                Overridden
              </div>
              <div className="text-lg font-bold tabular-nums mt-0.5">
                {entries.filter((e) => e.source === 'OVERRIDDEN_FROM_AI').length}
              </div>
            </div>
            <div className="rounded-md border border-emerald-200 bg-white px-3 py-2 text-emerald-700">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-pfl-slate-500">
                Manual
              </div>
              <div className="text-lg font-bold tabular-nums mt-0.5">
                {entries.filter((e) => e.source === 'MANUAL').length}
              </div>
            </div>
          </div>
        </div>

        {/* Filter bar */}
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <label className="text-[12px] text-pfl-slate-600 font-medium whitespace-nowrap">
              Business type
            </label>
            <select
              value={businessType}
              onChange={(e) => setBusinessType(e.target.value)}
              className="rounded-md border border-pfl-slate-300 px-3 py-1.5 text-[13px] focus:outline-none focus:ring-1 focus:ring-pfl-blue-500"
            >
              {BUSINESS_TYPES.map((bt) => (
                <option key={bt.value} value={bt.value}>
                  {bt.label}
                </option>
              ))}
            </select>
            {isLoading && (
              <Loader2Icon className="h-4 w-4 animate-spin text-pfl-slate-400" />
            )}
          </div>
          <Button
            onClick={() => setAddOpen(true)}
            className="flex items-center gap-1.5"
          >
            <PlusIcon className="h-4 w-4" />
            Add new entry
          </Button>
        </div>

        {error && (
          <div
            role="alert"
            className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            {error instanceof Error ? error.message : 'Failed to load MRP catalogue.'}
          </div>
        )}

        {/* Table */}
        {isLoading ? (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : entries.length === 0 ? (
          <div className="rounded border border-pfl-slate-200 bg-pfl-slate-50 p-10 text-center">
            <DatabaseIcon className="h-8 w-8 text-pfl-slate-300 mx-auto mb-3" />
            <p className="text-sm text-pfl-slate-500 max-w-sm mx-auto">
              No catalogue entries yet. They populate automatically as L3 vision
              encounters new items, or you can add one manually.
            </p>
          </div>
        ) : (
          <div className="rounded-md border border-pfl-slate-200 bg-white overflow-x-auto">
            <table className="w-full text-[12.5px] border-collapse">
              <thead>
                <tr className="border-b border-pfl-slate-200 bg-pfl-slate-50">
                  <Th>Business type</Th>
                  <Th>Item description</Th>
                  <Th>Canonical key</Th>
                  <Th>Category</Th>
                  <Th>MRP (₹)</Th>
                  <Th>Source</Th>
                  <Th>Observed</Th>
                  <Th>Updated</Th>
                  <Th>Actions</Th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry, idx) => (
                  <tr
                    key={entry.id}
                    className={cn(
                      'border-b border-pfl-slate-100 last:border-b-0 hover:bg-pfl-slate-50/60',
                      idx % 2 === 1 ? 'bg-pfl-slate-50/30' : 'bg-white',
                    )}
                  >
                    {/* Business type */}
                    <td className="px-3 py-2.5 whitespace-nowrap text-pfl-slate-600">
                      {entry.business_type}
                    </td>

                    {/* Item description — truncated */}
                    <td className="px-3 py-2.5 max-w-[240px]">
                      <span
                        title={entry.item_description}
                        className="block truncate text-pfl-slate-800"
                      >
                        {entry.item_description.length > 60
                          ? entry.item_description.slice(0, 60) + '…'
                          : entry.item_description}
                      </span>
                    </td>

                    {/* Canonical key */}
                    <td className="px-3 py-2.5 max-w-[160px]">
                      <span
                        title={entry.item_canonical}
                        className="block truncate font-mono text-[11px] text-pfl-slate-500"
                      >
                        {entry.item_canonical}
                      </span>
                    </td>

                    {/* Category */}
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <CategoryPill category={entry.category} />
                    </td>

                    {/* MRP — inline editable */}
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <InlineMrpCell
                        entry={entry}
                        onSave={(newMrp) => handleInlineMrpSave(entry, newMrp)}
                      />
                    </td>

                    {/* Source */}
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <SourcePill source={entry.source} />
                    </td>

                    {/* Observed count */}
                    <td className="px-3 py-2.5 whitespace-nowrap text-center text-pfl-slate-600 tabular-nums">
                      {entry.observed_count}
                    </td>

                    {/* Updated at */}
                    <td className="px-3 py-2.5 whitespace-nowrap text-pfl-slate-500">
                      <span title={new Date(entry.updated_at).toLocaleString()}>
                        {relativeTime(entry.updated_at)}
                      </span>
                    </td>

                    {/* Actions */}
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => setEditEntry(entry)}
                          className="p-1 rounded text-pfl-slate-400 hover:text-pfl-blue-600 hover:bg-pfl-blue-50 transition-colors"
                          title="Edit"
                          aria-label="Edit entry"
                        >
                          <PencilIcon className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => setDeleteEntry(entry)}
                          className="p-1 rounded text-pfl-slate-400 hover:text-red-600 hover:bg-red-50 transition-colors"
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

      {/* Add modal */}
      {addOpen && (
        <MrpModal
          onClose={() => setAddOpen(false)}
          onSave={handleAdd}
        />
      )}

      {/* Edit modal */}
      {editEntry && (
        <MrpModal
          initial={editEntry}
          onClose={() => setEditEntry(null)}
          onSave={(values) => handleEdit(editEntry, values)}
        />
      )}

      {/* Delete confirm */}
      {deleteEntry && (
        <DeleteConfirm
          entry={deleteEntry}
          onClose={() => setDeleteEntry(null)}
          onConfirm={() => handleDelete(deleteEntry)}
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
