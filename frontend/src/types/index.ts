export type RunSummary = {
  id: string
  phase: string
  outcome: string | null
  config: Record<string, any>
  counters: Record<string, any>
  warnings: Array<Record<string, any>>
  exclusions: Array<Record<string, any>>
  coverage: Record<string, any>
  error_code: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export type Paper = {
  id: string
  title: string
  authors: string[]
  year: number
  venue: string | null
  abstract: string | null
  doi: string | null
  url: string | null
  is_seed: boolean
  depth: number
  provider_citation_count: number | null
  internal_in_count: number
  internal_out_count: number
  topics: string[]
  relevance_scores: Record<string, number>
  classification_status: string
  provenance: Record<string, any>
}

export type Citation = { source: string; target: string; provenance: Record<string, any> }
export type GraphData = { run: RunSummary; papers: Paper[]; citations: Citation[] }

export type TopicSearchPaper = {
  id: string
  openalex_id: string | null
  doi: string | null
  title: string
  authors: string[]
  year: number
  venue: string | null
  abstract: string | null
  url: string | null
  citation_count: number | null
}

export type TopicSearchResponse = {
  query: string
  papers: TopicSearchPaper[]
  coverage: Record<string, any>
}

