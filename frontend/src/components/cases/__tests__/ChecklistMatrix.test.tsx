/**
 * Tests for ChecklistMatrix component.
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'
import { ChecklistMatrix } from '../ChecklistMatrix'
import type { ChecklistValidationResultRead } from '@/lib/types'

function makeResult(overrides: Partial<ChecklistValidationResultRead> = {}): ChecklistValidationResultRead {
  return {
    id: '00000000-0000-0000-0000-000000000001',
    case_id: '00000000-0000-0000-0000-000000000002',
    is_complete: true,
    present_docs: [],
    missing_docs: [],
    validated_at: '2026-01-01T10:00:00+00:00',
    ...overrides,
  }
}

describe('ChecklistMatrix', () => {
  it('shows "not yet run" when notRun=true', () => {
    render(<ChecklistMatrix notRun />)
    expect(screen.getByText(/not yet run/i)).toBeInTheDocument()
  })

  it('shows "not yet run" when no result', () => {
    render(<ChecklistMatrix />)
    expect(screen.getByText(/not yet run/i)).toBeInTheDocument()
  })

  it('renders skeleton while loading', () => {
    render(<ChecklistMatrix isLoading />)
    expect(screen.getByTestId('checklist-skeleton')).toBeInTheDocument()
  })

  it('shows COMPLETE badge when is_complete=true', () => {
    render(<ChecklistMatrix result={makeResult({ is_complete: true })} />)
    expect(screen.getByText('COMPLETE')).toBeInTheDocument()
  })

  it('shows INCOMPLETE badge when is_complete=false', () => {
    render(<ChecklistMatrix result={makeResult({ is_complete: false })} />)
    expect(screen.getByText('INCOMPLETE')).toBeInTheDocument()
  })

  it('renders present docs', () => {
    const result = makeResult({
      present_docs: [{ name: 'Aadhaar Card', artifact_id: 'art-123' }],
    })
    render(<ChecklistMatrix result={result} />)
    expect(screen.getByText('Aadhaar Card')).toBeInTheDocument()
  })

  it('renders missing docs with reason', () => {
    const result = makeResult({
      is_complete: false,
      missing_docs: [{ name: 'PAN Card', reason: 'Not uploaded' }],
    })
    render(<ChecklistMatrix result={result} />)
    expect(screen.getByText('PAN Card')).toBeInTheDocument()
    expect(screen.getByText('Not uploaded')).toBeInTheDocument()
  })

  it('shows counts in section headers', () => {
    const result = makeResult({
      present_docs: [{ name: 'Doc A' }, { name: 'Doc B' }],
      missing_docs: [{ name: 'Doc C' }],
    })
    render(<ChecklistMatrix result={result} />)
    expect(screen.getByText(/Present \(2\)/i)).toBeInTheDocument()
    expect(screen.getByText(/Missing \(1\)/i)).toBeInTheDocument()
  })
})
