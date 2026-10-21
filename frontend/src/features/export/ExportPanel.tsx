import { Download, FileJson, Network, Sheet } from 'lucide-react'
import { api } from '../../api/client'
import type { RunSummary } from '../../types'

export function ExportPanel({ run }: { run: RunSummary }) {
  const files = [
    { name: 'papers.csv', icon: Sheet, copy: 'Canonical retained publications and annotations' },
    { name: 'citations.csv', icon: Sheet, copy: 'Directed citation relationships within the retained graph' },
    { name: 'run_metadata.json', icon: FileJson, copy: 'Configuration, provenance, limits, warnings, and coverage' },
    { name: 'graph.graphml', icon: Network, copy: 'Interoperable graph representation' },
  ]
  return <main className="export-page content-width"><div className="eyebrow"><Download size={15} /> Reproducible output</div><h1>Take the discovery trail with you.</h1><p className="lede">The CSV pair is canonical. The explorer can reconstruct this graph from those files without contacting a scholarly provider.</p>
    <section className="export-grid">{files.map(({ name, icon: Icon, copy }) => <a key={name} href={api.exportUrl(run.id, name)} download><Icon /><div><h2>{name}</h2><p>{copy}</p></div><Download size={18} /></a>)}</section>
    <section className="export-summary"><h2>Run summary</h2><dl><div><dt>Status</dt><dd>{run.phase.replaceAll('_', ' ')}</dd></div><div><dt>Papers</dt><dd>{run.counters.papers ?? '—'}</dd></div><div><dt>Citations</dt><dd>{run.counters.citations ?? '—'}</dd></div><div><dt>Coverage</dt><dd>{run.coverage.retrieval_complete === false ? 'Retrieval incomplete' : 'Attempted traversal processed'}</dd></div></dl></section>
  </main>
}

