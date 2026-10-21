import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { StudyConfiguration } from './StudyConfiguration'

describe('StudyConfiguration', () => {
  it('shows the required disconnected-paper limitation', () => {
    render(<StudyConfiguration onCreated={vi.fn()} />)
    expect(screen.getByText(/Relevant publications without a discovered citation path/)).toBeInTheDocument()
    expect(screen.getByText(/processed by local GROBID/)).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /Level 1 \(recommended\)/ })).toHaveProperty('selected', true)
  })

  it('searches by topic and enables graph creation after paper selection', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        query: 'unlearning AND causal',
        papers: [{ id: 'openalex:W1', openalex_id: 'W1', doi: null, title: 'Found paper', authors: ['Ada'], year: 2025, venue: null, abstract: null, url: 'https://openalex.org/W1', citation_count: 4 }],
        coverage: { capped: true, known_total: 9 },
      }),
    }))
    render(<StudyConfiguration onCreated={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Search by topic' }))
    fireEvent.change(screen.getByLabelText('Boolean paper search'), { target: { value: 'unlearning AND causal' } })
    fireEvent.click(screen.getByRole('button', { name: 'Find papers' }))
    await waitFor(() => expect(screen.getByText(/Found paper/)).toBeInTheDocument())
    expect(screen.getByText(/Showing the first 1 of 9 matches/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox'))
    expect(screen.getByRole('button', { name: /Build graph from 1 selected/ })).toBeEnabled()
    vi.unstubAllGlobals()
  })
})

