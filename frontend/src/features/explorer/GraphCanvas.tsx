import cytoscape, { Core } from 'cytoscape'
import { Maximize2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { Citation, Paper } from '../../types'

type Props = { papers: Paper[]; citations: Citation[]; selected: string | null; onSelect: (id: string) => void }

export function GraphCanvas({ papers, citations, selected, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const instance = useRef<Core | null>(null)
  const [layoutMode, setLayoutMode] = useState<'levels' | 'force' | 'grid'>('levels')
  useEffect(() => {
    if (!container.current) return
    const ids = new Set(papers.map((paper) => paper.id))
    const maxDepth = Math.max(0, ...papers.map((paper) => paper.depth))
    instance.current?.destroy()
    const cy = cytoscape({
      container: container.current,
      elements: [
        ...papers.map((paper) => ({ data: { id: paper.id, label: paper.title, seed: paper.is_seed ? 'yes' : 'no', year: paper.year, depth: paper.depth } })),
        ...citations.filter((edge) => ids.has(edge.source) && ids.has(edge.target)).map((edge, index) => ({ data: { id: `e${index}`, source: edge.source, target: edge.target } })),
      ],
      style: [
        { selector: 'node', style: { 'background-color': '#70a98d', width: 14, height: 14, label: '', 'border-width': 2, 'border-color': '#f6f2e8' } },
        { selector: 'node[seed = "yes"]', style: { 'background-color': '#e79b67', width: 22, height: 22 } },
        { selector: 'node:selected', style: { 'border-width': 5, 'border-color': '#f0c35e', width: 26, height: 26 } },
        { selector: 'edge', style: { width: 1, 'line-color': '#688078', 'target-arrow-color': '#688078', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier', opacity: 0.55 } },
      ],
      layout: layoutMode === 'levels'
        ? { name: 'concentric', animate: false, padding: 52, avoidOverlap: true, minNodeSpacing: 24, concentric: (node) => maxDepth - Number(node.data('depth')), levelWidth: () => 1 }
        : layoutMode === 'force'
          ? { name: 'cose', animate: false, padding: 42, nodeRepulsion: () => 9000, idealEdgeLength: () => 70 }
          : { name: 'grid', animate: false, padding: 36, avoidOverlap: true },
    })
    cy.on('tap', 'node', (event) => onSelect(event.target.id()))
    instance.current = cy
    return () => cy.destroy()
  }, [papers, citations, onSelect, layoutMode])
  useEffect(() => {
    const cy = instance.current
    if (!cy || !selected) return
    cy.nodes().unselect()
    const node = cy.getElementById(selected)
    if (node.length) { node.select(); cy.animate({ center: { eles: node }, duration: 250 }) }
  }, [selected, papers, layoutMode])
  return <><div className="graph-tools" aria-label="Graph layout controls">
    <span>Layout</span>
    <button className={layoutMode === 'levels' ? 'active' : ''} onClick={() => setLayoutMode('levels')}>Levels</button>
    <button className={layoutMode === 'force' ? 'active' : ''} onClick={() => setLayoutMode('force')}>Connections</button>
    <button className={layoutMode === 'grid' ? 'active' : ''} onClick={() => setLayoutMode('grid')}>Grid</button>
    <button title="Fit graph to view" aria-label="Fit graph to view" onClick={() => instance.current?.fit(undefined, 36)}><Maximize2 size={14} /></button>
  </div><div className="graph-canvas" ref={container} aria-label="Interactive citation graph" /></>
}

