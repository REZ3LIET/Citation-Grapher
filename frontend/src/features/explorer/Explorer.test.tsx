import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { GraphData, Paper } from '../../types'
import { Explorer } from './Explorer'

vi.mock('./GraphCanvas', () => ({ GraphCanvas: () => <div aria-label="Mock graph" /> }))

const makePaper = (id: string, isSeed: boolean): Paper => ({
  id, title: `Paper ${id}`, authors: ['Author'], year: 2025, venue: null, abstract: null,
  doi: null, url: null, is_seed: isSeed, depth: isSeed ? 0 : 1,
  provider_citation_count: 1, internal_in_count: 0, internal_out_count: 0,
  topics: ['unlearning'], relevance_scores: { unlearning: .8, causal: .4, counterfactual: 0 },
  classification_status: 'classified', provenance: {},
})

const data: GraphData = {
  run: {
    id: 'run', phase: 'completed', outcome: null, config: {}, counters: {}, warnings: [],
    exclusions: [], coverage: {}, error_code: null, error: null,
    created_at: '2026-10-20T00:00:00Z', updated_at: '2026-10-20T00:00:00Z',
  },
  papers: [makePaper('p1', true), makePaper('p2', false)],
  citations: [{ source: 'p2', target: 'p1', provenance: {} }],
}

describe('Explorer graph navigation', () => {
  it('returns to the previous selection and resets filters', () => {
    render(<Explorer data={data} />)
    fireEvent.click(document.getElementById('paper-p2')!)
    expect(document.getElementById('paper-p2')).toHaveClass('selected')
    fireEvent.click(screen.getByRole('button', { name: 'Previous selection' }))
    expect(document.getElementById('paper-p1')).toHaveClass('selected')

    fireEvent.change(screen.getByLabelText('Search papers'), { target: { value: 'missing' } })
    expect(screen.getByText('No papers match the current filters.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reset graph' }))
    expect(screen.getAllByText('Paper p1').length).toBeGreaterThan(0)
    expect(screen.getByLabelText('Search papers')).toHaveValue('')
  })
})
