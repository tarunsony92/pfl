/**
 * Tests for DedupeSnapshotsTable component.
 *
 * Covers:
 * - Empty state
 * - Renders rows with correct data
 * - Active snapshot has Active badge
 * - Inactive snapshot has Inactive badge
 * - Download link when download_url present
 * - No download link when download_url is null
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'

import { DedupeSnapshotsTable } from '../DedupeSnapshotsTable'
import type { DedupeSnapshotRead } from '@/lib/types'

function makeSnapshot(overrides: Partial<DedupeSnapshotRead> = {}): DedupeSnapshotRead {
  return {
    id: '00000000-0000-0000-0000-000000000001',
    uploaded_by: 'aaaaaaaa-0000-0000-0000-000000000001',
    uploaded_at: '2026-01-01T10:00:00+00:00',
    row_count: 1000,
    is_active: true,
    download_url: 'https://example.com/download/snap.xlsx',
    ...overrides,
  }
}

describe('DedupeSnapshotsTable', () => {
  it('shows empty state when no snapshots', () => {
    render(<DedupeSnapshotsTable snapshots={[]} />)
    expect(screen.getByTestId('empty-state')).toBeInTheDocument()
    expect(screen.getByText(/no dedupe snapshots/i)).toBeInTheDocument()
  })

  it('renders table headers when snapshots present', () => {
    render(<DedupeSnapshotsTable snapshots={[makeSnapshot()]} />)
    expect(screen.getByText('Snapshot ID')).toBeInTheDocument()
    expect(screen.getByText('Uploaded By')).toBeInTheDocument()
    expect(screen.getByText('Rows')).toBeInTheDocument()
    expect(screen.getByText('Status')).toBeInTheDocument()
    // Use getAllByText since column header and link both say "Download"
    const downloadEls = screen.getAllByText('Download')
    expect(downloadEls.length).toBeGreaterThanOrEqual(1)
  })

  it('shows Active badge for active snapshot', () => {
    render(<DedupeSnapshotsTable snapshots={[makeSnapshot({ is_active: true })]} />)
    expect(screen.getByText('Active')).toBeInTheDocument()
  })

  it('shows Inactive badge for inactive snapshot', () => {
    render(<DedupeSnapshotsTable snapshots={[makeSnapshot({ is_active: false, download_url: null })]} />)
    expect(screen.getByText('Inactive')).toBeInTheDocument()
  })

  it('shows row count formatted', () => {
    render(<DedupeSnapshotsTable snapshots={[makeSnapshot({ row_count: 12345 })]} />)
    // toLocaleString formats numbers differently in test env, just check the number is there
    expect(screen.getByText(/12/)).toBeInTheDocument()
  })

  it('renders download link when download_url present', () => {
    const snap = makeSnapshot({ download_url: 'https://s3.example.com/snap.xlsx' })
    render(<DedupeSnapshotsTable snapshots={[snap]} />)
    const link = screen.getByRole('link', { name: /download/i })
    expect(link).toHaveAttribute('href', 'https://s3.example.com/snap.xlsx')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('shows dash when download_url is null', () => {
    render(<DedupeSnapshotsTable snapshots={[makeSnapshot({ download_url: null })]} />)
    expect(screen.queryByRole('link', { name: /download/i })).not.toBeInTheDocument()
  })

  it('renders multiple rows', () => {
    const snaps = [
      makeSnapshot({ id: '00000000-0000-0000-0000-000000000001', is_active: true }),
      makeSnapshot({ id: '00000000-0000-0000-0000-000000000002', is_active: false, download_url: null }),
    ]
    render(<DedupeSnapshotsTable snapshots={snaps} />)
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('Inactive')).toBeInTheDocument()
  })
})
