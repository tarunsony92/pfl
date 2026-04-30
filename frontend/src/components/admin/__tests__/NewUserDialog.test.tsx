/**
 * Tests for NewUserDialog component.
 *
 * Covers:
 * - Dialog opens on button click
 * - Validation errors for empty fields + short password
 * - Successful create calls api.users.create + onCreated
 * - API error shows error toast
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'

// Mock api
vi.mock('@/lib/api', () => ({
  api: {
    users: {
      create: vi.fn(),
    },
  },
}))

// Mock toast
const mockToast = vi.fn()
vi.mock('@/components/ui/use-toast', () => ({
  toast: (...args: unknown[]) => mockToast(...args),
}))

import { NewUserDialog } from '../NewUserDialog'
import { api } from '@/lib/api'
import type { UserRead } from '@/lib/types'

function makeUser(overrides: Partial<UserRead> = {}): UserRead {
  return {
    id: '00000000-0000-0000-0000-000000000001',
    email: 'new@example.com',
    full_name: 'New User',
    role: 'underwriter',
    mfa_enabled: false,
    is_active: true,
    last_login_at: null,
    created_at: '2026-01-01T10:00:00+00:00',
    ...overrides,
  }
}

describe('NewUserDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders trigger button', () => {
    render(<NewUserDialog onCreated={vi.fn()} />)
    expect(screen.getByRole('button', { name: /new user/i })).toBeInTheDocument()
  })

  it('opens dialog on button click', async () => {
    const user = userEvent.setup()
    render(<NewUserDialog onCreated={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: /new user/i }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    // Dialog title "New User" will appear alongside the button text — use heading
    expect(screen.getByRole('heading', { name: /new user/i })).toBeInTheDocument()
  })

  it('shows validation errors for empty form submission', async () => {
    const user = userEvent.setup()
    render(<NewUserDialog onCreated={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: /new user/i }))
    await user.click(screen.getByRole('button', { name: /create user/i }))
    await waitFor(() => {
      expect(screen.getByText(/invalid email/i)).toBeInTheDocument()
    })
  })

  it('shows error for short password', async () => {
    const user = userEvent.setup()
    render(<NewUserDialog onCreated={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: /new user/i }))
    await user.type(screen.getByLabelText(/email/i), 'test@example.com')
    await user.type(screen.getByLabelText(/full name/i), 'Test User')
    await user.type(screen.getByLabelText(/password/i), 'short')
    await user.click(screen.getByRole('button', { name: /create user/i }))
    await waitFor(() => {
      expect(screen.getByText(/at least 8 characters/i)).toBeInTheDocument()
    })
  })

  it('calls api.users.create and onCreated on valid submit', async () => {
    vi.mocked(api.users.create).mockResolvedValue(makeUser())
    const onCreated = vi.fn()
    const user = userEvent.setup()

    render(<NewUserDialog onCreated={onCreated} />)
    await user.click(screen.getByRole('button', { name: /new user/i }))

    await user.type(screen.getByLabelText(/email/i), 'alice@example.com')
    await user.type(screen.getByLabelText(/full name/i), 'Alice Smith')
    await user.type(screen.getByLabelText(/password/i), 'securepass123')
    await user.click(screen.getByRole('button', { name: /create user/i }))

    await waitFor(() => {
      expect(api.users.create).toHaveBeenCalledWith({
        email: 'alice@example.com',
        full_name: 'Alice Smith',
        role: 'underwriter',
        password: 'securepass123',
      })
      expect(onCreated).toHaveBeenCalledOnce()
    })
  })

  it('shows error toast on API failure', async () => {
    vi.mocked(api.users.create).mockRejectedValue(new Error('Conflict: user exists'))
    const user = userEvent.setup()

    render(<NewUserDialog onCreated={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: /new user/i }))

    await user.type(screen.getByLabelText(/email/i), 'alice@example.com')
    await user.type(screen.getByLabelText(/full name/i), 'Alice Smith')
    await user.type(screen.getByLabelText(/password/i), 'securepass123')
    await user.click(screen.getByRole('button', { name: /create user/i }))

    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({ variant: 'destructive' }),
      )
    })
  })
})
