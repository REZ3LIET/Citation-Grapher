import type { GraphData, RunSummary, TopicSearchResponse } from '../types'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options)
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(detail.detail || 'Request failed')
  }
  return response.json() as Promise<T>
}

export const api = {
  createRun: (body: unknown) => request<RunSummary>('/api/runs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }),
  searchTopics: (body: unknown) => request<TopicSearchResponse>('/api/topic-search', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }),
  getRun: (id: string) => request<RunSummary>(`/api/runs/${id}`),
  continueRun: (id: string) => request<RunSummary>(`/api/runs/${id}/continue`, { method: 'POST' }),
  expandRun: (id: string, targetLevel: number) => request<RunSummary>(`/api/runs/${id}/expand`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target_level: targetLevel }),
  }),
  stopRun: (id: string) => request<RunSummary>(`/api/runs/${id}/stop`, { method: 'POST' }),
  graph: (id: string) => request<GraphData>(`/api/runs/${id}/graph`),
  importCsv: (papers: File, citations: File) => {
    const body = new FormData()
    body.append('papers_file', papers)
    body.append('citations_file', citations)
    return request<RunSummary>('/api/import', { method: 'POST', body })
  },
  identifyPdf: (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<{ identifier: string; title: string | null; year: number | null }>('/api/seed-pdfs/identify', { method: 'POST', body })
  },
  exportSubset: async (id: string, body: unknown) => {
    const response = await fetch(`/api/runs/${id}/exports/subset`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    if (!response.ok) {
      const detail = await response.json().catch(() => ({ detail: response.statusText }))
      throw new Error(detail.detail || 'Subset export failed')
    }
    return response.blob()
  },
  exportUrl: (id: string, name: string) => `/api/runs/${id}/exports/${name}`,
}

