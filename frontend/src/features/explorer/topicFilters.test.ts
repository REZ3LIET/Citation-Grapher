import { describe, expect, it } from 'vitest'
import type { Paper } from '../../types'
import { matchesTopicRules } from './topicFilters'

const paper = (scores: Record<string, number>) => ({ relevance_scores: scores } as Paper)

describe('Boolean topic filtering', () => {
  const rules = { unlearning: 'must', causal: 'any', counterfactual: 'any' } as const

  it('represents unlearning AND (causal OR counterfactual)', () => {
    expect(matchesTopicRules(paper({ unlearning: .8, causal: .4, counterfactual: 0 }), rules, .2)).toBe(true)
    expect(matchesTopicRules(paper({ unlearning: .8, causal: 0, counterfactual: .5 }), rules, .2)).toBe(true)
    expect(matchesTopicRules(paper({ unlearning: .8, causal: 0, counterfactual: 0 }), rules, .2)).toBe(false)
    expect(matchesTopicRules(paper({ unlearning: 0, causal: .6, counterfactual: .5 }), rules, .2)).toBe(false)
  })
})
