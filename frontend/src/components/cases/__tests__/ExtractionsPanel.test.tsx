/**
 * Tests for ExtractionsPanel component.
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import { ExtractionsPanel } from '../ExtractionsPanel'
import type { CaseExtractionRead } from '@/lib/types'

function makeExtraction(overrides: Partial<CaseExtractionRead> = {}): CaseExtractionRead {
  return {
    id: '00000000-0000-0000-0000-000000000001',
    case_id: '00000000-0000-0000-0000-000000000002',
    artifact_id: null,
    extractor_name: 'auto_cam',
    schema_version: '1.0',
    status: 'SUCCESS',
    data: { applicant_name: 'Alice', loan_amount: 50000 },
    warnings: null,
    error_message: null,
    extracted_at: '2026-01-01T10:00:00+00:00',
    created_at: '2026-01-01T10:00:00+00:00',
    ...overrides,
  }
}

describe('ExtractionsPanel', () => {
  it('shows empty state when no extractions', () => {
    render(<ExtractionsPanel extractions={[]} />)
    expect(screen.getByText(/no extraction results/i)).toBeInTheDocument()
  })

  it('renders extractor name with friendly label', () => {
    render(<ExtractionsPanel extractions={[makeExtraction({ extractor_name: 'auto_cam' })]} />)
    expect(screen.getByText('AutoCAM')).toBeInTheDocument()
  })

  it('renders extractor name fallback for unknown name', () => {
    render(<ExtractionsPanel extractions={[makeExtraction({ extractor_name: 'CUSTOM_EXT' })]} />)
    expect(screen.getByText('CUSTOM_EXT')).toBeInTheDocument()
  })

  it('shows SUCCESS badge', () => {
    render(<ExtractionsPanel extractions={[makeExtraction({ status: 'SUCCESS' })]} />)
    expect(screen.getByText('SUCCESS')).toBeInTheDocument()
  })

  it('shows FAILED badge', () => {
    render(<ExtractionsPanel extractions={[makeExtraction({ status: 'FAILED' })]} />)
    expect(screen.getByText('FAILED')).toBeInTheDocument()
  })

  it('shows warning count badge when warnings present', () => {
    render(<ExtractionsPanel extractions={[makeExtraction({ warnings: ['warn1', 'warn2'] })]} />)
    expect(screen.getByText(/2 warnings/i)).toBeInTheDocument()
  })

  it('expands panel on click and shows key-value data', async () => {
    const user = userEvent.setup()
    render(<ExtractionsPanel extractions={[makeExtraction()]} />)
    await user.click(screen.getByRole('button', { name: /autocam/i }))
    expect(screen.getByText('applicant_name')).toBeInTheDocument()
    expect(screen.getByText('Alice')).toBeInTheDocument()
  })

  it('shows raw JSON toggle and dumps data', async () => {
    const user = userEvent.setup()
    render(<ExtractionsPanel extractions={[makeExtraction()]} />)
    await user.click(screen.getByRole('button', { name: /autocam/i }))
    await user.click(screen.getByRole('button', { name: /view raw json/i }))
    expect(screen.getByText(/applicant_name/)).toBeInTheDocument()
  })

  it('shows error message when status is FAILED', async () => {
    const user = userEvent.setup()
    const extraction = makeExtraction({ status: 'FAILED', error_message: 'Parse error occurred' })
    render(<ExtractionsPanel extractions={[extraction]} />)
    await user.click(screen.getByRole('button', { name: /auto_cam|autocam/i }))
    expect(screen.getByText('Parse error occurred')).toBeInTheDocument()
  })

  it('shows warnings list when expanded', async () => {
    const user = userEvent.setup()
    const extraction = makeExtraction({ warnings: ['Missing field X'] })
    render(<ExtractionsPanel extractions={[extraction]} />)
    await user.click(screen.getByRole('button', { name: /autocam/i }))
    expect(screen.getByText('Missing field X')).toBeInTheDocument()
  })

  it('renders multiple extractors', () => {
    const extractions = [
      makeExtraction({ id: 'id-1', extractor_name: 'auto_cam' }),
      makeExtraction({ id: 'id-2', extractor_name: 'equifax' }),
    ]
    render(<ExtractionsPanel extractions={extractions} />)
    expect(screen.getByText('AutoCAM')).toBeInTheDocument()
    expect(screen.getByText('Equifax')).toBeInTheDocument()
  })

  // M4: field count chip + PARTIAL styling tests
  it('shows field count chip when data has values', () => {
    render(
      <ExtractionsPanel
        extractions={[makeExtraction({ data: { applicant_name: 'Alice', loan_amount: 50000 } })]}
      />,
    )
    expect(screen.getByText(/2 fields extracted/i)).toBeInTheDocument()
  })

  it('shows SUCCESS when backend=PARTIAL but data extracted and warnings non-critical', () => {
    // Single non-critical warning on a populated extract should read as SUCCESS
    render(
      <ExtractionsPanel
        extractions={[
          makeExtraction({
            status: 'PARTIAL',
            data: { applicant_name: 'Alice' },
            warnings: ['missing_sheet:Elegibilty'],
          }),
        ]}
      />,
    )
    expect(screen.getByText(/^SUCCESS$/i)).toBeInTheDocument()
    expect(screen.queryByText(/data found/i)).not.toBeInTheDocument()
  })

  it('shows FAILED when no fields are extracted regardless of backend PARTIAL', () => {
    render(
      <ExtractionsPanel
        extractions={[
          makeExtraction({
            status: 'PARTIAL',
            data: {},
            warnings: ['missing_sheet:SystemCam'],
          }),
        ]}
      />,
    )
    expect(screen.getByText(/^FAILED$/i)).toBeInTheDocument()
    expect(screen.queryByText(/data found/i)).not.toBeInTheDocument()
  })

  it('shows PARTIAL when backend=PARTIAL has data but a critical warning is present', () => {
    render(
      <ExtractionsPanel
        extractions={[
          makeExtraction({
            status: 'PARTIAL',
            data: { name: 'Alice' },
            warnings: ['missing_credit_score'],
          }),
        ]}
      />,
    )
    expect(screen.getByText(/^PARTIAL$/i)).toBeInTheDocument()
  })

  it('shows PARTIAL when backend=PARTIAL has data but three+ warnings', () => {
    render(
      <ExtractionsPanel
        extractions={[
          makeExtraction({
            status: 'PARTIAL',
            data: { name: 'Alice' },
            warnings: ['w1', 'w2', 'w3'],
          }),
        ]}
      />,
    )
    expect(screen.getByText(/^PARTIAL$/i)).toBeInTheDocument()
  })

  it('shows applicant name next to the extractor label to disambiguate rows', () => {
    const extractions = [
      makeExtraction({
        id: 'id-1',
        extractor_name: 'equifax',
        data: { customer_info: { name: 'AJAY SINGH' }, credit_score: 834, bureau_hit: true },
      }),
      makeExtraction({
        id: 'id-2',
        extractor_name: 'equifax',
        data: { customer_info: { name: 'GORDHAN' }, credit_score: -1, bureau_hit: false },
      }),
    ]
    render(<ExtractionsPanel extractions={extractions} />)
    expect(screen.getByText(/AJAY SINGH/)).toBeInTheDocument()
    expect(screen.getByText(/GORDHAN/)).toBeInTheDocument()
  })

  it('annotates Equifax rows with score / NTC qualifier', () => {
    const extractions = [
      makeExtraction({
        id: 'id-1',
        extractor_name: 'equifax',
        data: { customer_info: { name: 'AJAY SINGH' }, credit_score: 834, bureau_hit: true },
      }),
      makeExtraction({
        id: 'id-2',
        extractor_name: 'equifax',
        data: { customer_info: { name: 'GORDHAN' }, credit_score: -1, bureau_hit: false },
      }),
    ]
    render(<ExtractionsPanel extractions={extractions} />)
    expect(screen.getByText(/score 834/)).toBeInTheDocument()
    expect(screen.getByText(/NTC \/ no bureau record/)).toBeInTheDocument()
  })

  it('PARTIAL section shows data-available note when opened', async () => {
    const user = userEvent.setup()
    render(
      <ExtractionsPanel
        extractions={[
          makeExtraction({
            status: 'PARTIAL',
            data: { applicant_name: 'Alice' },
            warnings: ['missing_credit_score'],
          }),
        ]}
      />,
    )
    await user.click(screen.getByRole('button', { name: /autocam/i }))
    expect(screen.getByText(/data available/i)).toBeInTheDocument()
  })
})
