import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { L3PerItemTable, type L3ItemRow } from '../L3PerItemTable'

vi.mock('@/lib/useVerification', () => ({
  useCasePhotos: (
    _caseId: string,
    _subtype: string,
    enabled = true,
  ) => {
    if (!enabled) return { data: undefined, error: undefined, isLoading: false }
    return {
      data: {
        items: [
          {
            artifact_id: 'biz-photo-1',
            filename: 'biz-1.jpg',
            download_url: 'https://example.test/biz-1.jpg',
          },
          {
            artifact_id: 'biz-photo-2',
            filename: 'biz-2.jpg',
            download_url: 'https://example.test/biz-2.jpg',
          },
        ],
      },
      error: undefined,
      isLoading: false,
    }
  },
}))

describe('L3PerItemTable', () => {
  it('renders the auto-refresh notice and fires onAutoRefresh when items is undefined', () => {
    const cb = vi.fn()
    render(<L3PerItemTable items={undefined} caseId="test-case-id" onAutoRefresh={cb} />)
    expect(screen.getByText(/Refreshing per-item breakdown/i)).toBeInTheDocument()
    expect(cb).toHaveBeenCalledTimes(1)
  })

  it('renders the empty-items fallback when items.length === 0', () => {
    render(<L3PerItemTable items={[]} caseId="test-case-id" />)
    expect(
      screen.getByText(/No itemised collateral extracted/i),
    ).toBeInTheDocument()
  })

  it('renders priced items with grand total and unpriced exclusion footnote', () => {
    const items: L3ItemRow[] = [
      {
        description: 'barber chair',
        qty: 2,
        category: 'equipment',
        mrp_estimate_inr: 8500,
        mrp_confidence: 'medium',
      },
      {
        description: 'shampoo bottle',
        qty: 6,
        category: 'consumable',
        mrp_estimate_inr: 250,
        mrp_confidence: 'low',
      },
      {
        description: 'mystery jar',
        qty: 1,
        category: 'other',
        mrp_estimate_inr: null,
        mrp_confidence: 'low',
      },
    ]
    render(<L3PerItemTable items={items} caseId="test-case-id" />)
    expect(screen.getByText(/barber chair/i)).toBeInTheDocument()
    expect(screen.getAllByText(/low conf/i).length).toBeGreaterThanOrEqual(1)
    // Grand total = 17000 + 1500 = 18500. formatInr renders ₹18,500 (or similar).
    expect(screen.getByText(/18,500|18500/)).toBeInTheDocument()
    expect(screen.getByText(/1 item unpriced/i)).toBeInTheDocument()
  })

  it('shows curated source pill and uses catalogue_mrp_inr as the MRP', () => {
    const items: L3ItemRow[] = [
      {
        description: 'barber chair',
        qty: 2,
        category: 'equipment',
        mrp_estimate_inr: 8500,
        mrp_confidence: 'medium',
        catalogue_mrp_inr: 12000,
        mrp_source: 'MANUAL',
        catalogue_entry_id: 'cat-id',
      },
    ]
    render(<L3PerItemTable items={items} caseId="test-case-id" />)
    // Catalogue value should win over AI estimate
    expect(screen.getByText(/12,000|12000/)).toBeInTheDocument()
    // Source pill present
    expect(screen.getByText(/curated/i)).toBeInTheDocument()
    // Grand total = 12000 * 2 = 24000; appears in both line total and grand total cells
    expect(screen.getAllByText(/24,000|24000/).length).toBeGreaterThanOrEqual(1)
  })

  it('shows edited source pill for OVERRIDDEN_FROM_AI', () => {
    const items: L3ItemRow[] = [
      {
        description: 'hair clipper',
        qty: 1,
        category: 'equipment',
        mrp_estimate_inr: 2500,
        mrp_confidence: 'medium',
        catalogue_mrp_inr: 3000,
        mrp_source: 'OVERRIDDEN_FROM_AI',
      },
    ]
    render(<L3PerItemTable items={items} caseId="test-case-id" />)
    expect(screen.getByText(/edited/i)).toBeInTheDocument()
  })

  it('renders "view on photo" button when bbox + source_image are present', () => {
    const items: L3ItemRow[] = [
      {
        description: 'barber chair',
        qty: 2,
        category: 'equipment',
        mrp_estimate_inr: 8500,
        mrp_confidence: 'medium',
        bbox: [0.1, 0.1, 0.3, 0.3],
        source_image: 1,
      },
    ]
    render(<L3PerItemTable items={items} caseId="test-case-id" />)
    expect(screen.getByText(/view on photo/i)).toBeInTheDocument()
  })

  it('does NOT render "view on photo" when bbox is null', () => {
    const items: L3ItemRow[] = [
      {
        description: 'wall mirror',
        qty: 3,
        category: 'equipment',
        mrp_estimate_inr: 1200,
        mrp_confidence: 'high',
        bbox: null,
        source_image: 1,
      },
    ]
    render(<L3PerItemTable items={items} caseId="test-case-id" />)
    expect(screen.queryByText(/view on photo/i)).not.toBeInTheDocument()
  })

  it('opens modal with SVG bbox overlay when "view on photo" is clicked', () => {
    const items: L3ItemRow[] = [
      {
        description: 'barber chair',
        qty: 2,
        category: 'equipment',
        mrp_estimate_inr: 8500,
        mrp_confidence: 'medium',
        bbox: [0.1, 0.2, 0.4, 0.5],
        source_image: 1,
      },
    ]
    render(<L3PerItemTable items={items} caseId="test-case-id" />)
    fireEvent.click(screen.getByText(/view on photo/i))
    // Modal opened
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    // SVG overlay rendered with the rect at the normalised coords
    const svg = screen.getByTestId('bbox-overlay-svg')
    expect(svg).toBeInTheDocument()
    const rect = svg.querySelector('rect')
    expect(rect).not.toBeNull()
    expect(rect?.getAttribute('x')).toBe('0.1')
    expect(rect?.getAttribute('y')).toBe('0.2')
    // width = x1 - x0 = 0.3, height = y1 - y0 = 0.3
    expect(parseFloat(rect!.getAttribute('width')!)).toBeCloseTo(0.3)
    expect(parseFloat(rect!.getAttribute('height')!)).toBeCloseTo(0.3)
  })
})
