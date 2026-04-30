/**
 * Tests for the toast + Toaster system.
 *
 * Verifies:
 * - toast() adds a toast that appears in the Toaster
 * - Destructive variant renders
 * - EmptyState renders with all props
 * - EmptyState renders without optional props
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import React from 'react'

// ---------------------------------------------------------------------------
// Mock Radix UI Toast (its portal/timer logic doesn't work in jsdom)
// ---------------------------------------------------------------------------

vi.mock('@radix-ui/react-toast', () => ({
  Provider: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Root: ({
    children,
    variant,
    ...rest
  }: React.HTMLAttributes<HTMLDivElement> & { variant?: string }) => (
    <div data-testid="toast-root" data-variant={variant ?? 'default'} {...rest}>
      {children}
    </div>
  ),
  Title: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="toast-title">{children}</div>
  ),
  Description: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="toast-description">{children}</div>
  ),
  Viewport: () => <div data-testid="toast-viewport" />,
}))

import { Toaster } from '../toaster'
import { toast } from '../use-toast'
import { EmptyState } from '../empty-state'

// ---------------------------------------------------------------------------
// Toast system tests
// ---------------------------------------------------------------------------

describe('toast system', () => {
  it('shows a default toast title after calling toast()', () => {
    render(<Toaster />)

    act(() => {
      toast({ title: 'Upload complete' })
    })

    expect(screen.getByTestId('toast-title')).toHaveTextContent('Upload complete')
  })

  it('shows toast description when provided', () => {
    render(<Toaster />)

    act(() => {
      toast({ title: 'Done', description: 'All 3 files processed.' })
    })

    expect(screen.getByTestId('toast-description')).toHaveTextContent('All 3 files processed.')
  })

  it('renders a destructive toast', () => {
    render(<Toaster />)

    act(() => {
      toast({ title: 'Upload failed', description: 'File too large.', variant: 'destructive' })
    })

    // Multiple toasts may be present from prior tests (module-level state); find ours by text
    const titles = screen.getAllByTestId('toast-title')
    const failedTitle = titles.find((el) => el.textContent === 'Upload failed')
    expect(failedTitle).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// EmptyState component tests
// ---------------------------------------------------------------------------

describe('EmptyState component', () => {
  it('renders heading and subtext', () => {
    render(
      <EmptyState
        heading="No cases found"
        subtext="Adjust your filters or create a new case."
      />,
    )
    expect(screen.getByText('No cases found')).toBeInTheDocument()
    expect(screen.getByText('Adjust your filters or create a new case.')).toBeInTheDocument()
  })

  it('renders optional CTA action', () => {
    const onClick = vi.fn()
    render(
      <EmptyState
        heading="No data"
        action={<button onClick={onClick}>Clear</button>}
      />,
    )
    expect(screen.getByRole('button', { name: 'Clear' })).toBeInTheDocument()
  })

  it('renders without icon or subtext (minimal props)', () => {
    render(<EmptyState heading="Nothing here" />)
    expect(screen.getByText('Nothing here')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('renders with icon node', () => {
    render(
      <EmptyState
        heading="Empty"
        icon={<svg data-testid="empty-icon" aria-hidden="true" />}
      />,
    )
    expect(screen.getByTestId('empty-icon')).toBeInTheDocument()
  })
})
