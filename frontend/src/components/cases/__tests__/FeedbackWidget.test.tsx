/**
 * Tests for FeedbackWidget component.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'

// Mock SWR
vi.mock('swr', () => ({
  default: vi.fn(),
}))

// Mock API
vi.mock('@/lib/api', () => ({
  cases: {
    listFeedback: vi.fn(),
    submitFeedback: vi.fn(),
  },
}))

// Mock toast
vi.mock('@/components/ui/use-toast', () => ({
  toast: vi.fn(),
}))

import useSWR from 'swr'
import { FeedbackWidget } from '../FeedbackWidget'
import { cases as casesApi } from '@/lib/api'
import type { FeedbackRead } from '@/lib/types'

const mockUseSWR = useSWR as ReturnType<typeof vi.fn>
const mockSubmitFeedback = casesApi.submitFeedback as ReturnType<typeof vi.fn>

const CASE_ID = '00000000-0000-0000-0000-000000000001'

function makeFeedback(overrides: Partial<FeedbackRead> = {}): FeedbackRead {
  return {
    id: '00000000-0000-0000-0000-000000000099',
    case_id: CASE_ID,
    actor_user_id: '00000000-0000-0000-0000-000000000010',
    verdict: 'APPROVE',
    notes: 'Looks good',
    phase: 'phase1',
    created_at: '2026-01-01T10:00:00+00:00',
    ...overrides,
  }
}

describe('FeedbackWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseSWR.mockReturnValue({ data: [], isLoading: false, mutate: vi.fn() })
  })

  it('renders the section title', () => {
    render(<FeedbackWidget caseId={CASE_ID} />)
    expect(screen.getByText(/Your Feedback/i)).toBeInTheDocument()
    expect(screen.getByText(/AI Learning/i)).toBeInTheDocument()
  })

  it('renders all three verdict buttons', () => {
    render(<FeedbackWidget caseId={CASE_ID} />)
    expect(screen.getByRole('button', { name: /approve/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /needs revision/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reject/i })).toBeInTheDocument()
  })

  it('selecting a verdict marks it as pressed', async () => {
    const user = userEvent.setup()
    render(<FeedbackWidget caseId={CASE_ID} />)
    const approveBtn = screen.getByRole('button', { name: /approve/i })
    await user.click(approveBtn)
    expect(approveBtn).toHaveAttribute('aria-pressed', 'true')
  })

  it('deselects verdict on second click', async () => {
    const user = userEvent.setup()
    render(<FeedbackWidget caseId={CASE_ID} />)
    const approveBtn = screen.getByRole('button', { name: /approve/i })
    await user.click(approveBtn)
    await user.click(approveBtn)
    expect(approveBtn).toHaveAttribute('aria-pressed', 'false')
  })

  it('submit button is disabled when no verdict selected', () => {
    render(<FeedbackWidget caseId={CASE_ID} />)
    const submitBtn = screen.getByRole('button', { name: /submit feedback/i })
    expect(submitBtn).toBeDisabled()
  })

  it('submit button is enabled after selecting verdict', async () => {
    const user = userEvent.setup()
    render(<FeedbackWidget caseId={CASE_ID} />)
    await user.click(screen.getByRole('button', { name: /approve/i }))
    const submitBtn = screen.getByRole('button', { name: /submit feedback/i })
    expect(submitBtn).not.toBeDisabled()
  })

  it('calls submitFeedback with correct payload on submit', async () => {
    const mutate = vi.fn()
    mockUseSWR.mockReturnValue({ data: [], isLoading: false, mutate })
    mockSubmitFeedback.mockResolvedValue(makeFeedback())
    const user = userEvent.setup()
    render(<FeedbackWidget caseId={CASE_ID} />)

    await user.click(screen.getByRole('button', { name: /reject/i }))
    await user.type(screen.getByRole('textbox'), 'Risk too high')
    await user.click(screen.getByRole('button', { name: /submit feedback/i }))

    await waitFor(() => {
      expect(mockSubmitFeedback).toHaveBeenCalledWith(
        CASE_ID,
        expect.objectContaining({ verdict: 'REJECT', notes: 'Risk too high', phase: 'phase1' }),
      )
    })
  })

  it('shows existing feedbacks list when data present', () => {
    mockUseSWR.mockReturnValue({
      data: [
        makeFeedback({ verdict: 'APPROVE', notes: 'All good' }),
        makeFeedback({ id: 'id-2', verdict: 'REJECT', notes: 'Risky' }),
      ],
      isLoading: false,
      mutate: vi.fn(),
    })
    render(<FeedbackWidget caseId={CASE_ID} />)
    expect(screen.getByText(/APPROVE/)).toBeInTheDocument()
    expect(screen.getByText('All good')).toBeInTheDocument()
  })
})
