import { describe, expect, it } from 'vitest'
import type { Paper } from '../../types'
import {
  combineTopicExpressions, evaluateTopicExpression, parseTopicExpression, topicSelectionExpression,
} from './topicFilters'

const paper = (
  scores: Record<string, number>,
  title = '',
  abstract = '',
) => ({ relevance_scores: scores, title, abstract, topics: [] } as unknown as Paper)

function matches(item: Paper, expression: string, threshold = .2) {
  const parsed = parseTopicExpression(expression)
  if (!parsed.ast) return false
  return evaluateTopicExpression(item, parsed.ast, threshold)
}

describe('Boolean topic expressions', () => {
  const expression = '(LLMs OR Large language models) AND unlearning AND (causal OR counterfactual)'

  it('supports multiple parenthesized OR groups joined with AND', () => {
    expect(matches(paper(
      { unlearning: .8, causal: .4, counterfactual: 0 }, 'Unlearning for LLMs',
    ), expression)).toBe(true)
    expect(matches(paper(
      { unlearning: .8, causal: 0, counterfactual: .5 }, 'Unlearning large language models',
    ), expression)).toBe(true)
    expect(matches(paper(
      { unlearning: .8, causal: 0, counterfactual: 0 }, 'Unlearning for LLMs',
    ), expression)).toBe(false)
    expect(matches(paper(
      { unlearning: 0, causal: .6, counterfactual: .5 }, 'Causal analysis of LLMs',
    ), expression)).toBe(false)
  })

  it('uses AND precedence over OR when parentheses are omitted', () => {
    expect(parseTopicExpression('LLMs OR causal AND unlearning').error).toBeNull()
    expect(matches(paper({}, 'Efficient LLMs'), 'LLMs OR causal AND unlearning')).toBe(true)
    expect(matches(paper({ causal: .7, unlearning: 0 }), 'LLMs OR causal AND unlearning')).toBe(false)
  })

  it('reports malformed expressions instead of silently changing their meaning', () => {
    expect(parseTopicExpression('(unlearning OR causal').error).toMatch(/closing parenthesis/i)
    expect(parseTopicExpression('unlearning (causal)').error).toMatch(/expected AND or OR/i)
    expect(parseTopicExpression('"research AND development').error).toMatch(/closing quote/i)
  })

  it('allows quoted topic names containing operator words', () => {
    const parsed = parseTopicExpression('"research AND development" OR causal')
    expect(parsed.error).toBeNull()
    expect(parsed.terms).toEqual(['research AND development', 'causal'])
  })
})

describe('Topic chip selection', () => {
  it('builds quoted OR/AND expressions that survive operator words in names', () => {
    expect(topicSelectionExpression(['causal', 'research AND development'], 'any'))
      .toBe('"causal" OR "research AND development"')
    const parsed = parseTopicExpression(topicSelectionExpression(['causal', 'research AND development'], 'all'))
    expect(parsed.error).toBeNull()
    expect(parsed.terms).toEqual(['causal', 'research AND development'])
  })

  it('combines the typed expression with the chip selection using AND', () => {
    const combined = combineTopicExpressions('LLMs OR unlearning', topicSelectionExpression(['causal'], 'any'))
    expect(combined).toBe('(LLMs OR unlearning) AND ("causal")')
    expect(matches(paper({ unlearning: .9, causal: .5 }), combined)).toBe(true)
    expect(matches(paper({ unlearning: .9, causal: .1 }), combined)).toBe(false)
    expect(combineTopicExpressions('', '  ')).toBe('')
    expect(combineTopicExpressions('', 'causal')).toBe('causal')
  })
})
