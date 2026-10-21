import { AlertTriangle, CheckCircle2, Database, GitFork, LoaderCircle, PauseCircle } from 'lucide-react'
import { useMemo, useState } from 'react'
import { api } from '../../api/client'
import type { RunSummary } from '../../types'

type Props = { run: RunSummary; onUpdate: (run: RunSummary) => void; onExplore: () => void }

export function DiscoveryProgress({ run, onUpdate, onExplore }: Props) {
  const [autoNext, setAutoNext] = useState(false)
  const papers = run.counters.papers ?? Object.values(run.counters.papers_by_depth ?? {}).reduce((a: number, b) => a + Number(b), 0)
  const finished = ['completed', 'completed_partial'].includes(run.phase)
  const failed = run.phase === 'failed'
  const paused = run.phase === 'awaiting_continue'
  const completedLevel = Number(run.coverage.highest_completed_level ?? run.config.depth ?? 0)
  const canExpand = finished && completedLevel < 3 && Number(run.counters.discovered_papers ?? 0) > 0
  const warningGroups = useMemo(() => {
    const groups = new Map<string, { code: string; message: string; count: number }>()
    run.warnings.forEach((warning) => {
      const code = String(warning.code)
      const key = `${code}\u0000${warning.message}`
      const existing = groups.get(key)
      if (existing) existing.count += 1
      else groups.set(key, { code, message: warning.message, count: 1 })
    })
    return [...groups.values()]
  }, [run.warnings])
  return <main className="progress-page content-width">
    <div className="eyebrow"><LoaderCircle className={finished || failed ? '' : 'spin'} size={15} /> Run {run.id.slice(0, 8)}</div>
    <div className="progress-heading"><div><h1>{failed ? 'Discovery could not start.' : finished ? 'Your literature map is ready.' : paused ? 'Discovery is paused.' : 'Following the citation trail…'}</h1>
      <p>{finished ? 'Review discovered papers, inspect relationships, or export the reproducible dataset.' : 'Progress is checkpointed to disk. You can safely restart the application.'}</p></div>
      <span className={`status-pill ${finished ? 'complete' : paused ? 'paused' : ''}`}>{run.phase.replaceAll('_', ' ')}</span>
    </div>
    <section className="metric-grid">
      <article><Database /><span>Retained papers</span><strong>{papers}</strong><small>500 pause · 1,000 final limit</small></article>
      <article><GitFork /><span>Citation edges</span><strong>{run.counters.citations ?? '—'}</strong><small>within the retained graph</small></article>
      <article><CheckCircle2 /><span>Resolved seeds</span><strong>{run.counters.resolved_seeds ?? '—'}</strong><small>of {run.counters.input_seeds ?? run.config.seeds?.length ?? '—'} supplied</small></article>
      <article><PauseCircle /><span>Provider requests</span><strong>{run.counters.provider_requests ?? 0}</strong><small>of {run.config.collection_budgets?.provider_requests_per_run ?? 1500}</small></article>
    </section>
    {paused && <section className="decision-card"><AlertTriangle /><div><h2>500-paper checkpoint reached</h2><p>Continue toward the final hard limit of 1,000 papers, or stop now and export everything retained. Continuing may increase keyless-provider usage.</p></div><div className="decision-actions"><button className="secondary" onClick={async () => onUpdate(await api.stopRun(run.id))}>Stop & export</button><button className="primary" onClick={async () => onUpdate(await api.continueRun(run.id))}>Continue discovery</button></div></section>}
    {(run.warnings.length > 0 || run.coverage.retrieval_complete === false) && <section className="coverage-card"><h2>Coverage & warnings</h2>
      {run.coverage.retrieval_complete === false && <p className="coverage-state"><AlertTriangle size={17} /> This run is retrieval-incomplete. Results are valid for retained data, but one or more candidate frontiers were capped or unavailable.</p>}
      <ul>{warningGroups.map((warning) => <li key={`${warning.code}-${warning.message}`}><strong>{warning.code.replaceAll('_', ' ')} ({warning.count})</strong><span>{warning.message}</span></li>)}</ul></section>}
    {run.error && <p className="error">{run.error_code && <strong>{run.error_code.replaceAll('_', ' ')}: </strong>}{run.error}</p>}
    {finished && <div className="center-action">
      <button className="primary" onClick={onExplore}>Explore discovered papers</button>
      {canExpand && <>
        <button className="secondary" onClick={async () => onUpdate(await api.expandRun(run.id, autoNext ? 3 : completedLevel + 1))}>Run next level</button>
        <label className="auto-next"><input type="checkbox" checked={autoNext} onChange={(event) => setAutoNext(event.target.checked)} /> Auto-run remaining levels through level 3</label>
      </>}
    </div>}
  </main>
}

