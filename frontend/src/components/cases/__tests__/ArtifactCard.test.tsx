/**
 * Tests for ArtifactCard component.
 *
 * Verifies:
 * - Renders artifact label, filename, and download button
 * - Calls onDownload with correct artifact ID
 * - Handles unknown subtype gracefully
 * - Shows size when present
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import { ArtifactCard } from '../ArtifactCard'
import type { CaseArtifactRead } from '@/lib/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeArtifact(overrides: Partial<CaseArtifactRead> = {}): CaseArtifactRead {
  return {
    id: 'artifact-1',
    artifact_type: 'KYC_AADHAAR',
    filename: 'aadhaar.pdf',
    content_type: 'application/pdf',
    size_bytes: 102400,
    uploaded_at: '2026-01-01T10:00:00+00:00',
    download_url: null,
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ArtifactCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the friendly label for a known subtype', () => {
    render(<ArtifactCard artifact={makeArtifact({ artifact_type: 'KYC_AADHAAR' })} onDownload={vi.fn()} />)
    expect(screen.getByText('Aadhaar Card')).toBeInTheDocument()
  })

  it('renders PAN Card label for KYC_PAN', () => {
    render(<ArtifactCard artifact={makeArtifact({ artifact_type: 'KYC_PAN' })} onDownload={vi.fn()} />)
    expect(screen.getByText('PAN Card')).toBeInTheDocument()
  })

  it('renders the filename', () => {
    render(<ArtifactCard artifact={makeArtifact({ filename: 'document.pdf' })} onDownload={vi.fn()} />)
    expect(screen.getByText('document.pdf')).toBeInTheDocument()
  })

  it('renders file size when size_bytes is provided', () => {
    render(<ArtifactCard artifact={makeArtifact({ size_bytes: 102400 })} onDownload={vi.fn()} />)
    expect(screen.getByText('100.0 KB')).toBeInTheDocument()
  })

  it('does not render size when size_bytes is null', () => {
    render(<ArtifactCard artifact={makeArtifact({ size_bytes: null })} onDownload={vi.fn()} />)
    expect(screen.queryByText(/KB/i)).not.toBeInTheDocument()
  })

  it('calls onDownload with artifact id when Download button is clicked', async () => {
    const onDownload = vi.fn()
    const user = userEvent.setup()
    render(<ArtifactCard artifact={makeArtifact({ id: 'art-42' })} onDownload={onDownload} />)
    await user.click(screen.getByRole('button', { name: /download/i }))
    expect(onDownload).toHaveBeenCalledWith('art-42')
  })

  it('renders fallback type name for unknown subtype', () => {
    render(
      <ArtifactCard
        artifact={makeArtifact({ artifact_type: 'SOME_CUSTOM_TYPE' as never })}
        onDownload={vi.fn()}
      />,
    )
    expect(screen.getByText('SOME_CUSTOM_TYPE')).toBeInTheDocument()
  })

  it('renders Bank Statement label for BANK_STATEMENT', () => {
    render(<ArtifactCard artifact={makeArtifact({ artifact_type: 'BANK_STATEMENT' })} onDownload={vi.fn()} />)
    expect(screen.getByText('Bank Statement')).toBeInTheDocument()
  })
})
