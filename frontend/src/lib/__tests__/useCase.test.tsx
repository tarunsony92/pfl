/**
 * Tests for useCase and related hooks.
 *
 * Mocks SWR and api.cases to verify key shapes and happy paths.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'

// ---------------------------------------------------------------------------
// Mock SWR — return data synchronously via a mock implementation
// ---------------------------------------------------------------------------

const mockUseSWR = vi.fn()

vi.mock('swr', () => ({
  default: (...args: unknown[]) => mockUseSWR(...args),
}))

// Mock api module
vi.mock('@/lib/api', () => ({
  cases: {
    get: vi.fn(),
    extractions: vi.fn(),
    checklistValidation: vi.fn(),
    dedupeMatches: vi.fn(),
    auditLog: vi.fn(),
  },
}))

import { useCase, useCaseExtractions, useCaseChecklist } from '../useCase'

// ---------------------------------------------------------------------------
// Helper consumer components
// ---------------------------------------------------------------------------

function CaseConsumer({ caseId }: { caseId: string }) {
  const { data, error, isLoading } = useCase(caseId)
  if (isLoading) return <div data-testid="loading">Loading</div>
  if (error) return <div data-testid="error">Error</div>
  return <div data-testid="data">{data ? (data as { loan_id: string }).loan_id : 'null'}</div>
}

function ExtractionsConsumer({ caseId }: { caseId: string }) {
  const { data, isLoading } = useCaseExtractions(caseId)
  if (isLoading) return <div data-testid="loading">Loading</div>
  return <div data-testid="data">{data ? String(data.length) : '0'}</div>
}

function ChecklistConsumer({ caseId }: { caseId: string }) {
  const { data, isLoading } = useCaseChecklist(caseId)
  if (isLoading) return <div data-testid="loading">Loading</div>
  return <div data-testid="data">{data ? 'has-checklist' : 'no-checklist'}</div>
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useCase', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns data when SWR resolves', async () => {
    mockUseSWR.mockReturnValue({
      data: { loan_id: 'LOAN-001', id: 'abc' },
      error: null,
      isLoading: false,
      mutate: vi.fn(),
    })

    render(<CaseConsumer caseId="abc" />)
    expect(screen.getByTestId('data')).toHaveTextContent('LOAN-001')
  })

  it('shows loading state', () => {
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: null,
      isLoading: true,
      mutate: vi.fn(),
    })

    render(<CaseConsumer caseId="abc" />)
    expect(screen.getByTestId('loading')).toBeInTheDocument()
  })

  it('shows error state', () => {
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: new Error('Network error'),
      isLoading: false,
      mutate: vi.fn(),
    })

    render(<CaseConsumer caseId="abc" />)
    expect(screen.getByTestId('error')).toBeInTheDocument()
  })

  it('passes null key when caseId is empty string', () => {
    mockUseSWR.mockReturnValue({
      data: undefined,
      error: null,
      isLoading: false,
      mutate: vi.fn(),
    })

    render(<CaseConsumer caseId="" />)
    // SWR should have been called with null key
    const call = mockUseSWR.mock.calls[0]
    expect(call[0]).toBeNull()
  })
})

describe('useCaseExtractions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns extractions array', () => {
    mockUseSWR.mockReturnValue({
      data: [{ id: 'e1' }, { id: 'e2' }],
      error: null,
      isLoading: false,
      mutate: vi.fn(),
    })

    render(<ExtractionsConsumer caseId="abc" />)
    expect(screen.getByTestId('data')).toHaveTextContent('2')
  })

  it('uses correct SWR key', () => {
    mockUseSWR.mockReturnValue({
      data: [],
      error: null,
      isLoading: false,
      mutate: vi.fn(),
    })

    render(<ExtractionsConsumer caseId="test-id" />)
    const key = mockUseSWR.mock.calls[0][0]
    expect(key).toEqual(['case-extractions', 'test-id'])
  })
})

describe('useCaseChecklist', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns checklist result', () => {
    mockUseSWR.mockReturnValue({
      data: { is_complete: true, present_docs: [], missing_docs: [], validated_at: '2026-01-01T00:00:00Z' },
      error: null,
      isLoading: false,
      mutate: vi.fn(),
    })

    render(<ChecklistConsumer caseId="abc" />)
    expect(screen.getByTestId('data')).toHaveTextContent('has-checklist')
  })

  it('uses correct SWR key', () => {
    mockUseSWR.mockReturnValue({
      data: null,
      error: null,
      isLoading: false,
      mutate: vi.fn(),
    })

    render(<ChecklistConsumer caseId="case-xyz" />)
    const key = mockUseSWR.mock.calls[0][0]
    expect(key).toEqual(['case-checklist', 'case-xyz'])
  })
})
