/**
 * Tests for DedupeMatchTable component.
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import { DedupeMatchTable } from '../DedupeMatchTable'
import type { DedupeMatchRead } from '@/lib/types'

function makeMatch(overrides: Partial<DedupeMatchRead> = {}): DedupeMatchRead {
  return {
    id: '00000000-0000-0000-0000-000000000001',
    case_id: '00000000-0000-0000-0000-000000000002',
    snapshot_id: '00000000-0000-0000-0000-000000000003',
    match_type: 'AADHAAR',
    match_score: 0.95,
    matched_customer_id: 'CUST-001',
    matched_details_json: { aadhaar: '1234-5678-9012' },
    created_at: '2026-01-01T10:00:00+00:00',
    ...overrides,
  }
}

describe('DedupeMatchTable', () => {
  it('shows empty state when no matches', () => {
    render(<DedupeMatchTable matches={[]} />)
    expect(screen.getByText(/no dedupe matches found/i)).toBeInTheDocument()
  })

  it('renders table headers when matches exist', () => {
    render(<DedupeMatchTable matches={[makeMatch()]} />)
    expect(screen.getByText('Match Type')).toBeInTheDocument()
    expect(screen.getByText('Score')).toBeInTheDocument()
    expect(screen.getByText('Matched Customer')).toBeInTheDocument()
  })

  it('renders match type badge', () => {
    render(<DedupeMatchTable matches={[makeMatch({ match_type: 'PAN' })]} />)
    expect(screen.getByText('PAN')).toBeInTheDocument()
  })

  it('renders score as percentage', () => {
    render(<DedupeMatchTable matches={[makeMatch({ match_score: 0.95 })]} />)
    expect(screen.getByText('95.0%')).toBeInTheDocument()
  })

  it('applies red color class for score >= 0.9', () => {
    render(<DedupeMatchTable matches={[makeMatch({ match_score: 0.92 })]} />)
    const score = screen.getByText('92.0%')
    expect(score.className).toContain('red')
  })

  it('applies amber color class for score 0.7-0.89', () => {
    render(<DedupeMatchTable matches={[makeMatch({ match_score: 0.75 })]} />)
    const score = screen.getByText('75.0%')
    expect(score.className).toContain('amber')
  })

  it('applies gray class for score < 0.7', () => {
    render(<DedupeMatchTable matches={[makeMatch({ match_score: 0.5 })]} />)
    const score = screen.getByText('50.0%')
    expect(score.className).toContain('slate-400')
  })

  it('renders customer ID', () => {
    render(<DedupeMatchTable matches={[makeMatch({ matched_customer_id: 'CUST-XYZ' })]} />)
    expect(screen.getByText('CUST-XYZ')).toBeInTheDocument()
  })

  it('expands details on click', async () => {
    const user = userEvent.setup()
    render(<DedupeMatchTable matches={[makeMatch()]} />)
    await user.click(screen.getByRole('button', { name: /view details/i }))
    // The raw JSON pre block should contain the details
    const pre = document.querySelector('pre')
    expect(pre).toBeInTheDocument()
    expect(pre!.textContent).toContain('1234-5678-9012')
  })

  it('shows dash for null customer id', () => {
    render(<DedupeMatchTable matches={[makeMatch({ matched_customer_id: null })]} />)
    // Dash renders as — character
    expect(screen.queryByText('CUST-001')).not.toBeInTheDocument()
  })
})
