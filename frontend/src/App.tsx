import { lazy, Suspense, useEffect, useState } from 'react'
import { BookOpenText, Download, Network, Search } from 'lucide-react'
import { api } from './api/client'
import { StudyConfiguration } from './features/configuration/StudyConfiguration'
import { DiscoveryProgress } from './features/discovery/DiscoveryProgress'
import { ExportPanel } from './features/export/ExportPanel'
import type { GraphData, RunSummary } from './types'

type Screen = 'configure' | 'progress' | 'explore' | 'export'
const Explorer = lazy(() => import('./features/explorer/Explorer').then((module) => ({ default: module.Explorer })))

export default function App() {
  const [screen, setScreen] = useState<Screen>('configure')
  const [run, setRun] = useState<RunSummary | null>(null)
  const [graph, setGraph] = useState<GraphData | null>(null)

  useEffect(() => {
    if (!run || !['created','resolving','collecting_frontier','scheduling_frontier','completing_edges','annotating','exporting'].includes(run.phase)) return
    const timer = window.setInterval(async () => {
      try { setRun(await api.getRun(run.id)) } catch { /* retain last durable state */ }
    }, 1500)
    return () => window.clearInterval(timer)
  }, [run?.id, run?.phase])

  async function openExplorer() {
    if (!run) return
    const data = await api.graph(run.id)
    setGraph(data); setRun(data.run); setScreen('explore')
  }

  function created(value: RunSummary) {
    setRun(value)
    if (value.outcome === 'imported_csv') openImported(value)
    else setScreen('progress')
  }
  async function openImported(value: RunSummary) {
    const data = await api.graph(value.id); setGraph(data); setRun(data.run); setScreen('explore')
  }

  return <div className="app-shell">
    <nav className="topbar"><button className="brand" onClick={() => setScreen('configure')}><span><BookOpenText size={20} /></span>Citation Grapher</button>
      <div className="nav-steps"><button className={screen === 'configure' ? 'active' : ''} onClick={() => setScreen('configure')}>01 Configure</button><button disabled={!run} className={screen === 'progress' ? 'active' : ''} onClick={() => setScreen('progress')}>02 Discovery</button><button disabled={!run} className={screen === 'explore' ? 'active' : ''} onClick={openExplorer}><Search size={14} />03 Explore</button><button disabled={!run || !['completed','completed_partial'].includes(run.phase)} className={screen === 'export' ? 'active' : ''} onClick={() => setScreen('export')}><Download size={14} />04 Export</button></div>
      <div className="top-status"><Network size={14} /> {run ? run.phase.replaceAll('_', ' ') : 'Ready'}</div>
    </nav>
    {screen === 'configure' && <StudyConfiguration onCreated={created} />}
    {screen === 'progress' && run && <DiscoveryProgress run={run} onUpdate={setRun} onExplore={openExplorer} />}
    {screen === 'explore' && graph && <Suspense fallback={<main className="content-width"><p>Loading graph explorer…</p></main>}><Explorer data={graph} /></Suspense>}
    {screen === 'export' && run && <ExportPanel run={run} />}
  </div>
}

