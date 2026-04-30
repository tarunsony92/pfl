/**
 * Tests for Topbar — user display and logout action.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'

// Mock next/navigation
const mockPush = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}))

// Mock useAuth
vi.mock('@/components/auth/useAuth', () => ({
  useAuth: vi.fn(),
}))

import { useAuth } from '@/components/auth/useAuth'
import { Topbar } from '../Topbar'

const mockUseAuth = vi.mocked(useAuth)

function makeAuth(overrides?: Partial<ReturnType<typeof mockUseAuth>>) {
  const logoutFn = vi.fn().mockResolvedValue(undefined)
  return {
    user: {
      id: '1',
      email: 'user@example.com',
      full_name: 'Test User',
      role: 'underwriter',
      mfa_enabled: false,
      is_active: true,
      last_login_at: null,
      created_at: '2024-01-01T00:00:00Z',
    },
    loading: false,
    login: vi.fn(),
    logout: logoutFn,
    refreshUser: vi.fn(),
    ...overrides,
  }
}

describe('Topbar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders user email in the trigger', () => {
    mockUseAuth.mockReturnValue(makeAuth())
    render(<Topbar />)
    expect(screen.getByText('user@example.com')).toBeInTheDocument()
  })

  it('renders the role badge', () => {
    mockUseAuth.mockReturnValue(makeAuth())
    render(<Topbar />)
    // RoleBadge renders "Underwriter" for role underwriter
    expect(screen.getByText('Underwriter')).toBeInTheDocument()
  })

  it('calls logout and redirects to /login on logout click', async () => {
    const logoutFn = vi.fn().mockResolvedValue(undefined)
    mockUseAuth.mockReturnValue(makeAuth({ logout: logoutFn }))
    const user = userEvent.setup()
    render(<Topbar />)

    // Open dropdown
    await user.click(screen.getByRole('button', { name: /user menu/i }))

    // Click logout
    await user.click(screen.getByText(/logout/i))

    await waitFor(() => {
      expect(logoutFn).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/login')
    })
  })

  it('renders nothing when user is null', () => {
    mockUseAuth.mockReturnValue(makeAuth({ user: null }))
    const { container } = render(<Topbar />)
    // The header should be empty (no dropdown trigger)
    expect(container.querySelector('button')).toBeNull()
  })
})
