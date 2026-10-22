import type { Paper } from '../../types'

export type TopicExpression =
  | { type: 'term'; value: string }
  | { type: 'and' | 'or'; left: TopicExpression; right: TopicExpression }

export type ParsedTopicExpression = {
  ast: TopicExpression | null
  terms: string[]
  error: string | null
}

function tokenize(expression: string): string[] {
  const tokens: string[] = []
  let buffer = ''
  let quoted = false
  const flush = () => {
    const value = buffer.trim()
    if (value) tokens.push(value)
    buffer = ''
  }
  for (let index = 0; index < expression.length;) {
    const character = expression[index]
    if (character === '"') {
      quoted = !quoted
      index += 1
      continue
    }
    if (!quoted && (character === '(' || character === ')')) {
      flush()
      tokens.push(character)
      index += 1
      continue
    }
    if (!quoted) {
      const operator = expression.slice(index).match(/^(AND|OR)\b/i)?.[1]
      const beforeBoundary = index === 0 || /[\s(]/.test(expression[index - 1])
      const after = operator ? expression[index + operator.length] : undefined
      const afterBoundary = after === undefined || /[\s)]/.test(after)
      if (operator && beforeBoundary && afterBoundary) {
        flush()
        tokens.push(operator.toUpperCase())
        index += operator.length
        continue
      }
    }
    buffer += character
    index += 1
  }
  if (quoted) throw new Error('Missing closing quote')
  flush()
  return tokens
}

export function parseTopicExpression(expression: string): ParsedTopicExpression {
  let tokens: string[]
  try {
    tokens = tokenize(expression)
  } catch (error) {
    return {
      ast: null, terms: [],
      error: error instanceof Error ? error.message : 'Invalid topic expression',
    }
  }
  if (!tokens.length) return { ast: null, terms: [], error: null }
  let index = 0
  const terms: string[] = []

  const primary = (): TopicExpression => {
    const token = tokens[index]
    if (!token) throw new Error('Expected a topic or opening parenthesis')
    if (token === '(') {
      index += 1
      const nested = orExpression()
      if (tokens[index] !== ')') throw new Error('Missing closing parenthesis')
      index += 1
      return nested
    }
    if (token === ')' || /^(AND|OR)$/i.test(token)) throw new Error(`Unexpected “${token}”`)
    index += 1
    const value = token.trim()
    if (!value) throw new Error('Topic names cannot be empty')
    terms.push(value)
    return { type: 'term', value }
  }

  const andExpression = (): TopicExpression => {
    let left = primary()
    while (/^AND$/i.test(tokens[index] ?? '')) {
      index += 1
      left = { type: 'and', left, right: primary() }
    }
    return left
  }

  const orExpression = (): TopicExpression => {
    let left = andExpression()
    while (/^OR$/i.test(tokens[index] ?? '')) {
      index += 1
      left = { type: 'or', left, right: andExpression() }
    }
    return left
  }

  try {
    const ast = orExpression()
    if (index !== tokens.length) throw new Error(`Expected AND or OR before “${tokens[index]}”`)
    return { ast, terms: [...new Set(terms)], error: null }
  } catch (error) {
    return {
      ast: null,
      terms: [...new Set(terms)],
      error: error instanceof Error ? error.message : 'Invalid topic expression',
    }
  }
}

function normalized(value: string): string {
  return value.toLocaleLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
}

export function topicMeetsThreshold(paper: Paper, topic: string, threshold: number) {
  const wanted = normalized(topic)
  const scoreEntry = Object.entries(paper.relevance_scores).find(([name]) => normalized(name) === wanted)
  if (scoreEntry) return threshold === 0 ? scoreEntry[1] > 0 : scoreEntry[1] >= threshold

  // Literal matching keeps aliases useful even when they were not included in
  // the original embedding topics. It does not fabricate a similarity score.
  const text = normalized([paper.title, paper.abstract ?? '', ...paper.topics].join(' '))
  return !!wanted && (` ${text} `).includes(` ${wanted} `)
}

export function evaluateTopicExpression(
  paper: Paper,
  expression: TopicExpression,
  threshold: number,
): boolean {
  if (expression.type === 'term') return topicMeetsThreshold(paper, expression.value, threshold)
  if (expression.type === 'and') {
    return evaluateTopicExpression(paper, expression.left, threshold)
      && evaluateTopicExpression(paper, expression.right, threshold)
  }
  return evaluateTopicExpression(paper, expression.left, threshold)
    || evaluateTopicExpression(paper, expression.right, threshold)
}
