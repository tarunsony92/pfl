/**
 * Tests for StageBadge component.
 *
 * Verifies correct label and color class for a representative sample
 * of CaseStage values.
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'
import { StageBadge } from '../StageBadge'

describe('StageBadge', () => {
  it('renders UPLOADED with gray styling', () => {
    render(<StageBadge stage="UPLOADED" />)
    const badge = screen.getByText('UPLOADED')
    expect(badge).toBeInTheDocument()
    expect(badge.className).toContain('slate')
  })

  it('renders CHECKLIST_MISSING_DOCS with red styling', () => {
    render(<StageBadge stage="CHECKLIST_MISSING_DOCS" />)
    const badge = screen.getByText('MISSING DOCS')
    expect(badge).toBeInTheDocument()
    expect(badge.className).toContain('red')
  })

  it('renders CHECKLIST_VALIDATION with amber styling', () => {
    render(<StageBadge stage="CHECKLIST_VALIDATION" />)
    const badge = screen.getByText('VALIDATING')
    expect(badge).toBeInTheDocument()
    expect(badge.className).toContain('amber')
  })

  it('renders APPROVED with green styling', () => {
    render(<StageBadge stage="APPROVED" />)
    const badge = screen.getByText('APPROVED')
    expect(badge).toBeInTheDocument()
    expect(badge.className).toContain('green')
  })

  it('renders REJECTED with deep red styling', () => {
    render(<StageBadge stage="REJECTED" />)
    const badge = screen.getByText('REJECTED')
    expect(badge).toBeInTheDocument()
    expect(badge.className).toContain('red')
  })

  it('renders INGESTED with indigo styling', () => {
    render(<StageBadge stage="INGESTED" />)
    const badge = screen.getByText('INGESTED')
    expect(badge).toBeInTheDocument()
    expect(badge.className).toContain('indigo')
  })

  it('renders PHASE_2_AUDITING with amber styling', () => {
    render(<StageBadge stage="PHASE_2_AUDITING" />)
    const badge = screen.getByText('AUDITING')
    expect(badge).toBeInTheDocument()
    expect(badge.className).toContain('amber')
  })

  it('renders ESCALATED_TO_CEO with pink styling', () => {
    render(<StageBadge stage="ESCALATED_TO_CEO" />)
    const badge = screen.getByText('ESCALATED')
    expect(badge).toBeInTheDocument()
    expect(badge.className).toContain('pink')
  })

  it('accepts a custom className', () => {
    render(<StageBadge stage="APPROVED" className="test-custom" />)
    const badge = screen.getByText('APPROVED')
    expect(badge.className).toContain('test-custom')
  })
})
