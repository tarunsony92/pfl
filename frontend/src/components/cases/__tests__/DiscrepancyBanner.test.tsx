/**
 * Tests for DiscrepancyBanner — the Overview-tab alert that surfaces
 * unresolved CAM discrepancies.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render as rtlRender, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'
import { SWRConfig } from 'swr'

vi.mock('@/lib/api', () => ({
  api: {
    cases: {
      camDiscrepancies: vi.fn(),
      camDiscrepancyReportUrl: (id: string) => `/cases/${id}/cam-discrepancies/report`,
    },
  },
}))

import { DiscrepancyBanner } from '../DiscrepancyBanner'
import { api } from '@/lib/api'
import type { CamDiscrepancySummary } from '@/lib/types'

const CASE_ID = '00000000-0000-0000-0000-000000000001'

function render(ui: React.ReactElement) {
  return rtlRender(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      {ui}
    </SWRConfig>,
  )
}

const mockFn = api.cases.camDiscrepancies as ReturnType<typeof vi.fn>

function summary(overrides: Partial<CamDiscrepancySummary>): CamDiscrepancySummary {
  return {
    case_id: CASE_ID,
    generated_at: '2026-04-22T00:00:00+00:00',
    total: 0,
    unresolved_critical: 0,
    unresolved_warning: 0,
    phase1_blocked: false,
    views: [],
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('DiscrepancyBanner', () => {
  it('renders nothing when there are no open discrepancies', async () => {
    mockFn.mockResolvedValue(summary({}))
    render(<DiscrepancyBanner caseId={CASE_ID} />)
    // Give SWR one flush + ensure banner never appears
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByTestId('discrepancy-banner')).not.toBeInTheDocument()
  })

  it('shows red-tone CRITICAL banner when Phase 1 is blocked', async () => {
    mockFn.mockResolvedValue(
      summary({
        total: 1,
        unresolved_critical: 1,
        phase1_blocked: true,
      }),
    )
    render(<DiscrepancyBanner caseId={CASE_ID} />)
    const banner = await screen.findByTestId('discrepancy-banner')
    expect(banner).toHaveTextContent(/1 CRITICAL CAM/i)
    expect(banner).toHaveTextContent(/Phase 1 decisioning is blocked/i)
  })

  it('shows amber WARNING banner when only warnings are open', async () => {
    mockFn.mockResolvedValue(
      summary({
        total: 2,
        unresolved_warning: 2,
      }),
    )
    render(<DiscrepancyBanner caseId={CASE_ID} />)
    const banner = await screen.findByTestId('discrepancy-banner')
    expect(banner).toHaveTextContent(/2 CAM warnings/i)
    expect(banner).toHaveTextContent(/Phase 1 is NOT blocked/i)
  })

  it('invokes onGoToTab when Review is clicked', async () => {
    mockFn.mockResolvedValue(
      summary({ total: 1, unresolved_critical: 1, phase1_blocked: true }),
    )
    const jump = vi.fn()
    render(<DiscrepancyBanner caseId={CASE_ID} onGoToTab={jump} />)
    const btn = await screen.findByTestId('discrepancy-banner-jump')
    fireEvent.click(btn)
    expect(jump).toHaveBeenCalled()
  })
})
