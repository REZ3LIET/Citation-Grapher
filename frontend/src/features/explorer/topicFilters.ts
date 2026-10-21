import type { Paper } from '../../types'

export type TopicRule = 'off' | 'must' | 'any'
export type TopicRules = Record<string, TopicRule>

export function topicMeetsThreshold(paper: Paper, topic: string, threshold: number) {
  const score = paper.relevance_scores[topic]
  if (score === undefined) return false
  return threshold === 0 ? score > 0 : score >= threshold
}

export function matchesTopicRules(paper: Paper, rules: TopicRules, threshold: number) {
  const must = Object.entries(rules).filter(([, rule]) => rule === 'must').map(([topic]) => topic)
  const any = Object.entries(rules).filter(([, rule]) => rule === 'any').map(([topic]) => topic)
  return must.every((topic) => topicMeetsThreshold(paper, topic, threshold))
    && (any.length === 0 || any.some((topic) => topicMeetsThreshold(paper, topic, threshold)))
}
