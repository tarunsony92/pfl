/**
 * Tests for AuditLogTimeline component.
 *
 * Verifies:
 * - Loading skeleton state
 * - Empty state message
 * - Renders audit entries most-recent first
 * - Diff toggle shows/hides before/after JSON
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import { AuditLogTimeline } from '../AuditLogTimeline'
import type { AuditLogRead } from '@/lib/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeEntry(overrides: Partial<AuditLogRead> = {}): AuditLogRead {
  return {
    id: 'log-1',
    actor_user_id: 'user-abc12345',
    action: 'STAGE_TRANSITION',
    entity_type: 'case',
    entity_id: 'case-1',
    before_json: null,
    after_json: null,
    ip_address: null,
    user_agent: null,
    created_at: '2026-01-01T10:00:00+00:00',
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AuditLogTimeline', () => {
  it('renders loading skeletons when isLoading=true', () => {
    render(<AuditLogTimeline entries={[]} isLoading={true} />)
    expect(screen.getByTestId('audit-skeleton')).toBeInTheDocument()
    // Should not show empty state
    expect(screen.queryByText(/No audit log entries/i)).not.toBeInTheDocument()
  })

  it('renders empty state when entries is empty', () => {
    render(<AuditLogTimeline entries={[]} />)
    expect(screen.getByText(/No audit log entries found/i)).toBeInTheDocument()
  })

  it('renders entry actions in friendly format', () => {
    render(
      <AuditLogTimeline
        entries={[makeEntry({ action: 'STAGE_TRANSITION' })]}
      />,
    )
    expect(screen.getByText('Stage Transition')).toBeInTheDocument()
  })

  it('renders multiple entries sorted most-recent first', () => {
    const entries = [
      makeEntry({ id: 'old', action: 'FIRST_ACTION', created_at: '2026-01-01T08:00:00+00:00' }),
      makeEntry({ id: 'new', action: 'SECOND_ACTION', created_at: '2026-01-01T12:00:00+00:00' }),
    ]

    render(<AuditLogTimeline entries={entries} />)

    const items = screen.getAllByRole('listitem')
    // Most recent first: SECOND_ACTION should appear before FIRST_ACTION
    expect(items[0]).toHaveTextContent('Second Action')
    expect(items[1]).toHaveTextContent('First Action')
  })

  it('shows actor ID truncated', () => {
    render(
      <AuditLogTimeline
        entries={[makeEntry({ actor_user_id: 'user-abc12345-longid' })]}
      />,
    )
    expect(screen.getByText(/user-abc…/)).toBeInTheDocument()
  })

  it('shows "system" as actor when actor_user_id is null', () => {
    render(
      <AuditLogTimeline
        entries={[makeEntry({ actor_user_id: null })]}
      />,
    )
    expect(screen.getByText(/system/i)).toBeInTheDocument()
  })

  it('does not show Diff button when no before/after JSON', () => {
    render(
      <AuditLogTimeline
        entries={[makeEntry({ before_json: null, after_json: null })]}
      />,
    )
    expect(screen.queryByText(/Diff/i)).not.toBeInTheDocument()
  })

  it('shows Diff toggle and expands/collapses when clicked', async () => {
    const user = userEvent.setup()
    const before = { stage: 'UPLOADED' }
    const after = { stage: 'CHECKLIST_VALIDATION' }

    render(
      <AuditLogTimeline
        entries={[makeEntry({ before_json: before, after_json: after })]}
      />,
    )

    const diffButton = screen.getByRole('button', { name: /show diff details/i })
    expect(diffButton).toBeInTheDocument()

    // Initially collapsed — no Before/After labels
    expect(screen.queryByText('Before')).not.toBeInTheDocument()

    // Expand
    await user.click(diffButton)
    expect(screen.getByText('Before')).toBeInTheDocument()
    expect(screen.getByText('After')).toBeInTheDocument()

    // Collapse again
    await user.click(screen.getByRole('button', { name: /hide diff details/i }))
    expect(screen.queryByText('Before')).not.toBeInTheDocument()
  })
})
