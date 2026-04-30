/**
 * Tests for CaseFilters component.
 *
 * Covers:
 *   - renders all controls
 *   - stage change calls onChange with correct partial
 *   - loan_id_prefix change calls onChange
 *   - from_date / to_date changes
 *   - "Clear filters" calls onClear
 *   - "Uploaded by" dropdown hidden when no users prop
 *   - "Uploaded by" dropdown visible when users list provided
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import { CaseFilters } from '../CaseFilters'
import type { CaseListFilters } from '@/lib/api'
import type { UserRead } from '@/lib/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeUser(overrides: Partial<UserRead> = {}): UserRead {
  return {
    id: '11111111-0000-0000-0000-000000000001',
    email: 'admin@pfl.com',
    full_name: 'Admin User',
    role: 'admin',
    mfa_enabled: false,
    is_active: true,
    last_login_at: null,
    created_at: '2026-01-01T00:00:00+00:00',
    ...overrides,
  }
}

const emptyFilters: CaseListFilters = {}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('CaseFilters', () => {
  let onChange: ReturnType<typeof vi.fn>
  let onClear: ReturnType<typeof vi.fn>

  beforeEach(() => {
    onChange = vi.fn()
    onClear = vi.fn()
  })

  it('renders stage select', () => {
    render(
      <CaseFilters filters={emptyFilters} onChange={onChange} onClear={onClear} />,
    )
    expect(screen.getByLabelText(/stage/i)).toBeInTheDocument()
  })

  it('renders Loan ID search input', () => {
    render(
      <CaseFilters filters={emptyFilters} onChange={onChange} onClear={onClear} />,
    )
    expect(screen.getByLabelText(/loan id/i)).toBeInTheDocument()
  })

  it('renders From/To date inputs', () => {
    render(
      <CaseFilters filters={emptyFilters} onChange={onChange} onClear={onClear} />,
    )
    expect(screen.getByLabelText(/^from$/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^to$/i)).toBeInTheDocument()
  })

  it('renders Clear filters button', () => {
    render(
      <CaseFilters filters={emptyFilters} onChange={onChange} onClear={onClear} />,
    )
    expect(screen.getByTestId('clear-filters')).toBeInTheDocument()
  })

  it('calls onChange when stage is selected', async () => {
    const user = userEvent.setup()
    render(
      <CaseFilters filters={emptyFilters} onChange={onChange} onClear={onClear} />,
    )
    await user.selectOptions(screen.getByLabelText(/stage/i), 'APPROVED')
    expect(onChange).toHaveBeenCalledWith({ stage: 'APPROVED' })
  })

  it('calls onChange when loan ID is typed', async () => {
    const user = userEvent.setup()
    // Provide a controlled value so the Input reflects cumulative input.
    let currentFilters = { ...emptyFilters }
    const trackedOnChange = vi.fn((partial: Partial<CaseListFilters>) => {
      currentFilters = { ...currentFilters, ...partial }
    })
    const { rerender } = render(
      <CaseFilters filters={currentFilters} onChange={trackedOnChange} onClear={onClear} />,
    )
    const input = screen.getByLabelText(/loan id/i)
    await user.type(input, 'A')
    rerender(<CaseFilters filters={{ loan_id_prefix: 'A' }} onChange={trackedOnChange} onClear={onClear} />)
    await user.type(input, 'B')
    rerender(<CaseFilters filters={{ loan_id_prefix: 'AB' }} onChange={trackedOnChange} onClear={onClear} />)
    await user.type(input, 'C')
    expect(trackedOnChange).toHaveBeenLastCalledWith({ loan_id_prefix: 'ABC' })
  })

  it('calls onClear when Clear filters button clicked', async () => {
    const user = userEvent.setup()
    render(
      <CaseFilters filters={emptyFilters} onChange={onChange} onClear={onClear} />,
    )
    await user.click(screen.getByTestId('clear-filters'))
    expect(onClear).toHaveBeenCalledOnce()
  })

  it('hides Uploaded by dropdown when users prop not provided', () => {
    render(
      <CaseFilters filters={emptyFilters} onChange={onChange} onClear={onClear} />,
    )
    expect(screen.queryByLabelText(/uploaded by/i)).not.toBeInTheDocument()
  })

  it('shows Uploaded by dropdown when users list provided', () => {
    const users = [makeUser()]
    render(
      <CaseFilters
        filters={emptyFilters}
        onChange={onChange}
        onClear={onClear}
        users={users}
      />,
    )
    expect(screen.getByLabelText(/uploaded by/i)).toBeInTheDocument()
    const select = screen.getByLabelText(/uploaded by/i)
    expect(within(select).getByText('Admin User')).toBeInTheDocument()
  })

  it('calls onChange with uploaded_by when user selected', async () => {
    const user = userEvent.setup()
    const users = [makeUser({ id: 'user-uuid-1', full_name: 'Bob' })]
    render(
      <CaseFilters
        filters={emptyFilters}
        onChange={onChange}
        onClear={onClear}
        users={users}
      />,
    )
    await user.selectOptions(screen.getByLabelText(/uploaded by/i), 'user-uuid-1')
    expect(onChange).toHaveBeenCalledWith({ uploaded_by: 'user-uuid-1' })
  })
})
