/**
 * Tests for useRequireAdmin hook.
 *
 * Verifies:
 * - Admin users get ready=true and no redirect
 * - Non-admin users get redirected to /cases
 * - Hook returns ready=false while loading
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import React from 'react'

// Mock next/navigation
const mockPush = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}))

// Mock useAuth — will be overridden per test
const mockUseAuth = vi.fn()
vi.mock('@/components/auth/useAuth', () => ({
  useAuth: () => mockUseAuth(),
}))

import { useRequireAdmin } from '../useRequireAdmin'

function TestComponent() {
  const { ready } = useRequireAdmin()
  return <div data-testid="ready">{ready ? 'ready' : 'not-ready'}</div>
}

describe('useRequireAdmin', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns ready=true for admin user', async () => {
    mockUseAuth.mockReturnValue({
      user: { id: '1', role: 'admin', email: 'admin@example.com' },
      loading: false,
    })

    render(<TestComponent />)

    await waitFor(() => {
      expect(screen.getByTestId('ready').textContent).toBe('ready')
    })
    expect(mockPush).not.toHaveBeenCalled()
  })

  it('redirects non-admin to /cases', async () => {
    mockUseAuth.mockReturnValue({
      user: { id: '2', role: 'underwriter', email: 'uw@example.com' },
      loading: false,
    })

    render(<TestComponent />)

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/cases')
    })
    expect(screen.getByTestId('ready').textContent).toBe('not-ready')
  })

  it('redirects CEO to /cases (not admin)', async () => {
    mockUseAuth.mockReturnValue({
      user: { id: '3', role: 'ceo', email: 'ceo@example.com' },
      loading: false,
    })

    render(<TestComponent />)

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/cases')
    })
  })

  it('returns ready=false while loading', () => {
    mockUseAuth.mockReturnValue({
      user: null,
      loading: true,
    })

    render(<TestComponent />)

    expect(screen.getByTestId('ready').textContent).toBe('not-ready')
    expect(mockPush).not.toHaveBeenCalled()
  })

  it('does not redirect while still loading', async () => {
    mockUseAuth.mockReturnValue({
      user: null,
      loading: true,
    })

    render(<TestComponent />)

    // Wait a tick to ensure no async redirect happened
    await new Promise((r) => setTimeout(r, 50))
    expect(mockPush).not.toHaveBeenCalled()
  })
})
