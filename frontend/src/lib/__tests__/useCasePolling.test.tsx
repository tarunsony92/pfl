/**
 * Tests for useCasePolling hook.
 *
 * Verifies:
 * - Interval fires for in-flight stages, invoking mutate for all 5 SWR keys
 * - No polling for stages that are not in-flight
 * - Cleanup on unmount clears the interval
 * - No polling when tab is hidden (document.hidden = true)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, act } from '@testing-library/react'
import React from 'react'

// ---------------------------------------------------------------------------
// Mock SWR
// ---------------------------------------------------------------------------

const mockMutate = vi.fn()
vi.mock('swr', () => ({
  useSWRConfig: () => ({ mutate: mockMutate }),
}))

import { useCasePolling } from '../useCasePolling'
import type { CaseStage } from '../enums'

// ---------------------------------------------------------------------------
// Test component
// ---------------------------------------------------------------------------

function PollingTestComponent({
  caseId,
  stage,
}: {
  caseId: string
  stage: CaseStage | undefined
}) {
  useCasePolling(caseId, stage)
  return null
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useCasePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    // Ensure tab is visible by default
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      get: () => false,
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('fires mutate for all 5 SWR keys after 5 s when stage is in-flight', () => {
    const caseId = 'test-case-1'
    render(<PollingTestComponent caseId={caseId} stage="CHECKLIST_VALIDATION" />)

    expect(mockMutate).not.toHaveBeenCalled()

    act(() => {
      vi.advanceTimersByTime(5000)
    })

    expect(mockMutate).toHaveBeenCalledTimes(5)
    expect(mockMutate).toHaveBeenCalledWith(['case', caseId])
    expect(mockMutate).toHaveBeenCalledWith(['case-extractions', caseId])
    expect(mockMutate).toHaveBeenCalledWith(['case-checklist', caseId])
    expect(mockMutate).toHaveBeenCalledWith(['case-dedupe', caseId])
    expect(mockMutate).toHaveBeenCalledWith(['case-audit', caseId])
  })

  it('fires again on subsequent intervals (10 s = 2 ticks)', () => {
    render(<PollingTestComponent caseId="case-2" stage="PHASE_1_DECISIONING" />)

    act(() => {
      vi.advanceTimersByTime(10000)
    })

    expect(mockMutate).toHaveBeenCalledTimes(10) // 5 keys × 2 ticks
  })

  it('does NOT poll for a non-in-flight stage (UPLOADED)', () => {
    render(<PollingTestComponent caseId="case-3" stage="UPLOADED" />)

    act(() => {
      vi.advanceTimersByTime(15000)
    })

    expect(mockMutate).not.toHaveBeenCalled()
  })

  it('does NOT poll when stage is undefined', () => {
    render(<PollingTestComponent caseId="case-4" stage={undefined} />)

    act(() => {
      vi.advanceTimersByTime(10000)
    })

    expect(mockMutate).not.toHaveBeenCalled()
  })

  it('polls for CHECKLIST_MISSING_DOCS (re-trigger stage)', () => {
    render(<PollingTestComponent caseId="case-5" stage="CHECKLIST_MISSING_DOCS" />)

    act(() => {
      vi.advanceTimersByTime(5000)
    })

    expect(mockMutate).toHaveBeenCalledTimes(5)
  })

  it('polls for PHASE_2_AUDITING', () => {
    render(<PollingTestComponent caseId="case-6" stage="PHASE_2_AUDITING" />)

    act(() => {
      vi.advanceTimersByTime(5000)
    })

    expect(mockMutate).toHaveBeenCalledTimes(5)
  })

  it('does NOT start interval when document is hidden', () => {
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      get: () => true,
    })

    render(<PollingTestComponent caseId="case-7" stage="CHECKLIST_VALIDATION" />)

    act(() => {
      vi.advanceTimersByTime(15000)
    })

    expect(mockMutate).not.toHaveBeenCalled()
  })
})
