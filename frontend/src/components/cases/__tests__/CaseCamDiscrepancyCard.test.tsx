/**
 * Tests for CaseCamDiscrepancyCard — in-data conflict detection across the
 * AutoCAM sheets (SystemCam ↔ CM CAM IL).
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'
import {
  CaseCamDiscrepancyCard,
  detectCamConflicts,
} from '../CaseCamDiscrepancyCard'
import type { CaseExtractionRead } from '@/lib/types'

function makeAutoCam(data: Record<string, unknown>, id = 'a'): CaseExtractionRead {
  return {
    id: `00000000-0000-0000-0000-${id.padStart(12, '0')}`,
    case_id: '00000000-0000-0000-0000-000000000001',
    artifact_id: null,
    extractor_name: 'auto_cam',
    schema_version: '1.0',
    status: 'SUCCESS',
    data,
    warnings: null,
    error_message: null,
    extracted_at: '2026-01-01T10:00:00+00:00',
    created_at: '2026-01-01T10:00:00+00:00',
  } as CaseExtractionRead
}

describe('detectCamConflicts', () => {
  it('returns empty when sheets agree', () => {
    const r = detectCamConflicts([
      makeAutoCam({
        system_cam: { applicant_name: 'AJAY SINGH', pan: 'OWLPS6441C', loan_amount: '100000' },
        cm_cam_il: { borrower_name: 'AJAY SINGH', pan_number: 'OWLPS6441C', loan_required: '100000', foir: 0.181 },
        eligibility: { foir: 0.181 },
        health_sheet: { foir: 0.181 },
      }),
    ])
    expect(r).toEqual([])
  })

  it('flags applicant-name mismatch between SystemCam and CM CAM IL as critical', () => {
    const r = detectCamConflicts([
      makeAutoCam({
        system_cam: { applicant_name: 'AJAY SINGH' },
        cm_cam_il: { borrower_name: 'RAJU SINGH' },
      }),
    ])
    const nameDisc = r.find((d) => d.field === 'applicant_name')
    expect(nameDisc).toBeDefined()
    expect(nameDisc!.severity).toBe('critical')
    expect(nameDisc!.values.length).toBeGreaterThanOrEqual(2)
  })

  it('tolerates ≤0.5 pct-pt FOIR drift across sheets', () => {
    const r = detectCamConflicts([
      makeAutoCam({
        cm_cam_il: { foir: 0.181 },
        health_sheet: { foir: 0.184 },
      }),
    ])
    expect(r.find((d) => d.field === 'foir')).toBeUndefined()
  })

  it('flags FOIR mismatch >0.5 pct-pt as warning', () => {
    const r = detectCamConflicts([
      makeAutoCam({
        cm_cam_il: { foir: 0.181 },
        health_sheet: { foir: 0.22 },
      }),
    ])
    const f = r.find((d) => d.field === 'foir')
    expect(f).toBeDefined()
    expect(f!.severity).toBe('warning')
  })

  it('normalises PAN casing before comparing', () => {
    const r = detectCamConflicts([
      makeAutoCam({
        system_cam: { pan: 'owlps6441c' },
        cm_cam_il: { pan_number: 'OWLPS6441C' },
      }),
    ])
    expect(r.find((d) => d.field === 'pan')).toBeUndefined()
  })

  it('returns nothing when no auto_cam extraction is present', () => {
    expect(detectCamConflicts([])).toEqual([])
  })
})

describe('<CaseCamDiscrepancyCard/>', () => {
  it('renders the clean state when there are no conflicts', () => {
    render(
      <CaseCamDiscrepancyCard
        extractions={[
          makeAutoCam({
            system_cam: { applicant_name: 'X', pan: 'ABCDE1234F' },
            cm_cam_il: { borrower_name: 'X', pan_number: 'ABCDE1234F' },
          }),
        ]}
      />,
    )
    expect(screen.getByText(/All sheets agree/i)).toBeInTheDocument()
  })

  it('renders discrepancy rows when fields disagree', () => {
    render(
      <CaseCamDiscrepancyCard
        extractions={[
          makeAutoCam({
            system_cam: { applicant_name: 'AJAY SINGH', pan: 'OWLPS6441C' },
            cm_cam_il: { borrower_name: 'RAJU SINGH', pan_number: 'OWLPS6441C' },
          }),
        ]}
      />,
    )
    expect(screen.getByText(/Applicant name/i)).toBeInTheDocument()
    expect(screen.getByText(/AJAY SINGH/i)).toBeInTheDocument()
    expect(screen.getByText(/RAJU SINGH/i)).toBeInTheDocument()
  })

  it('renders nothing when no auto_cam extraction is present', () => {
    const { container } = render(<CaseCamDiscrepancyCard extractions={[]} />)
    expect(container.firstChild).toBeNull()
  })
})
