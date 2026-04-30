/**
 * Tests for useCases hook.
 *
 * Mocks SWR and api.cases.list to verify key shapes and filters.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'

// ---------------------------------------------------------------------------
// Mock SWR
// ---------------------------------------------------------------------------

const mockUseSWR = vi.fn()
vi.mock('swr', () => ({
  default: (...args: unknown[]) => mockUseSWR(...args),
}))

vi.mock('@/lib/api', () => ({
  cases: {
    list: vi.fn(),
  },
}))

import { useCases } from '../useCases'

// ---------------------------------------------------------------------------
// Test component
// ---------------------------------------------------------------------------

function CasesConsumer({ stage }: { stage?: string }) {
  const { data, isLoading } = useCases(stage ? { stage } : {})
  if (isLoading) return <div data-testid="loading">Loading</div>
  return (
    <div data-testid="total">{data ? String(data.total) : '0'}</div>
  )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useCases', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns case list data when SWR resolves', () => {
    mockUseSWR.mockReturnValue({
      data: { cases: [], total: 42, limit: 10, offset: 0 },
      error: null,
      isLoading: false,
      isValidating: false,
      mutate: vi.fn(),
    })

    render(<CasesConsumer />)
    expect(screen.getByTestId('total')).toHaveTextContent('42')
  })

  it('shows loading state while fetching', () => {
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: null,
      isLoading: true,
      isValidating: true,
      mutate: vi.fn(),
    })

    render(<CasesConsumer />)
    expect(screen.getByTestId('loading')).toBeInTheDocument()
  })

  it('passes filters in the SWR key', () => {
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: null,
      isLoading: false,
      isValidating: false,
      mutate: vi.fn(),
    })

    render(<CasesConsumer stage="INGESTED" />)

    const [key] = mockUseSWR.mock.calls[0]
    expect(key).toEqual(['cases', { stage: 'INGESTED' }])
  })

  it('uses default empty filters when none provided', () => {
    mockUseSWR.mockReturnValue({
      data: { cases: [], total: 0, limit: 10, offset: 0 },
      error: null,
      isLoading: false,
      isValidating: false,
      mutate: vi.fn(),
    })

    render(<CasesConsumer />)

    const [key] = mockUseSWR.mock.calls[0]
    expect(key).toEqual(['cases', {}])
  })
})
