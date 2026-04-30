/**
 * Tests for UsersTable component.
 *
 * Covers:
 * - Renders user rows
 * - Self row shows "(you)" and has disabled role select + disabled active toggle
 * - Role change calls api.users.updateRole + onMutate
 * - Active toggle calls api.users.updateActive + onMutate
 * - Cannot toggle self
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'

// Mock api
vi.mock('@/lib/api', () => ({
  api: {
    users: {
      updateRole: vi.fn(),
      updateActive: vi.fn(),
    },
  },
}))

// Mock toast
vi.mock('@/components/ui/use-toast', () => ({
  toast: vi.fn(),
}))

import { UsersTable } from '../UsersTable'
import { api } from '@/lib/api'
import type { UserRead } from '@/lib/types'

function makeUser(overrides: Partial<UserRead> = {}): UserRead {
  return {
    id: '00000000-0000-0000-0000-000000000001',
    email: 'user@example.com',
    full_name: 'Test User',
    role: 'underwriter',
    mfa_enabled: false,
    is_active: true,
    last_login_at: null,
    created_at: '2026-01-01T10:00:00+00:00',
    ...overrides,
  }
}

const SELF_ID = 'self-uuid-001'
const OTHER_ID = 'other-uuid-002'

describe('UsersTable', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders column headers', () => {
    render(<UsersTable users={[]} currentUserId={SELF_ID} onMutate={vi.fn()} />)
    // Empty state shown, but on non-empty:
    expect(screen.getByText('No users found.')).toBeInTheDocument()
  })

  it('renders table headers when users are present', () => {
    const users = [makeUser({ id: OTHER_ID })]
    render(<UsersTable users={users} currentUserId={SELF_ID} onMutate={vi.fn()} />)
    expect(screen.getByText('Email')).toBeInTheDocument()
    expect(screen.getByText('Role')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
  })

  it('shows (you) label for current user', () => {
    const users = [makeUser({ id: SELF_ID, email: 'me@example.com' })]
    render(<UsersTable users={users} currentUserId={SELF_ID} onMutate={vi.fn()} />)
    expect(screen.getByText('(you)')).toBeInTheDocument()
  })

  it('renders RoleBadge (not select) for self', () => {
    const users = [makeUser({ id: SELF_ID, role: 'admin' })]
    render(<UsersTable users={users} currentUserId={SELF_ID} onMutate={vi.fn()} />)
    // Should not have a role select for self
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    // Should have the text "Admin" from RoleBadge
    expect(screen.getByText('Admin')).toBeInTheDocument()
  })

  it('renders role select for non-self user', () => {
    const users = [makeUser({ id: OTHER_ID, role: 'underwriter' })]
    render(<UsersTable users={users} currentUserId={SELF_ID} onMutate={vi.fn()} />)
    const select = screen.getByRole('combobox', { name: /change role/i })
    expect(select).toBeInTheDocument()
    expect(select).not.toBeDisabled()
  })

  it('calls updateRole + onMutate on role change', async () => {
    vi.mocked(api.users.updateRole).mockResolvedValue(
      makeUser({ id: OTHER_ID, role: 'admin' }),
    )
    const onMutate = vi.fn()
    const user = userEvent.setup()

    const users = [makeUser({ id: OTHER_ID, role: 'underwriter' })]
    render(<UsersTable users={users} currentUserId={SELF_ID} onMutate={onMutate} />)

    const select = screen.getByRole('combobox', { name: /change role/i })
    await user.selectOptions(select, 'admin')

    await waitFor(() => {
      expect(api.users.updateRole).toHaveBeenCalledWith(OTHER_ID, 'admin')
      expect(onMutate).toHaveBeenCalledOnce()
    })
  })

  it('active toggle is disabled for self', () => {
    const users = [makeUser({ id: SELF_ID, is_active: true })]
    render(<UsersTable users={users} currentUserId={SELF_ID} onMutate={vi.fn()} />)
    const toggle = screen.getByRole('switch')
    expect(toggle).toBeDisabled()
  })

  it('calls updateActive + onMutate on toggle', async () => {
    vi.mocked(api.users.updateActive).mockResolvedValue(
      makeUser({ id: OTHER_ID, is_active: false }),
    )
    const onMutate = vi.fn()
    const user = userEvent.setup()

    const users = [makeUser({ id: OTHER_ID, is_active: true })]
    render(<UsersTable users={users} currentUserId={SELF_ID} onMutate={onMutate} />)

    const toggle = screen.getByRole('switch')
    await user.click(toggle)

    await waitFor(() => {
      expect(api.users.updateActive).toHaveBeenCalledWith(OTHER_ID, false)
      expect(onMutate).toHaveBeenCalledOnce()
    })
  })

  it('shows MFA enabled badge', () => {
    const users = [makeUser({ id: OTHER_ID, mfa_enabled: true })]
    render(<UsersTable users={users} currentUserId={SELF_ID} onMutate={vi.fn()} />)
    expect(screen.getByText('Enabled')).toBeInTheDocument()
  })

  it('shows MFA disabled badge', () => {
    const users = [makeUser({ id: OTHER_ID, mfa_enabled: false })]
    render(<UsersTable users={users} currentUserId={SELF_ID} onMutate={vi.fn()} />)
    expect(screen.getByText('Disabled')).toBeInTheDocument()
  })
})
