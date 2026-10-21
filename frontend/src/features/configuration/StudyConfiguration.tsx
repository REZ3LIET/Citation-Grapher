import { FormEvent, useState } from 'react'
import { ArrowRight, FileUp, Network } from 'lucide-react'
import { api } from '../../api/client'
import type { RunSummary, TopicSearchResponse } from '../../types'

type Props = { onCreated: (run: RunSummary) => void }

export function StudyConfiguration({ onCreated }: Props) {
  const [mode, setMode] = useState<'seeds' | 'topic'>('seeds')
  const [seeds, setSeeds] = useState('')
  const [topics, setTopics] = useState('')
  const [topicQuery, setTopicQuery] = useState('')
  const [topicResults, setTopicResults] = useState<TopicSearchResponse | null>(null)
  const [selectedResults, setSelectedResults] = useState<string[]>([])
  const [searching, setSearching] = useState(false)
  const [minYear, setMinYear] = useState(2018)
  const [maxYear, setMaxYear] = useState(new Date().getFullYear())
  const [direction, setDirection] = useState('both')
  const [depth, setDepth] = useState(1)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [pdfStatus, setPdfStatus] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const seedList = mode === 'seeds'
        ? seeds.split(/\n|,/).map((value) => value.trim()).filter(Boolean)
        : (topicResults?.papers ?? []).filter((paper) => selectedResults.includes(paper.id)).map((paper) => paper.openalex_id ? `https://openalex.org/${paper.openalex_id}` : paper.doi ? `https://doi.org/${paper.doi}` : paper.id)
      if (!seedList.length) throw new Error('Select at least one paper to use as a seed')
      const topicList = topics.split(/\n|,/).map((value) => value.trim()).filter(Boolean)
      onCreated(await api.createRun({ seeds: seedList, topics: topicList, min_year: minYear,
        max_year: maxYear, direction, depth }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not start discovery')
    } finally { setSubmitting(false) }
  }

  async function searchByTopic() {
    setError('')
    setSearching(true)
    try {
      const result = await api.searchTopics({ query: topicQuery, min_year: minYear, max_year: maxYear, limit: 25 })
      setTopicResults(result)
      setSelectedResults([])
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Topic search failed')
    } finally { setSearching(false) }
  }

  async function importFiles(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const papers = form.get('papers')
    const citations = form.get('citations')
    if (papers instanceof File && citations instanceof File) {
      try { onCreated(await api.importCsv(papers, citations)) }
      catch (caught) { setError(caught instanceof Error ? caught.message : 'Import failed') }
    }
  }

  async function addPdf(file: File | undefined) {
    if (!file) return
    setPdfStatus('Extracting metadata locally…')
    try {
      const result = await api.identifyPdf(file)
      setSeeds((current) => `${current}${current.trim() ? '\n' : ''}${result.identifier}`)
      setPdfStatus(`Added ${result.title || result.identifier}${result.year ? ` (${result.year})` : ''}`)
    } catch (caught) {
      setPdfStatus(caught instanceof Error ? caught.message : 'PDF extraction failed')
    }
  }

  return <main className="configuration page-grid">
    <section className="intro-panel">
      <div className="eyebrow"><Network size={15} /> Citation-connected discovery</div>
      <h1>Follow the literature,<br /><em>not just the citations.</em></h1>
      <p className="lede">Begin with papers you trust. Trace the work around them, surface recent developments, and keep a reproducible record of what was—and was not—retrieved.</p>
      <div className="principles">
        <div><span>01</span><p><strong>Recent by design</strong>Use a strict publication window and newest-first paper list.</p></div>
        <div><span>02</span><p><strong>Transparent coverage</strong>Every provider limit and incomplete frontier stays visible.</p></div>
        <div><span>03</span><p><strong>Reproducible</strong>Export canonical papers, citations, provenance, and run metadata.</p></div>
      </div>
    </section>
    <section className="form-panel surface">
      <div><p className="step-label">Study configuration</p><h2>Define your starting point</h2></div>
      <form onSubmit={submit}>
        <div className="mode-toggle" aria-label="Discovery starting mode"><button type="button" className={mode === 'seeds' ? 'active' : ''} onClick={() => setMode('seeds')}>Start with papers</button><button type="button" className={mode === 'topic' ? 'active' : ''} onClick={() => setMode('topic')}>Search by topic</button></div>
        {mode === 'seeds' ? <>
          <label>Seed papers <span>one or more</span>
            <textarea value={seeds} onChange={(e) => setSeeds(e.target.value)} rows={5}
              placeholder={'One DOI, OpenAlex ID, arXiv ID, or URL per line\n10.1038/s41586-023-...\nhttps://arxiv.org/abs/...'} required />
          </label>
          <label className="pdf-seed">Or add a paper PDF <span>processed by local GROBID</span>
            <input type="file" accept="application/pdf,.pdf" onChange={(event) => addPdf(event.target.files?.[0])} />
            {pdfStatus && <small>{pdfStatus}</small>}
          </label>
        </> : <section className="topic-search-panel">
          <label>Boolean paper search <span>title, abstract, full text, and keywords</span>
            <textarea aria-label="Boolean paper search" value={topicQuery} onChange={(event) => setTopicQuery(event.target.value)} rows={3} placeholder={'unlearning AND (causal OR counterfactual)'} required />
          </label>
          <button type="button" className="secondary topic-search-button" disabled={searching || topicQuery.trim().length < 2} onClick={searchByTopic}>{searching ? 'Searching…' : 'Find papers'}</button>
          {topicResults && <div className="topic-results"><div className="topic-results-heading"><strong>{topicResults.papers.length} candidate papers</strong><button type="button" onClick={() => setSelectedResults(selectedResults.length === topicResults.papers.length ? [] : topicResults.papers.map((paper) => paper.id))}>{selectedResults.length === topicResults.papers.length ? 'Clear selection' : 'Select all'}</button></div>
            {topicResults.coverage.provider === 'arxiv' && <p className="search-coverage">OpenAlex’s keyless allowance was unavailable, so these results came from the bounded arXiv fallback.</p>}
            {topicResults.coverage.capped && <p className="search-coverage">Showing the first {topicResults.papers.length} of {topicResults.coverage.known_total ?? 'more'} matches. Refine the query for narrower coverage.</p>}
            <div className="topic-result-list">{topicResults.papers.map((paper) => <label key={paper.id} className="topic-result"><input type="checkbox" checked={selectedResults.includes(paper.id)} onChange={() => setSelectedResults((current) => current.includes(paper.id) ? current.filter((id) => id !== paper.id) : [...current, paper.id])} /><span><b>{paper.year} · {paper.title}</b><small>{paper.authors.slice(0, 3).join(', ') || 'Authors unavailable'} · {paper.citation_count ?? '—'} citations</small></span></label>)}</div>
          </div>}
        </section>}
        <label>Guiding topics <span>annotation only</span>
          <textarea value={topics} onChange={(e) => setTopics(e.target.value)} rows={3}
            placeholder="e.g. retrieval-augmented generation, citation recommendation" required />
        </label>
        <div className="field-row">
          <label>From year<input type="number" value={minYear} onChange={(e) => setMinYear(+e.target.value)} /></label>
          <label>To year<input type="number" value={maxYear} onChange={(e) => setMaxYear(+e.target.value)} /></label>
        </div>
        <div className="field-row">
          <label>Direction<select value={direction} onChange={(e) => setDirection(e.target.value)}>
            <option value="both">Forward + backward</option><option value="forward">Forward only</option><option value="backward">Backward only</option>
          </select></label>
          <label>Expansion level<select value={depth} onChange={(e) => setDepth(+e.target.value)}>
            <option value={1}>Level 1 (recommended)</option><option value={2}>Level 2</option><option value={3}>Level 3</option>
          </select></label>
        </div>
        <aside className="limitation"><strong>Coverage note</strong>This application discovers papers through citation relationships with the supplied seed papers. Relevant publications without a discovered citation path to the seeds may be omitted.</aside>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={submitting || (mode === 'topic' && !selectedResults.length)}>{submitting ? 'Starting…' : mode === 'topic' ? `Build graph from ${selectedResults.length} selected` : 'Begin discovery'} <ArrowRight size={18} /></button>
      </form>
      <div className="divider"><span>or explore an existing dataset</span></div>
      <form className="import-form" onSubmit={importFiles}>
        <label><FileUp size={16} /> papers.csv<input name="papers" type="file" accept=".csv" required /></label>
        <label><FileUp size={16} /> citations.csv<input name="citations" type="file" accept=".csv" required /></label>
        <button className="secondary">Import CSV pair</button>
      </form>
    </section>
  </main>
}

