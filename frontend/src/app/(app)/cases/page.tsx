'use client'

/**
 * Cases list page — /cases
 *
 * Layout:
 *   - Page header: "Cases" + "N matching" count
 *   - CaseFilters (sticky top bar)
 *   - CaseTable with pagination
 *
 * Data: SWR via useCases() hook with 10s staleness.
 * Auth: useAuth() to determine whether to show the "Uploaded by" filter.
 */

import React, { useState, useCallback } from 'react'
import Link from 'next/link'
import { CaseFilters } from '@/components/cases/CaseFilters'
import { CaseTable } from '@/components/cases/CaseTable'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/components/auth/useAuth'
import { useCases } from '@/lib/useCases'
import { users as usersApi } from '@/lib/api'
import type { CaseListFilters } from '@/lib/api'
import type { UserRead } from '@/lib/types'
import useSWR from 'swr'

const PAGE_SIZE = 10

const DEFAULT_FILTERS: CaseListFilters = {
  limit: PAGE_SIZE,
  offset: 0,
}

export default function CasesPage() {
  const { user } = useAuth()
  const isAdmin =
    user?.role === 'admin' || user?.role === 'ceo' || user?.role === 'credit_ho'
  // Backend gate: POST /cases/initiate allows AI_ANALYSER + ADMIN
  const canCreateCase = user?.role === 'ai_analyser' || user?.role === 'admin'

  const [filters, setFilters] = useState<CaseListFilters>(DEFAULT_FILTERS)

  // Fetch user list for admin "Uploaded by" filter
  const { data: userList } = useSWR<UserRead[]>(
    isAdmin ? 'users-list' : null,
    () => usersApi.list(),
  )

  const { data, isLoading, error, mutate } = useCases(filters)

  const handleChange = useCallback(
    (partial: Partial<CaseListFilters>) => {
      setFilters((prev) => ({
        ...prev,
        ...partial,
        // reset pagination on any filter change
        offset: 'offset' in partial ? partial.offset ?? 0 : 0,
      }))
    },
    [],
  )

  const handleClear = useCallback(() => {
    setFilters(DEFAULT_FILTERS)
  }, [])

  const handlePageChange = useCallback((newOffset: number) => {
    setFilters((prev) => ({ ...prev, offset: newOffset }))
  }, [])

  // Build a userId → name map for the table
  const userMap: Record<string, string> = {}
  if (userList) {
    for (const u of userList) {
      userMap[u.id] = u.full_name || u.email
    }
  }

  const totalCount = data?.total ?? 0
  const cases = data?.cases ?? []

  return (
    <div className="flex flex-col gap-0">
      {/* Page header */}
      <div className="px-6 py-5 border-b border-pfl-slate-200 flex items-center justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <h1 className="text-2xl font-bold text-pfl-slate-900">Cases</h1>
          {!isLoading && (
            <span className="text-sm text-pfl-slate-500">
              {totalCount} matching
            </span>
          )}
        </div>
        {canCreateCase && (
          <Button asChild>
            <Link href="/cases/new">+ New Case</Link>
          </Button>
        )}
      </div>

      {/* Filter bar */}
      <CaseFilters
        filters={filters}
        onChange={handleChange}
        onClear={handleClear}
        users={isAdmin ? (userList ?? null) : null}
      />

      {/* Error state */}
      {error && (
        <div
          role="alert"
          className="mx-6 mt-4 rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          Failed to load cases. Please try again.
        </div>
      )}

      {/* Table */}
      <div className="px-6 py-4">
        <CaseTable
          cases={cases}
          isLoading={isLoading}
          total={totalCount}
          limit={filters.limit ?? PAGE_SIZE}
          offset={filters.offset ?? 0}
          onPageChange={handlePageChange}
          onClearFilters={handleClear}
          userMap={userMap}
          onCaseChanged={() => mutate()}
        />
      </div>
    </div>
  )
}
