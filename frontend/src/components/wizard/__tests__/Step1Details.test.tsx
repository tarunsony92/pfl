/**
 * Tests for Step1Details (wizard step 1) component.
 *
 * Covers:
 * - Renders all required fields
 * - Validation errors for invalid loan_id, out-of-range loan_amount and tenure
 * - Calls api.cases.initiate + onNext on valid submit
 * - Shows error toast on API failure
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'

// Mock api
vi.mock('@/lib/api', () => ({
  api: {
    cases: {
      initiate: vi.fn(),
    },
  },
}))

// Mock toast
const mockToast = vi.fn()
vi.mock('@/components/ui/use-toast', () => ({
  toast: (...args: unknown[]) => mockToast(...args),
}))

import { Step1Details } from '../Step1Details'
import { api } from '@/lib/api'

const validPresigned = {
  case_id: '00000000-0000-0000-0000-000000000001',
  upload_url: 'https://s3.example.com/upload',
  upload_fields: { key: 'test-key' },
  upload_key: 'test-key',
  expires_at: '2026-01-02T00:00:00+00:00',
  reupload: false,
}

describe('Step1Details', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders all form fields', () => {
    render(<Step1Details onNext={vi.fn()} />)
    expect(screen.getByLabelText(/loan id/i)).toBeInTheDocument()
    // Use the specific label text to avoid matching co-applicant label as well
    expect(screen.getByLabelText(/^applicant name/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/loan amount/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/loan tenure/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/co-applicant/i)).toBeInTheDocument()
  })

  it('renders Next button', () => {
    render(<Step1Details onNext={vi.fn()} />)
    expect(screen.getByRole('button', { name: /next/i })).toBeInTheDocument()
  })

  it('shows validation error for empty loan_id', async () => {
    const user = userEvent.setup()
    render(<Step1Details onNext={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: /next/i }))
    await waitFor(() => {
      expect(screen.getByText(/at least 3 characters/i)).toBeInTheDocument()
    })
  })

  it('shows validation error for loan_amount below 50000', async () => {
    const user = userEvent.setup()
    render(<Step1Details onNext={vi.fn()} />)
    await user.type(screen.getByLabelText(/loan id/i), 'PFL-001')
    await user.type(screen.getByLabelText(/^applicant name/i), 'Alice Smith')
    await user.type(screen.getByLabelText(/loan amount/i), '1000')
    await user.type(screen.getByLabelText(/loan tenure/i), '12')
    await user.click(screen.getByRole('button', { name: /next/i }))
    await waitFor(() => {
      expect(screen.getByText(/minimum loan amount/i)).toBeInTheDocument()
    })
  })

  it('shows validation error for tenure above 36', async () => {
    const user = userEvent.setup()
    render(<Step1Details onNext={vi.fn()} />)
    await user.type(screen.getByLabelText(/loan id/i), 'PFL-001')
    await user.type(screen.getByLabelText(/^applicant name/i), 'Alice Smith')
    await user.type(screen.getByLabelText(/loan amount/i), '100000')
    await user.type(screen.getByLabelText(/loan tenure/i), '48')
    await user.click(screen.getByRole('button', { name: /next/i }))
    await waitFor(() => {
      expect(screen.getByText(/maximum tenure/i)).toBeInTheDocument()
    })
  })

  it('calls api.cases.initiate and onNext on valid submit', async () => {
    vi.mocked(api.cases.initiate).mockResolvedValue(validPresigned)
    const onNext = vi.fn()
    const user = userEvent.setup()

    render(<Step1Details onNext={onNext} />)

    await user.type(screen.getByLabelText(/loan id/i), 'PFL-2026-001')
    await user.type(screen.getByLabelText(/^applicant name/i), 'Alice Smith')
    await user.type(screen.getByLabelText(/loan amount/i), '100000')
    await user.type(screen.getByLabelText(/loan tenure/i), '24')
    await user.click(screen.getByRole('button', { name: /next/i }))

    await waitFor(() => {
      expect(api.cases.initiate).toHaveBeenCalledWith(
        expect.objectContaining({
          loan_id: 'PFL-2026-001',
          applicant_name: 'Alice Smith',
          loan_amount: 100000,
          loan_tenure_months: 24,
        }),
      )
      expect(onNext).toHaveBeenCalledWith({
        presigned: validPresigned,
        caseId: validPresigned.case_id,
        formValues: expect.objectContaining({
          loan_id: 'PFL-2026-001',
          applicant_name: 'Alice Smith',
          loan_amount: 100000,
          loan_tenure_months: 24,
        }),
      })
    })
  })

  it('shows error toast on API failure', async () => {
    vi.mocked(api.cases.initiate).mockRejectedValue(new Error('Server error'))
    const user = userEvent.setup()

    render(<Step1Details onNext={vi.fn()} />)

    await user.type(screen.getByLabelText(/loan id/i), 'PFL-2026-001')
    await user.type(screen.getByLabelText(/^applicant name/i), 'Alice Smith')
    await user.type(screen.getByLabelText(/loan amount/i), '100000')
    await user.type(screen.getByLabelText(/loan tenure/i), '24')
    await user.click(screen.getByRole('button', { name: /next/i }))

    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({ variant: 'destructive' }),
      )
    })
  })
})
