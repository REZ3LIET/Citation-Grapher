import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DiscoveredPapers } from './DiscoveredPapers'
import type { Paper } from '../../types'

const paper: Paper = {
  id: 'p1', title: 'Recent graph research', authors: ['Ada Author'], year: 2025,
  venue: 'Journal', abstract: 'Abstract', doi: null, url: null, is_seed: false,
  depth: 1, provider_citation_count: 2, internal_in_count: 1, internal_out_count: 1,
  topics: ['citation graphs', 'causal'], relevance_scores: { 'citation graphs': 0.82, causal: 0.61, unrelated: 0 },
  classification_status: 'classified', provenance: {},
}

describe('DiscoveredPapers', () => {
  it('emphasizes year and topic relevance and links selection', () => {
    const onSelect = vi.fn()
    render(<DiscoveredPapers papers={[paper]} selected={null} onSelect={onSelect} />)
    expect(screen.getByText('2025')).toBeInTheDocument()
    expect(screen.getByText('citation graphs')).toBeInTheDocument()
    expect(screen.getByText('82%')).toBeInTheDocument()
    expect(screen.getByText('causal')).toBeInTheDocument()
    expect(screen.getByText('61%')).toBeInTheDocument()
    expect(screen.queryByText('unrelated')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('Recent graph research'))
    expect(onSelect).toHaveBeenCalledWith('p1')
  })
})

