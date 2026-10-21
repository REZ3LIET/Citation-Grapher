import { ChevronRight, Search } from 'lucide-react'
import type { Paper } from '../../types'

type Props = { papers: Paper[]; selected: string | null; onSelect: (id: string) => void; minRelevance?: number }

export function DiscoveredPapers({ papers, selected, onSelect, minRelevance = 0 }: Props) {
  return <section className="paper-list" aria-label="Discovered papers">
    <div className="list-heading"><div><p className="step-label">Discovered papers</p><h2>{papers.length} publications</h2></div><Search size={18} /></div>
    <div className="paper-rows">
      {papers.map((paper) => {
        const applicableTopics = Object.entries(paper.relevance_scores)
          .filter(([, score]) => minRelevance === 0 ? score > 0 : score >= minRelevance)
          .sort((a, b) => b[1] - a[1])
        return <button id={`paper-${encodeURIComponent(paper.id)}`} key={paper.id}
          className={`paper-row ${selected === paper.id ? 'selected' : ''}`} onClick={() => onSelect(paper.id)}>
          <div className="paper-year">{paper.year}<span>{paper.is_seed ? 'seed' : `d${paper.depth}`}</span></div>
          <div className="paper-copy"><h3>{paper.title}</h3><p>{paper.authors.slice(0, 3).join(', ') || 'Authors unavailable'}</p>
            <div className="topic-line">{applicableTopics.length ? applicableTopics.map(([topic, score]) => <span key={topic}>{topic} <b>{Math.round(score * 100)}%</b></span>) : <em>Unclassified</em>}</div>
          </div><ChevronRight size={17} />
        </button>
      })}
      {!papers.length && <div className="empty-state">No papers match the current filters.</div>}
    </div>
  </section>
}

