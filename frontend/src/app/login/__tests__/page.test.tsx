/**
 * Tests for the /login page component.
 *
 * Uses Vitest + @testing-library/react.
 * Mocks:
 *   - @/lib/api  (no real fetches)
 *   - next/navigation (useRouter + useSearchParams)
 *   - @/components/auth/useAuth (supplies a test auth context)
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockPush = vi.fn()
const mockGet = vi.fn().mockReturnValue(null) // searchParams.get()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => ({ get: mockGet }),
}))

const mockLogin = vi.fn()

vi.mock('@/components/auth/useAuth', () => ({
  useAuth: () => ({
    user: null,
    loading: false,
    login: mockLogin,
    logout: vi.fn(),
    refreshUser: vi.fn(),
  }),
}))

// ---------------------------------------------------------------------------
// Subject
// ---------------------------------------------------------------------------

// Import AFTER mocks are registered.
import LoginPage from '../page'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderPage() {
  return render(<LoginPage />)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockReturnValue(null)
  })

  it('renders email and password fields', () => {
    renderPage()
    expect(screen.getByLabelText(/email address/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('shows validation errors when submitted empty', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByText(/valid email/i)).toBeInTheDocument()
      expect(screen.getByText(/password is required/i)).toBeInTheDocument()
    })

    expect(mockLogin).not.toHaveBeenCalled()
  })

  it('calls login with email and password on valid submit', async () => {
    mockLogin.mockResolvedValue({})
    const user = userEvent.setup()
    renderPage()

    await user.type(screen.getByLabelText(/email address/i), 'admin@pfl.com')
    await user.type(screen.getByLabelText(/password/i), 'secret123')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalled()
    })
    const callArgs = mockLogin.mock.calls[0]
    expect(callArgs[0]).toBe('admin@pfl.com')
    expect(callArgs[1]).toBe('secret123')
  })

  it('redirects to /cases on successful login', async () => {
    mockLogin.mockResolvedValue({})
    const user = userEvent.setup()
    renderPage()

    await user.type(screen.getByLabelText(/email address/i), 'admin@pfl.com')
    await user.type(screen.getByLabelText(/password/i), 'secret123')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/cases')
    })
  })

  it('redirects to ?from param on successful login', async () => {
    mockLogin.mockResolvedValue({})
    mockGet.mockReturnValue('/cases/123')
    const user = userEvent.setup()
    renderPage()

    await user.type(screen.getByLabelText(/email address/i), 'admin@pfl.com')
    await user.type(screen.getByLabelText(/password/i), 'pass')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/cases/123')
    })
  })

  it('shows MFA code step when login returns mfaRequired', async () => {
    mockLogin.mockResolvedValue({ mfaRequired: true })
    const user = userEvent.setup()
    renderPage()

    await user.type(screen.getByLabelText(/email address/i), 'admin@pfl.com')
    await user.type(screen.getByLabelText(/password/i), 'pass')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByLabelText(/authenticator code/i)).toBeInTheDocument()
    })
    expect(mockPush).not.toHaveBeenCalled()
  })

  it('submits MFA code and redirects on success', async () => {
    // First call triggers MFA step; second call succeeds.
    mockLogin
      .mockResolvedValueOnce({ mfaRequired: true })
      .mockResolvedValueOnce({})

    const user = userEvent.setup()
    renderPage()

    // Credentials step
    await user.type(screen.getByLabelText(/email address/i), 'admin@pfl.com')
    await user.type(screen.getByLabelText(/password/i), 'pass')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    // MFA step
    await waitFor(() => {
      expect(screen.getByLabelText(/authenticator code/i)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText(/authenticator code/i), '123456')
    await user.click(screen.getByRole('button', { name: /verify code/i }))

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('admin@pfl.com', 'pass', '123456')
      expect(mockPush).toHaveBeenCalledWith('/cases')
    })
  })

  it('shows server error on login failure', async () => {
    mockLogin.mockRejectedValue(new Error('Invalid credentials'))
    const user = userEvent.setup()
    renderPage()

    await user.type(screen.getByLabelText(/email address/i), 'bad@pfl.com')
    await user.type(screen.getByLabelText(/password/i), 'wrong')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Invalid credentials')
    })
    expect(mockPush).not.toHaveBeenCalled()
  })

  it('back button returns to credentials step', async () => {
    mockLogin.mockResolvedValue({ mfaRequired: true })
    const user = userEvent.setup()
    renderPage()

    await user.type(screen.getByLabelText(/email address/i), 'admin@pfl.com')
    await user.type(screen.getByLabelText(/password/i), 'pass')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByLabelText(/authenticator code/i)).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /back to sign in/i }))

    await waitFor(() => {
      expect(screen.getByLabelText(/email address/i)).toBeInTheDocument()
    })
  })

  it('disables submit button while submitting', async () => {
    // Never resolves during the test so we can inspect the loading state.
    let resolveLogin!: (v: Record<string, unknown>) => void
    mockLogin.mockReturnValue(new Promise((res) => { resolveLogin = res }))

    const user = userEvent.setup()
    renderPage()

    await user.type(screen.getByLabelText(/email address/i), 'admin@pfl.com')
    await user.type(screen.getByLabelText(/password/i), 'pass')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /signing in/i })).toBeDisabled()
    })

    // Cleanup
    resolveLogin({})
  })
})
