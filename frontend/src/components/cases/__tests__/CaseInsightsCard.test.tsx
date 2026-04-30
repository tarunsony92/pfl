/**
 * Tests for CaseInsightsCard component.
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'
import { CaseInsightsCard } from '../CaseInsightsCard'
import type { CaseExtractionRead, DedupeMatchRead, CaseArtifactRead } from '@/lib/types'

function makeExtraction(name: string, data: Record<string, unknown>, overrides: Partial<CaseExtractionRead> = {}): CaseExtractionRead {
  return {
    id: `00000000-0000-0000-0000-${name.replace(/[^0-9a-f]/g, '0').slice(0, 12)}`,
    case_id: '00000000-0000-0000-0000-000000000001',
    artifact_id: null,
    extractor_name: name,
    schema_version: '1.0',
    status: 'SUCCESS',
    data,
    warnings: null,
    error_message: null,
    extracted_at: '2026-01-01T10:00:00+00:00',
    created_at: '2026-01-01T10:00:00+00:00',
    ...overrides,
  }
}

function makeArtifact(id: string): CaseArtifactRead {
  return {
    id,
    filename: 'test.pdf',
    artifact_type: 'ORIGINAL_ZIP',
    size_bytes: 1000,
    content_type: 'application/pdf',
    uploaded_at: '2026-01-01T10:00:00+00:00',
  }
}

const emptyProps = {
  extractions: [],
  dedupeMatches: [],
  artifacts: [],
}

describe('CaseInsightsCard', () => {
  it('renders the AI Insights heading', () => {
    render(<CaseInsightsCard {...emptyProps} />)
    expect(screen.getByText('AI Insights')).toBeInTheDocument()
  })

  it('shows — with "not extracted" note when no extractions', () => {
    render(<CaseInsightsCard {...emptyProps} />)
    // Should see multiple "not extracted" notes
    const notes = screen.getAllByText(/not extracted/i)
    expect(notes.length).toBeGreaterThan(0)
  })

  it('shows applicant name from auto_cam extraction', () => {
    const extractions = [
      makeExtraction('auto_cam', {
        system_cam: { applicant_name: 'AJAY SINGH', date_of_birth: '17-11-2001', pan: 'OWLPS6441C', loan_amount: 100000 },
        eligibility: { cibil_score: 750, foir: 0.181 },
        health_sheet: { total_monthly_income: 36000, total_monthly_expense: 10000 },
      }),
    ]
    render(<CaseInsightsCard {...emptyProps} extractions={extractions} />)
    expect(screen.getByText('AJAY SINGH')).toBeInTheDocument()
  })

  it('falls back to case applicant name when no auto_cam', () => {
    render(<CaseInsightsCard {...emptyProps} caseApplicantName="SEEMA DEVI" />)
    expect(screen.getByText('SEEMA DEVI')).toBeInTheDocument()
  })

  it('shows CIBIL score badge green when > 750', () => {
    const extractions = [
      makeExtraction('auto_cam', {
        eligibility: { cibil_score: 780 },
      }),
    ]
    render(<CaseInsightsCard {...emptyProps} extractions={extractions} />)
    const badge = screen.getByText('780')
    expect(badge).toBeInTheDocument()
    expect(badge.className).toMatch(/green/)
  })

  it('shows CIBIL score badge red when < 700', () => {
    const extractions = [
      makeExtraction('auto_cam', {
        eligibility: { cibil_score: 650 },
      }),
    ]
    render(<CaseInsightsCard {...emptyProps} extractions={extractions} />)
    const badge = screen.getByText('650')
    expect(badge.className).toMatch(/red/)
  })

  it('shows dedupe match count', () => {
    const matches: DedupeMatchRead[] = [
      {
        id: '00000000-0000-0000-0000-000000000001',
        case_id: '00000000-0000-0000-0000-000000000002',
        snapshot_id: '00000000-0000-0000-0000-000000000003',
        match_type: 'PAN',
        match_score: 0.95,
        matched_customer_id: 'CUST-1',
        matched_details_json: {},
        created_at: '2026-01-01T10:00:00+00:00',
      },
    ]
    render(<CaseInsightsCard {...emptyProps} dedupeMatches={matches} />)
    // Should show '1'
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('shows no active snapshot warning when dedupe has no_active_snapshot warning', () => {
    const extractions = [
      makeExtraction('dedupe', {}, { warnings: ['no_active_snapshot'] }),
    ]
    render(<CaseInsightsCard {...emptyProps} extractions={extractions} />)
    expect(screen.getByText(/no active snapshot/i)).toBeInTheDocument()
  })

  it('shows artifact classification count', () => {
    const artifacts = [makeArtifact('a1'), makeArtifact('a2')]
    render(<CaseInsightsCard {...emptyProps} artifacts={artifacts} />)
    // 0 of 2 classified (no metadata_json)
    expect(screen.getByText('0 of 2')).toBeInTheDocument()
  })
})
