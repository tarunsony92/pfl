/**
 * Tests for DiscrepanciesPanel.
 *
 * We mock the api + SWR so no network is needed. Focus: correct rendering
 * of summary bar + per-field cards, resolve form validation, role-gated
 * Approve / Reject buttons on edit-request cards.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render as rtlRender, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'
import { SWRConfig } from 'swr'

// Each render gets a fresh SWR cache provider so data from previous tests
// doesn't leak in. Without this, the mocks resolve but the component shows
// the cached empty state from the previous test.
function render(ui: React.ReactElement) {
  return rtlRender(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {ui}
    </SWRConfig>,
  )
}

vi.mock('@/lib/api', () => ({
  api: {
    cases: {
      camDiscrepancies: vi.fn(),
      resolveCamDiscrepancy: vi.fn(),
      camDiscrepancyReportUrl: (id: string) => `/cases/${id}/cam-discrepancies/report`,
      camDiscrepancyReportXlsxUrl: (id: string) =>
        `/cases/${id}/cam-discrepancies/report.xlsx`,
      listSystemCamEditRequests: vi.fn(),
      decideSystemCamEditRequest: vi.fn(),
    },
  },
}))

import { DiscrepanciesPanel } from '../DiscrepanciesPanel'
import { api } from '@/lib/api'
import type {
  CamDiscrepancySummary,
  SystemCamEditRequestRead,
} from '@/lib/types'

const CASE_ID = '00000000-0000-0000-0000-000000000001'

function makeSummary(
  views: CamDiscrepancySummary['views'],
  overrides: Partial<CamDiscrepancySummary> = {},
): CamDiscrepancySummary {
  const unresolvedCritical = views.filter(
    (v) => v.flag && !v.resolution && v.flag.severity === 'CRITICAL',
  ).length
  const unresolvedWarning = views.filter(
    (v) => v.flag && !v.resolution && v.flag.severity === 'WARNING',
  ).length
  return {
    case_id: CASE_ID,
    generated_at: '2026-04-22T00:00:00+00:00',
    total: views.length,
    unresolved_critical: unresolvedCritical,
    unresolved_warning: unresolvedWarning,
    phase1_blocked: unresolvedCritical > 0,
    views,
    ...overrides,
  }
}

const mockCamDiscrepancies = api.cases.camDiscrepancies as ReturnType<typeof vi.fn>
const mockListEditRequests = api.cases.listSystemCamEditRequests as ReturnType<typeof vi.fn>
const mockResolve = api.cases.resolveCamDiscrepancy as ReturnType<typeof vi.fn>
const mockDecide = api.cases.decideSystemCamEditRequest as ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.clearAllMocks()
  mockCamDiscrepancies.mockResolvedValue(makeSummary([]))
  mockListEditRequests.mockResolvedValue([])
})

describe('DiscrepanciesPanel', () => {
  it('renders empty state when no discrepancies', async () => {
    render(<DiscrepanciesPanel caseId={CASE_ID} userRole="ai_analyser" />)
    await waitFor(() => {
      expect(screen.getByTestId('discrepancies-empty')).toBeInTheDocument()
    })
    expect(screen.getByTestId('discrepancies-panel')).toHaveTextContent('OPEN')
  })

  it('renders a critical open discrepancy card with a resolve form', async () => {
    mockCamDiscrepancies.mockResolvedValue(
      makeSummary([
        {
          field_key: 'pan',
          field_label: 'PAN',
          flag: {
            field_key: 'pan',
            field_label: 'PAN',
            system_cam_value: 'OWLPS6441C',
            cm_cam_il_value: 'WRONG1234F',
            severity: 'CRITICAL',
            tolerance_description: 'exact',
            note: 'PAN mismatch',
          },
        },
      ]),
    )
    render(<DiscrepanciesPanel caseId={CASE_ID} userRole="ai_analyser" />)
    await waitFor(() => {
      expect(screen.getByTestId('discrepancy-card-pan')).toBeInTheDocument()
    })
    expect(screen.getByText(/Phase 1 blocked/i)).toBeInTheDocument()
    expect(screen.getByTestId('corrected-value-pan')).toBeInTheDocument()
    expect(screen.getByTestId('comment-pan')).toBeInTheDocument()
  })

  it('disables Save until corrected_value + comment are filled', async () => {
    mockCamDiscrepancies.mockResolvedValue(
      makeSummary([
        {
          field_key: 'pan',
          field_label: 'PAN',
          flag: {
            field_key: 'pan',
            field_label: 'PAN',
            system_cam_value: 'OWLPS6441C',
            cm_cam_il_value: 'WRONG1234F',
            severity: 'CRITICAL',
            tolerance_description: 'exact',
            note: '',
          },
        },
      ]),
    )
    render(<DiscrepanciesPanel caseId={CASE_ID} userRole="ai_analyser" />)
    const submit = await screen.findByTestId('resolve-submit-pan')
    expect(submit).toBeDisabled()

    // Add only a short comment — still disabled
    const comment = screen.getByTestId('comment-pan') as HTMLTextAreaElement
    fireEvent.change(comment, { target: { value: 'short' } })
    expect(submit).toBeDisabled()

    // Full comment — now enabled (corrected_value already has systemcam default)
    fireEvent.change(comment, {
      target: { value: 'Manual entry typo — correcting to finpage value.' },
    })
    expect(submit).not.toBeDisabled()
  })

  it('non-admin sees no Approve/Reject buttons on a pending edit request', async () => {
    const pendingReq: SystemCamEditRequestRead = {
      id: '00000000-0000-0000-0000-000000000010',
      case_id: CASE_ID,
      resolution_id: null,
      field_key: 'pan',
      field_label: 'PAN',
      current_system_cam_value: 'OLDVAL',
      requested_system_cam_value: 'NEWVAL',
      justification: 'Finpage PAN is stale',
      status: 'PENDING',
      requested_by: '00000000-0000-0000-0000-000000000002',
      requested_at: '2026-04-22T00:00:00+00:00',
      decided_by: null,
      decided_at: null,
      decision_comment: null,
      created_at: '2026-04-22T00:00:00+00:00',
    }
    mockListEditRequests.mockResolvedValue([pendingReq])
    render(<DiscrepanciesPanel caseId={CASE_ID} userRole="ai_analyser" />)
    await waitFor(() => {
      expect(screen.getByText(/Pending CEO \/ admin decision/i)).toBeInTheDocument()
    })
    expect(screen.queryByTestId(`edit-req-approve-${pendingReq.id}`)).not.toBeInTheDocument()
  })

  it('admin sees Approve + Reject on pending edit request', async () => {
    const pendingReq: SystemCamEditRequestRead = {
      id: '00000000-0000-0000-0000-000000000011',
      case_id: CASE_ID,
      resolution_id: null,
      field_key: 'pan',
      field_label: 'PAN',
      current_system_cam_value: 'OLDVAL',
      requested_system_cam_value: 'NEWVAL',
      justification: 'Finpage PAN is stale',
      status: 'PENDING',
      requested_by: '00000000-0000-0000-0000-000000000002',
      requested_at: '2026-04-22T00:00:00+00:00',
      decided_by: null,
      decided_at: null,
      decision_comment: null,
      created_at: '2026-04-22T00:00:00+00:00',
    }
    mockListEditRequests.mockResolvedValue([pendingReq])
    render(<DiscrepanciesPanel caseId={CASE_ID} userRole="admin" />)
    expect(await screen.findByTestId(`edit-req-approve-${pendingReq.id}`)).toBeInTheDocument()
    expect(screen.getByTestId(`edit-req-reject-${pendingReq.id}`)).toBeInTheDocument()
  })

  it('shows the download report link', async () => {
    render(<DiscrepanciesPanel caseId={CASE_ID} userRole="ai_analyser" />)
    const link = await screen.findByTestId('discrepancies-report-download')
    expect(link).toHaveAttribute(
      'href',
      `/api/proxy/cases/${CASE_ID}/cam-discrepancies/report`,
    )
  })
})
