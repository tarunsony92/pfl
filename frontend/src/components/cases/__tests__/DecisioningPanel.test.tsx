/**
 * Tests for DecisioningPanel component.
 *
 * We mock the SWR hooks (useDecisionResult, useDecisionSteps) so no network
 * or real SWR infrastructure is needed.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'

// Mock SWR hooks
vi.mock('@/lib/useDecisioning', () => ({
  useDecisionResult: vi.fn(),
  useDecisionSteps: vi.fn(),
}))

// Mock API
vi.mock('@/lib/api', () => ({
  cases: {
    phase1Start: vi.fn(),
    phase1Cancel: vi.fn(),
  },
}))

import { DecisioningPanel } from '../DecisioningPanel'
import { useDecisionResult, useDecisionSteps } from '@/lib/useDecisioning'
import { cases as casesApi } from '@/lib/api'
import type { DecisionResultRead, DecisionStepRead } from '@/lib/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const mockUseDecisionResult = useDecisionResult as ReturnType<typeof vi.fn>
const mockUseDecisionSteps = useDecisionSteps as ReturnType<typeof vi.fn>
const mockPhase1Start = casesApi.phase1Start as ReturnType<typeof vi.fn>

const CASE_ID = '00000000-0000-0000-0000-000000000001'
const DR_ID = '00000000-0000-0000-0000-000000000002'

function makeDr(overrides: Partial<DecisionResultRead> = {}): DecisionResultRead {
  return {
    id: DR_ID,
    case_id: CASE_ID,
    phase: 'phase1',
    status: 'PENDING',
    final_decision: null,
    recommended_amount: null,
    recommended_tenure: null,
    conditions: null,
    reasoning_markdown: null,
    pros_cons: null,
    deviations: null,
    risk_summary: null,
    confidence_score: null,
    token_usage: null,
    total_cost_usd: null,
    error_message: null,
    triggered_by: null,
    started_at: null,
    completed_at: null,
    created_at: '2026-01-01T10:00:00+00:00',
    updated_at: '2026-01-01T10:00:00+00:00',
    ...overrides,
  }
}

function makeStep(overrides: Partial<DecisionStepRead> = {}): DecisionStepRead {
  return {
    id: '00000000-0000-0000-0000-000000000010',
    decision_result_id: DR_ID,
    step_number: 1,
    step_name: 'policy_gates',
    model_used: null,
    status: 'SUCCEEDED',
    input_tokens: null,
    output_tokens: null,
    cache_read_tokens: null,
    cache_creation_tokens: null,
    cost_usd: null,
    output_data: null,
    citations: null,
    error_message: null,
    started_at: '2026-01-01T10:00:00+00:00',
    completed_at: '2026-01-01T10:00:01+00:00',
    created_at: '2026-01-01T10:00:00+00:00',
    updated_at: '2026-01-01T10:00:01+00:00',
    ...overrides,
  }
}

function defaultNoResult() {
  mockUseDecisionResult.mockReturnValue({
    data: undefined,
    error: { status: 404 },
    isLoading: false,
    mutate: vi.fn(),
  })
  mockUseDecisionSteps.mockReturnValue({
    data: undefined,
    error: undefined,
    isLoading: false,
    mutate: vi.fn(),
  })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DecisioningPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows "Start Phase 1" button when case is INGESTED and no result exists', () => {
    defaultNoResult()
    render(
      <DecisioningPanel caseId={CASE_ID} currentStage="INGESTED" isAdmin={false} />,
    )
    expect(screen.getByTestId('start-phase1-btn')).toBeInTheDocument()
    expect(screen.getByTestId('ready-msg')).toBeInTheDocument()
  })

  it('does NOT show "Start Phase 1" button when case is not INGESTED', () => {
    defaultNoResult()
    render(
      <DecisioningPanel caseId={CASE_ID} currentStage="PHASE_1_DECISIONING" isAdmin={false} />,
    )
    expect(screen.queryByTestId('start-phase1-btn')).not.toBeInTheDocument()
    expect(screen.getByTestId('no-result-msg')).toBeInTheDocument()
  })

  it('shows status badge when a decision result exists', () => {
    const mutateMock = vi.fn()
    mockUseDecisionResult.mockReturnValue({
      data: makeDr({ status: 'RUNNING' }),
      error: undefined,
      isLoading: false,
      mutate: mutateMock,
    })
    mockUseDecisionSteps.mockReturnValue({ data: [], error: undefined, isLoading: false, mutate: vi.fn() })

    render(
      <DecisioningPanel caseId={CASE_ID} currentStage="PHASE_1_DECISIONING" isAdmin={false} />,
    )
    expect(screen.getByTestId('decision-status-badge')).toHaveTextContent('RUNNING')
  })

  it('shows step rows when steps are present', () => {
    mockUseDecisionResult.mockReturnValue({
      data: makeDr({ status: 'RUNNING' }),
      error: undefined,
      isLoading: false,
      mutate: vi.fn(),
    })
    mockUseDecisionSteps.mockReturnValue({
      data: [
        makeStep({ step_number: 1, step_name: 'policy_gates', status: 'SUCCEEDED' }),
        makeStep({ step_number: 2, step_name: 'banking_check', status: 'RUNNING', id: '00000000-0000-0000-0000-000000000011' }),
      ],
      error: undefined,
      isLoading: false,
      mutate: vi.fn(),
    })

    render(
      <DecisioningPanel caseId={CASE_ID} currentStage="PHASE_1_DECISIONING" isAdmin={false} />,
    )

    expect(screen.getByTestId('steps-table')).toBeInTheDocument()
    expect(screen.getByTestId('step-row-1')).toBeInTheDocument()
    expect(screen.getByTestId('step-row-2')).toBeInTheDocument()
    expect(screen.getByText('policy_gates')).toBeInTheDocument()
    expect(screen.getByText('banking_check')).toBeInTheDocument()
  })

  it('renders final decision card when COMPLETED', () => {
    mockUseDecisionResult.mockReturnValue({
      data: makeDr({
        status: 'COMPLETED',
        final_decision: 'APPROVE',
        recommended_amount: 500000,
        recommended_tenure: 24,
        confidence_score: 82,
        conditions: ['Collateral required'],
        reasoning_markdown: 'Based on strong cash flow...',
      }),
      error: undefined,
      isLoading: false,
      mutate: vi.fn(),
    })
    mockUseDecisionSteps.mockReturnValue({ data: [], error: undefined, isLoading: false, mutate: vi.fn() })

    render(
      <DecisioningPanel caseId={CASE_ID} currentStage="PHASE_1_COMPLETE" isAdmin={false} />,
    )

    expect(screen.getByTestId('decision-card')).toBeInTheDocument()
    expect(screen.getByTestId('outcome-badge')).toHaveTextContent('APPROVE')
    expect(screen.getByTestId('conditions-list')).toBeInTheDocument()
    expect(screen.getByTestId('reasoning-markdown')).toHaveTextContent('Based on strong cash flow')
  })

  it('shows Cancel button for admin when run is active', () => {
    const mutateMock = vi.fn()
    mockUseDecisionResult.mockReturnValue({
      data: makeDr({ status: 'PENDING' }),
      error: undefined,
      isLoading: false,
      mutate: mutateMock,
    })
    mockUseDecisionSteps.mockReturnValue({ data: [], error: undefined, isLoading: false, mutate: vi.fn() })

    render(
      <DecisioningPanel caseId={CASE_ID} currentStage="PHASE_1_DECISIONING" isAdmin={true} />,
    )
    expect(screen.getByTestId('cancel-phase1-btn')).toBeInTheDocument()
  })

  it('does NOT show Cancel button for non-admin', () => {
    mockUseDecisionResult.mockReturnValue({
      data: makeDr({ status: 'PENDING' }),
      error: undefined,
      isLoading: false,
      mutate: vi.fn(),
    })
    mockUseDecisionSteps.mockReturnValue({ data: [], error: undefined, isLoading: false, mutate: vi.fn() })

    render(
      <DecisioningPanel caseId={CASE_ID} currentStage="PHASE_1_DECISIONING" isAdmin={false} />,
    )
    expect(screen.queryByTestId('cancel-phase1-btn')).not.toBeInTheDocument()
  })

  it('calls phase1Start API when Start Phase 1 is clicked', async () => {
    const mutateMock = vi.fn()
    mockUseDecisionResult.mockReturnValue({
      data: undefined,
      error: { status: 404 },
      isLoading: false,
      mutate: mutateMock,
    })
    mockUseDecisionSteps.mockReturnValue({ data: undefined, error: undefined, isLoading: false, mutate: vi.fn() })
    mockPhase1Start.mockResolvedValue({ decision_result_id: DR_ID })

    render(
      <DecisioningPanel caseId={CASE_ID} currentStage="INGESTED" isAdmin={false} />,
    )

    const btn = screen.getByTestId('start-phase1-btn')
    fireEvent.click(btn)

    await waitFor(() => {
      expect(mockPhase1Start).toHaveBeenCalledWith(CASE_ID)
      expect(mutateMock).toHaveBeenCalled()
    })
  })

  // -------------------------------------------------------------------------
  // API usage + cost summary
  // -------------------------------------------------------------------------

  it('renders the API usage summary with totals and per-tier breakdown', () => {
    mockUseDecisionResult.mockReturnValue({
      data: makeDr({ status: 'COMPLETED', total_cost_usd: '0.2742' }),
      error: undefined,
      isLoading: false,
      mutate: vi.fn(),
    })
    mockUseDecisionSteps.mockReturnValue({
      data: [
        makeStep({
          step_number: 2,
          step_name: 'banking_check',
          model_used: 'claude-haiku-4-5',
          input_tokens: 1200,
          output_tokens: 300,
          cache_read_tokens: 500,
          cache_creation_tokens: 800,
          cost_usd: '0.003',
        }),
        makeStep({
          step_number: 5,
          step_name: 'address_verification',
          model_used: 'claude-sonnet-4-6',
          input_tokens: 2000,
          output_tokens: 400,
          cache_read_tokens: 1500,
          cache_creation_tokens: 0,
          cost_usd: '0.02',
        }),
        makeStep({
          step_number: 11,
          step_name: 'final_synthesis',
          model_used: 'claude-opus-4-7',
          input_tokens: 4000,
          output_tokens: 1200,
          cache_read_tokens: 0,
          cache_creation_tokens: 0,
          cost_usd: '0.25',
        }),
      ],
      error: undefined,
      isLoading: false,
      mutate: vi.fn(),
    })

    render(<DecisioningPanel caseId={CASE_ID} currentStage="PHASE_1_COMPLETE" isAdmin={false} />)

    const summary = screen.getByTestId('usage-summary')
    expect(summary).toBeInTheDocument()
    expect(summary).toHaveTextContent('$0.2742') // top-line total cost
    expect(summary).toHaveTextContent('7.2k')    // sum of input tokens (1.2k + 2k + 4k)

    // Per-tier table has all three tiers with their costs
    const tierTable = screen.getByTestId('usage-by-tier')
    expect(tierTable).toHaveTextContent(/opus/i)
    expect(tierTable).toHaveTextContent(/sonnet/i)
    expect(tierTable).toHaveTextContent(/haiku/i)
    expect(tierTable).toHaveTextContent('$0.2500') // opus cost
  })

  it('shows token columns per step', () => {
    mockUseDecisionResult.mockReturnValue({
      data: makeDr({ status: 'RUNNING' }),
      error: undefined,
      isLoading: false,
      mutate: vi.fn(),
    })
    mockUseDecisionSteps.mockReturnValue({
      data: [
        makeStep({
          step_number: 3,
          step_name: 'income_analysis',
          model_used: 'claude-haiku-4-5',
          input_tokens: 1234,
          output_tokens: 56,
          cost_usd: '0.0014',
        }),
      ],
      error: undefined,
      isLoading: false,
      mutate: vi.fn(),
    })

    render(<DecisioningPanel caseId={CASE_ID} currentStage="PHASE_1_DECISIONING" isAdmin={false} />)
    const row = screen.getByTestId('step-row-3')
    expect(row).toHaveTextContent('1.2k')   // input tokens compact
    expect(row).toHaveTextContent('56')     // output tokens
    expect(row).toHaveTextContent('$0.0014') // per-step cost
  })
})
