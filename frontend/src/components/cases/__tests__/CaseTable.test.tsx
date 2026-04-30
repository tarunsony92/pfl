/**
 * Tests for CaseTable component.
 *
 * Covers:
 *   - rendering case rows
 *   - empty state + "Clear filters" CTA
 *   - loading skeleton state
 *   - pagination prev/next buttons
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'

// Mock next/link so it renders an anchor without the Next.js router context.
vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [k: string]: unknown }) =>
    React.createElement('a', { href, ...props }, children),
}))

import { CaseTable } from '../CaseTable'
import type { CaseRead } from '@/lib/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeCase(overrides: Partial<CaseRead> = {}): CaseRead {
  return {
    id: '00000000-0000-0000-0000-000000000001',
    loan_id: 'LOAN-001',
    applicant_name: 'Alice Smith',
    uploaded_by: 'aaaaaaaa-0000-0000-0000-000000000001',
    uploaded_at: '2026-01-01T10:00:00+00:00',
    finalized_at: null,
    current_stage: 'INGESTED',
    assigned_to: null,
    reupload_count: 0,
    reupload_allowed_until: null,
    is_deleted: false,
    created_at: '2026-01-01T10:00:00+00:00',
    updated_at: '2026-01-01T10:00:00+00:00',
    artifacts: [],
    ...overrides,
  }
}

const defaultProps = {
  cases: [],
  isLoading: false,
  total: 0,
  limit: 10,
  offset: 0,
  onPageChange: vi.fn(),
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('CaseTable', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders table headers', () => {
    render(<CaseTable {...defaultProps} />)
    expect(screen.getByText('Loan ID')).toBeInTheDocument()
    expect(screen.getByText('Applicant')).toBeInTheDocument()
    expect(screen.getByText('Stage')).toBeInTheDocument()
    expect(screen.getByText('Uploaded by')).toBeInTheDocument()
    expect(screen.getByText('Uploaded at')).toBeInTheDocument()
    expect(screen.getByText('Actions')).toBeInTheDocument()
  })

  it('renders case rows', () => {
    const cases = [
      makeCase({ id: 'id-1', loan_id: 'LOAN-A', applicant_name: 'Alice' }),
      makeCase({ id: 'id-2', loan_id: 'LOAN-B', applicant_name: 'Bob' }),
    ]
    render(<CaseTable {...defaultProps} cases={cases} total={2} />)
    expect(screen.getByText('LOAN-A')).toBeInTheDocument()
    expect(screen.getByText('LOAN-B')).toBeInTheDocument()
    expect(screen.getByText('Alice')).toBeInTheDocument()
    expect(screen.getByText('Bob')).toBeInTheDocument()
  })

  it('renders a View link per row', () => {
    const cases = [makeCase({ id: 'case-uuid-1', loan_id: 'LOAN-X' })]
    render(<CaseTable {...defaultProps} cases={cases} total={1} />)
    const viewLink = screen.getByRole('link', { name: /view/i })
    expect(viewLink).toHaveAttribute('href', '/cases/case-uuid-1')
  })

  it('shows empty state when no cases', () => {
    render(<CaseTable {...defaultProps} />)
    expect(screen.getByText(/no cases match/i)).toBeInTheDocument()
  })

  it('calls onClearFilters when empty state CTA is clicked', async () => {
    const onClearFilters = vi.fn()
    const user = userEvent.setup()
    render(<CaseTable {...defaultProps} onClearFilters={onClearFilters} />)
    await user.click(screen.getByTestId('empty-clear-filters'))
    expect(onClearFilters).toHaveBeenCalledOnce()
  })

  it('shows skeleton rows while loading', () => {
    render(<CaseTable {...defaultProps} isLoading={true} />)
    // Skeleton rows should be present; no "No cases" message
    expect(screen.queryByText(/no cases match/i)).not.toBeInTheDocument()
  })

  it('disables Prev button at offset=0', () => {
    const cases = [makeCase()]
    render(<CaseTable {...defaultProps} cases={cases} total={20} offset={0} />)
    expect(screen.getByRole('button', { name: /prev/i })).toBeDisabled()
  })

  it('disables Next button when on last page', () => {
    const cases = [makeCase()]
    // total=1, limit=10 → no next page
    render(<CaseTable {...defaultProps} cases={cases} total={1} />)
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled()
  })

  it('calls onPageChange with correct offset on Next click', async () => {
    const onPageChange = vi.fn()
    const user = userEvent.setup()
    const cases = Array.from({ length: 10 }, (_, i) =>
      makeCase({ id: `id-${i}`, loan_id: `L-${i}` }),
    )
    render(
      <CaseTable
        {...defaultProps}
        cases={cases}
        total={25}
        limit={10}
        offset={0}
        onPageChange={onPageChange}
      />,
    )
    await user.click(screen.getByRole('button', { name: /next/i }))
    expect(onPageChange).toHaveBeenCalledWith(10)
  })

  it('shows user full_name from userMap', () => {
    const cases = [makeCase({ uploaded_by: 'user-id-abc' })]
    const userMap = { 'user-id-abc': 'John Doe' }
    render(<CaseTable {...defaultProps} cases={cases} total={1} userMap={userMap} />)
    expect(screen.getByText('John Doe')).toBeInTheDocument()
  })
})
