import { useCallback, useMemo, useState } from 'react'
import { ArrowLeft, Download, ExternalLink, Filter, List, Network, RotateCcw, Search } from 'lucide-react'
import { api } from '../../api/client'
import type { GraphData, Paper } from '../../types'
import { DiscoveredPapers } from './DiscoveredPapers'
import { GraphCanvas } from './GraphCanvas'
import { evaluateTopicExpression, parseTopicExpression } from './topicFilters'

type Props = { data: GraphData }

export function Explorer({ data }: Props) {
  const years = data.papers.map((paper) => paper.year)
  const initialSelection = data.papers.find((paper) => paper.is_seed)?.id ?? data.papers[0]?.id ?? null
  const [query, setQuery] = useState('')
  const [minYear, setMinYear] = useState(Math.min(...years))
  const [maxYear, setMaxYear] = useState(Math.max(...years))
  const [topicExpression, setTopicExpression] = useState('')
  const [minRelevance, setMinRelevance] = useState(0)
  const [role, setRole] = useState('all')
  const [citationMetric, setCitationMetric] = useState<'provider' | 'internal'>('provider')
  const [minCitations, setMinCitations] = useState(0)
  const [distance, setDistance] = useState(0)
  const [selected, setSelected] = useState<string | null>(initialSelection)
  const [selectionHistory, setSelectionHistory] = useState<string[]>([])
  const [view, setView] = useState<'split' | 'list'>('split')
  const [exportingSubset, setExportingSubset] = useState(false)
  const [subsetExportError, setSubsetExportError] = useState<string | null>(null)
  const topics = useMemo(() => [...new Set(data.papers.flatMap((paper) => Object.keys(paper.relevance_scores)))], [data])
  const parsedTopics = useMemo(() => parseTopicExpression(topicExpression), [topicExpression])
  const activeTopics = parsedTopics.terms
  const distanceIds = useMemo(() => {
    if (!selected || distance === 0) return null
    const neighbors = new Map<string, Set<string>>()
    data.citations.forEach(({ source, target }) => {
      if (!neighbors.has(source)) neighbors.set(source, new Set())
      if (!neighbors.has(target)) neighbors.set(target, new Set())
      neighbors.get(source)!.add(target); neighbors.get(target)!.add(source)
    })
    const reached = new Set([selected]); let frontier = [selected]
    for (let hop = 0; hop < distance; hop++) {
      frontier = frontier.flatMap((id) => [...(neighbors.get(id) ?? [])]).filter((id) => !reached.has(id))
      frontier.forEach((id) => reached.add(id))
    }
    return reached
  }, [data.citations, selected, distance])
  const papers = useMemo(() => data.papers.filter((paper) => {
    const haystack = `${paper.title} ${paper.authors.join(' ')} ${paper.doi ?? ''} ${paper.id}`.toLowerCase()
    const citationCount = citationMetric === 'provider' ? (paper.provider_citation_count ?? 0) : paper.internal_in_count
    return paper.year >= minYear && paper.year <= maxYear && haystack.includes(query.toLowerCase())
      && (role === 'all' || (role === 'seed') === paper.is_seed)
      && (!topicExpression.trim() || (!!parsedTopics.ast && evaluateTopicExpression(paper, parsedTopics.ast, minRelevance)))
      && citationCount >= minCitations && (!distanceIds || distanceIds.has(paper.id))
  }).sort((a, b) => b.year - a.year || (Math.max(...activeTopics.map((topic) => Object.entries(b.relevance_scores).find(([name]) => name.toLowerCase() === topic.toLowerCase())?.[1] ?? 0), 0) - Math.max(...activeTopics.map((topic) => Object.entries(a.relevance_scores).find(([name]) => name.toLowerCase() === topic.toLowerCase())?.[1] ?? 0), 0)) || a.title.localeCompare(b.title)), [data, minYear, maxYear, query, role, topicExpression, parsedTopics, activeTopics, minRelevance, citationMetric, minCitations, distanceIds])
  const selectedPaper = data.papers.find((paper) => paper.id === selected) ?? null
  const selectPaper = useCallback((id: string) => {
    if (id === selected) return
    if (selected) setSelectionHistory((current) => [...current, selected].slice(-50))
    setSelected(id)
    document.getElementById(`paper-${encodeURIComponent(id)}`)?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
  }, [selected])
  const selectPrevious = () => setSelectionHistory((current) => {
    const next = [...current]
    const previous = next.pop()
    if (previous) setSelected(previous)
    return next
  })
  const resetGraph = () => {
    setQuery('')
    setMinYear(Math.min(...years))
    setMaxYear(Math.max(...years))
    setTopicExpression('')
    setMinRelevance(0)
    setRole('all')
    setCitationMetric('provider')
    setMinCitations(0)
    setDistance(0)
    setSelected(initialSelection)
    setSelectionHistory([])
  }
  const exportSubset = async () => {
    if (!papers.length || parsedTopics.error) return
    setExportingSubset(true)
    setSubsetExportError(null)
    try {
      const blob = await api.exportSubset(data.run.id, {
        paper_ids: papers.map((paper) => paper.id),
        filter_expression: topicExpression.trim() || null,
        filters: {
          query, min_year: minYear, max_year: maxYear, role,
          minimum_relevance: minRelevance, citation_metric: citationMetric,
          minimum_citations: minCitations, distance,
        },
      })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `citation-subset-${data.run.id.slice(0, 8)}.zip`
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      setSubsetExportError(error instanceof Error ? error.message : 'Subset export failed')
    } finally {
      setExportingSubset(false)
    }
  }
  return <main className="explorer-page">
    <header className="explorer-header"><div><p className="step-label">Citation graph explorer</p><h1>Research connected to your seeds</h1></div>
      <div className="explorer-actions"><button className="subset-export" disabled={!papers.length || !!parsedTopics.error || exportingSubset} onClick={exportSubset}><Download size={15} /> {exportingSubset ? 'Preparing…' : `Export subset (${papers.length})`}</button><div className="graph-navigation"><button disabled={!selectionHistory.length} onClick={selectPrevious}><ArrowLeft size={15} /> Previous selection</button><button onClick={resetGraph}><RotateCcw size={15} /> Reset graph</button></div><div className="view-toggle"><button className={view === 'split' ? 'active' : ''} onClick={() => setView('split')}><Network size={16} /> Graph + list</button><button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}><List size={16} /> List first</button></div></div>
    </header>
    <section className="filter-bar"><Filter size={17} /><label className="search-field"><Search size={16} /><input aria-label="Search papers" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Title, author, DOI, or ID" /></label>
      <label>Years <input aria-label="Minimum year" type="number" value={minYear} onChange={(e) => setMinYear(+e.target.value)} />–<input aria-label="Maximum year" type="number" value={maxYear} onChange={(e) => setMaxYear(+e.target.value)} /></label>
      {!!activeTopics.length && <label>Relevance <input type="range" min="0" max="1" step="0.05" value={minRelevance} onChange={(e) => setMinRelevance(+e.target.value)} /><span>{Math.round(minRelevance * 100)}%</span></label>}
      <label>Role <select value={role} onChange={(e) => setRole(e.target.value)}><option value="all">All papers</option><option value="seed">Seeds</option><option value="discovered">Discovered</option></select></label>
      <label>Citations <select value={citationMetric} onChange={(e) => setCitationMetric(e.target.value as 'provider' | 'internal')}><option value="provider">Provider</option><option value="internal">Internal incoming</option></select><input aria-label="Minimum citation count" type="number" min="0" value={minCitations} onChange={(e) => setMinCitations(+e.target.value)} /></label>
      <label>Distance <select value={distance} onChange={(e) => setDistance(+e.target.value)}><option value={0}>All</option><option value={1}>1 hop</option><option value={2}>2 hops</option><option value={3}>3 hops</option></select></label>
    </section>
    <section className={`boolean-filter ${parsedTopics.error ? 'invalid' : ''}`}><div><strong>Topic logic</strong><span>Type topic names with AND, OR, and parentheses.</span></div><input aria-label="Boolean topic expression" aria-invalid={!!parsedTopics.error} value={topicExpression} onChange={(event) => setTopicExpression(event.target.value)} placeholder="(LLMs OR Large language models) AND unlearning AND (causal OR counterfactual)" />{parsedTopics.error ? <small role="alert">{parsedTopics.error}</small> : <small>{topicExpression ? `${papers.length} matching papers` : `Available scored topics: ${topics.join(', ') || 'none'}`}</small>}</section>
    {subsetExportError && <div className="error">{subsetExportError}</div>}
    {data.run.phase === 'completed_partial' && <div className="partial-banner">Partial run · {data.run.outcome?.replaceAll('_', ' ')}. Coverage details remain available in the export report.</div>}
    <div className={`explorer-layout ${view}`}>
      <DiscoveredPapers papers={papers} selected={selected} onSelect={selectPaper} minRelevance={minRelevance} />
      {view === 'split' && <section className="graph-panel"><GraphCanvas papers={papers} citations={data.citations} selected={selected} onSelect={selectPaper} />
        <div className="legend"><span><i className="seed-dot" /> Seed</span><span><i /> Discovered</span><small>Arrows point from citing to cited paper</small></div></section>}
      {selectedPaper && <PaperDetail paper={selectedPaper} edges={data.citations} papers={data.papers} onSelect={selectPaper} />}
    </div>
  </main>
}

