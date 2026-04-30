/**
 * Tests for Sidebar — role-based link visibility.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'

// Mock next/navigation
vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => '/cases'),
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...props
  }: { href: string; children: React.ReactNode } & Record<string, unknown>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

// Mock useAuth
vi.mock('@/components/auth/useAuth', () => ({
  useAuth: vi.fn(),
}))

import { useAuth } from '@/components/auth/useAuth'
import { Sidebar } from '../Sidebar'

const mockUseAuth = vi.mocked(useAuth)

function adminUser() {
  return {
    user: {
      id: '1',
      email: 'admin@example.com',
      full_name: 'Admin User',
      role: 'admin',
      mfa_enabled: false,
      is_active: true,
      last_login_at: null,
      created_at: '2024-01-01T00:00:00Z',
    },
    loading: false,
    login: vi.fn(),
    logout: vi.fn(),
    refreshUser: vi.fn(),
  }
}

function regularUser(role = 'underwriter') {
  return {
    ...adminUser(),
    user: { ...adminUser().user, role, email: `${role}@example.com` },
  }
}

describe('Sidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders Cases and Settings links for all users', () => {
    mockUseAuth.mockReturnValue(regularUser())
    render(<Sidebar />)
    expect(screen.getByRole('link', { name: /cases/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /settings/i })).toBeInTheDocument()
  })

  it('does NOT show admin-only links for non-admin users', () => {
    mockUseAuth.mockReturnValue(regularUser('underwriter'))
    render(<Sidebar />)
    expect(screen.queryByRole('link', { name: /users/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /dedupe snapshots/i })).not.toBeInTheDocument()
  })

  it('shows Users and Dedupe Snapshots links for admin', () => {
    mockUseAuth.mockReturnValue(adminUser())
    render(<Sidebar />)
    expect(screen.getByRole('link', { name: /users/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /dedupe snapshots/i })).toBeInTheDocument()
  })

  it('marks the active link with aria-current="page"', () => {
    mockUseAuth.mockReturnValue(regularUser())
    render(<Sidebar />)
    const casesLink = screen.getByRole('link', { name: /cases/i })
    expect(casesLink).toHaveAttribute('aria-current', 'page')
  })

  it('navigation has accessible aria-label', () => {
    mockUseAuth.mockReturnValue(regularUser())
    render(<Sidebar />)
    expect(screen.getByRole('navigation', { name: /primary/i })).toBeInTheDocument()
  })
})
