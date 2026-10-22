import { describe, expect, it } from 'vitest'
import type { Citation, Paper } from '../../types'
import { assignCitationLayers, buildLayeredPositions } from './graphLayout'

const paper = (id: string, depth: number, directions: string[] = [], seed = false): Paper => ({
  id, title: id, authors: [], year: 2026 - depth, venue: null, abstract: null,
  doi: null, url: null, is_seed: seed, depth, provider_citation_count: 0,
  internal_in_count: 0, internal_out_count: 0, topics: [], relevance_scores: {},
  classification_status: 'classified', provenance: { directions },
})

describe('citation layer layout', () => {
  it('places backward generations left and forward generations right of seeds', () => {
    const papers = [
      paper('seed', 0, ['seed'], true),
      paper('back-1', 1, ['backward']), paper('back-2', 2, ['backward']),
      paper('forward-1', 1, ['forward']), paper('forward-2', 2, ['forward']),
    ]
    const citations: Citation[] = [
      { source: 'seed', target: 'back-1', provenance: {} },
      { source: 'back-1', target: 'back-2', provenance: {} },
      { source: 'forward-1', target: 'seed', provenance: {} },
      { source: 'forward-2', target: 'forward-1', provenance: {} },
    ]

    expect(Object.fromEntries(assignCitationLayers(papers, citations))).toEqual({
      seed: 0, 'back-1': -1, 'back-2': -2, 'forward-1': 1, 'forward-2': 2,
    })
    const positions = new Map(buildLayeredPositions(papers, citations).map((item) => [item.paper.id, item.position.x]))
    expect(positions.get('back-2')).toBeLessThan(positions.get('back-1')!)
    expect(positions.get('back-1')).toBeLessThan(positions.get('seed')!)
    expect(positions.get('forward-1')).toBeGreaterThan(positions.get('seed')!)
    expect(positions.get('forward-2')).toBeGreaterThan(positions.get('forward-1')!)
  })

  it('infers a side from citation direction for imported papers without provenance', () => {
    const papers = [paper('seed', 0, [], true), paper('reference', 1), paper('citing', 1)]
    const citations: Citation[] = [
      { source: 'seed', target: 'reference', provenance: {} },
      { source: 'citing', target: 'seed', provenance: {} },
    ]
    expect(Object.fromEntries(assignCitationLayers(papers, citations))).toEqual({
      seed: 0, reference: -1, citing: 1,
    })
  })
})

