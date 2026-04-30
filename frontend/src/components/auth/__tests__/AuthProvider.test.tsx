/**
 * Tests for AuthProvider + useAuth hook.
 *
 * Uses Vitest + @testing-library/react.
 * Mocks @/lib/api so no real fetch calls are made.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'

// Mock the api module BEFORE importing AuthProvider so the module cache
// sees our mock.
vi.mock('@/lib/api', () => {
  return {
    default: {
      users: {
        me: vi.fn(),
      },
      auth: {
        login: vi.fn(),
        logout: vi.fn(),
      },
    },
    api: {
      users: {
        me: vi.fn(),
      },
      auth: {
        login: vi.fn(),
        logout: vi.fn(),
      },
    },
  }
})

import { AuthProvider } from '../AuthProvider'
import { useAuth } from '../useAuth'
import api from '@/lib/api'

// Helper to render a component that consumes useAuth.
function TestConsumer() {
  const { user, loading, login, logout, refreshUser } = useAuth()

  return (
    <div>
      <div data-testid="loading">{loading ? 'loading' : 'ready'}</div>
      <div data-testid="user">{user ? user.email : 'null'}</div>
      <button onClick={() => login('test@example.com', 'password')}>Login</button>
      <button onClick={() => login('test@example.com', 'password', '123456')}>Login MFA</button>
      <button onClick={logout}>Logout</button>
      <button onClick={refreshUser}>Refresh</button>
    </div>
  )
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>
}

const mockUser = {
  id: '00000000-0000-0000-0000-000000000001',
  email: 'test@example.com',
  full_name: 'Test User',
  role: 'analyst',
  mfa_enabled: false,
  is_active: true,
  last_login_at: null,
  created_at: '2024-01-01T00:00:00+00:00',
}

describe('AuthProvider', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('starts in loading state and resolves user on mount', async () => {
    vi.mocked(api.users.me).mockResolvedValue(mockUser)

    render(<TestConsumer />, { wrapper: Wrapper })

    // Initially loading
    expect(screen.getByTestId('loading').textContent).toBe('loading')

    await waitFor(() => {
      expect(screen.getByTestId('loading').textContent).toBe('ready')
    })

    expect(screen.getByTestId('user').textContent).toBe('test@example.com')
  })

  it('sets user to null when /users/me fails', async () => {
    vi.mocked(api.users.me).mockRejectedValue(new Error('Unauthorized'))

    render(<TestConsumer />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(screen.getByTestId('loading').textContent).toBe('ready')
    })

    expect(screen.getByTestId('user').textContent).toBe('null')
  })

  it('login calls api.auth.login and refreshes user on success', async () => {
    vi.mocked(api.auth.login).mockResolvedValue({
      access_token: 'tok',
      refresh_token: 'ref',
      token_type: 'bearer',
      mfa_required: false,
      mfa_enrollment_required: false,
    })
    vi.mocked(api.users.me).mockResolvedValue(mockUser)

    const user = userEvent.setup()
    render(<TestConsumer />, { wrapper: Wrapper })

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('ready'))

    await user.click(screen.getByText('Login'))

    await waitFor(() => {
      expect(api.auth.login).toHaveBeenCalledWith('test@example.com', 'password', undefined)
    })
    expect(screen.getByTestId('user').textContent).toBe('test@example.com')
  })

  it('login returns mfaRequired flag when backend says so', async () => {
    vi.mocked(api.auth.login).mockResolvedValue({
      access_token: '',
      refresh_token: '',
      token_type: 'bearer',
      mfa_required: true,
      mfa_enrollment_required: false,
    })
    vi.mocked(api.users.me).mockRejectedValue(new Error('not authed'))

    const user = userEvent.setup()

    let loginResult: Record<string, unknown> = {}
    function CapturingConsumer() {
      const { login } = useAuth()
      return (
        <button
          onClick={async () => {
            loginResult = await login('test@example.com', 'password')
          }}
        >
          Login
        </button>
      )
    }

    render(<CapturingConsumer />, { wrapper: Wrapper })
    await user.click(screen.getByText('Login'))

    await waitFor(() => {
      expect(loginResult.mfaRequired).toBe(true)
    })
    // refreshUser should NOT have been called
    expect(api.users.me).toHaveBeenCalledTimes(1) // only the initial mount call
  })

  it('logout calls api.auth.logout and clears user', async () => {
    vi.mocked(api.users.me).mockResolvedValue(mockUser)
    vi.mocked(api.auth.logout).mockResolvedValue(undefined)

    const user = userEvent.setup()
    render(<TestConsumer />, { wrapper: Wrapper })

    await waitFor(() => expect(screen.getByTestId('user').textContent).toBe('test@example.com'))

    await user.click(screen.getByText('Logout'))

    await waitFor(() => {
      expect(screen.getByTestId('user').textContent).toBe('null')
    })
    expect(api.auth.logout).toHaveBeenCalledOnce()
  })

  it('logout clears user even if api call fails', async () => {
    vi.mocked(api.users.me).mockResolvedValue(mockUser)
    vi.mocked(api.auth.logout).mockRejectedValue(new Error('Network error'))

    const user = userEvent.setup()
    render(<TestConsumer />, { wrapper: Wrapper })

    await waitFor(() => expect(screen.getByTestId('user').textContent).toBe('test@example.com'))

    await user.click(screen.getByText('Logout'))

    await waitFor(() => {
      expect(screen.getByTestId('user').textContent).toBe('null')
    })
  })

  it('useAuth throws when used outside AuthProvider', () => {
    // Suppress React error boundary noise.
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    function Bare() {
      useAuth()
      return null
    }

    expect(() => render(<Bare />)).toThrow('useAuth must be used inside <AuthProvider>')

    consoleSpy.mockRestore()
  })
})