function PaperDetail({ paper, edges, papers, onSelect }: { paper: Paper; edges: GraphData['citations']; papers: Paper[]; onSelect: (id: string) => void }) {
  const linked = edges.filter((edge) => edge.source === paper.id || edge.target === paper.id).slice(0, 8)
  const byId = new Map(papers.map((item) => [item.id, item]))
  return <aside className="paper-detail"><div className="detail-kicker"><span>{paper.year}</span>{paper.is_seed ? 'Seed paper' : `Discovered at depth ${paper.depth}`}</div><h2>{paper.title}</h2><p className="authors">{paper.authors.join(', ')}</p>
    <p className="venue">{paper.venue || 'Venue unavailable'}</p>{paper.url && <a href={paper.url} target="_blank" rel="noreferrer">Open publication <ExternalLink size={14} /></a>}
    {paper.abstract && <div className="detail-section"><h3>Abstract</h3><p>{paper.abstract}</p></div>}
    <div className="detail-section"><h3>Topic relevance</h3><div className="score-list">{Object.entries(paper.relevance_scores).sort((a,b) => b[1]-a[1]).map(([name, score]) => <div key={name}><span>{name}</span><div><i style={{ width: `${Math.max(0, score) * 100}%` }} /></div><b>{score.toFixed(2)}</b></div>)}</div></div>
    <div className="detail-section"><h3>Connections in this graph</h3>{linked.map((edge, index) => { const id = edge.source === paper.id ? edge.target : edge.source; const target = byId.get(id); return <button className="linked-paper" key={`${id}-${index}`} onClick={() => onSelect(id)}><span>{edge.source === paper.id ? 'Cites' : 'Cited by'}</span>{target?.title ?? id}</button> })}</div>
  </aside>
}

