import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DiscoveryProgress } from './DiscoveryProgress'
import type { RunSummary } from '../../types'

const run: RunSummary = {
  id: 'level-one-run', phase: 'completed_partial', outcome: 'provider_retrieval_incomplete',
  config: { depth: 1, seeds: ['one', 'two'] },
  counters: { papers: 33, discovered_papers: 31, resolved_seeds: 2, input_seeds: 2 },
  warnings: [], exclusions: [],
  coverage: { retrieval_complete: false, highest_completed_level: 1 },
  error_code: null, error: null,
  created_at: '2026-10-20T00:00:00Z', updated_at: '2026-10-20T00:00:00Z',
}

describe('DiscoveryProgress level expansion', () => {
  it('offers one-level and automatic remaining-level expansion', () => {
    render(<DiscoveryProgress run={run} onUpdate={vi.fn()} onExplore={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Run next level' })).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /Auto-run remaining levels/ })).not.toBeChecked()
  })

  it('groups repeated warnings and shows their occurrence count', () => {
    render(<DiscoveryProgress run={{ ...run, warnings: [
      { code: 'unresolved_bibliography_entries', message: 'Some bibliography entries could not be resolved.' },
      { code: 'unresolved_bibliography_entries', message: 'Some bibliography entries could not be resolved.' },
    ] }} onUpdate={vi.fn()} onExplore={vi.fn()} />)
    expect(screen.getByText('unresolved bibliography entries (2)')).toBeInTheDocument()
    expect(screen.getAllByText('Some bibliography entries could not be resolved.')).toHaveLength(1)
  })
})
