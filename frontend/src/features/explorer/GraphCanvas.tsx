import cytoscape, { Core } from 'cytoscape'
import { Maximize2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { Citation, Paper } from '../../types'
import { buildLayeredPositions } from './graphLayout'

type Props = { papers: Paper[]; citations: Citation[]; selected: string | null; onSelect: (id: string) => void }

export function GraphCanvas({ papers, citations, selected, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const instance = useRef<Core | null>(null)
  const [layoutMode, setLayoutMode] = useState<'layers' | 'force' | 'grid'>('layers')
  useEffect(() => {
    if (!container.current) return
    const ids = new Set(papers.map((paper) => paper.id))
    const visibleCitations = citations.filter((edge) => ids.has(edge.source) && ids.has(edge.target))
    const positioned = buildLayeredPositions(papers, visibleCitations)
    instance.current?.destroy()
    const cy = cytoscape({
      container: container.current,
      elements: [
        ...positioned.map(({ paper, layer, position }) => ({
          data: {
            id: paper.id, label: paper.title, seed: paper.is_seed ? 'yes' : 'no',
            year: paper.year, depth: paper.depth, layer,
          },
          position,
        })),
        ...visibleCitations.map((edge, index) => ({ data: { id: `e${index}`, source: edge.source, target: edge.target } })),
      ],
      style: [
        { selector: 'node', style: { 'background-color': '#70a98d', width: 15, height: 15, label: '', 'border-width': 2, 'border-color': '#f6f2e8' } },
        { selector: 'node[seed = "yes"]', style: { 'background-color': '#e79b67', width: 22, height: 22 } },
        { selector: 'node.hovered, node:selected', style: {
          label: 'data(label)', color: '#f8f5ed', 'font-size': 11, 'font-weight': 600,
          'text-wrap': 'ellipsis', 'text-max-width': '220px', 'text-background-color': '#1b2b24',
          'text-background-opacity': 0.92, 'text-background-padding': '4px',
          'text-valign': 'bottom', 'text-margin-y': 9, 'z-index': 10,
        } },
        { selector: 'node:selected', style: { 'border-width': 5, 'border-color': '#f0c35e', width: 26, height: 26 } },
        { selector: 'node.related', style: { 'border-width': 4, 'border-color': '#b8d5c5' } },
        { selector: 'edge', style: { width: 1, 'line-color': '#688078', 'target-arrow-color': '#688078', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier', opacity: 0.55 } },
        { selector: 'edge.muted', style: { opacity: 0.12 } },
        { selector: 'edge.highlighted', style: { width: 3, opacity: 1, 'line-color': '#f0c35e', 'target-arrow-color': '#f0c35e', 'z-index': 8 } },
      ],
      layout: layoutMode === 'layers'
        ? { name: 'preset', animate: false, padding: 70, fit: true }
        : layoutMode === 'force'
          ? { name: 'cose', animate: false, padding: 42, nodeRepulsion: () => 9000, idealEdgeLength: () => 70 }
          : { name: 'grid', animate: false, padding: 36, avoidOverlap: true },
      minZoom: 0.05,
      maxZoom: 4,
      wheelSensitivity: 0.22,
    })
    cy.on('tap', 'node', (event) => onSelect(event.target.id()))
    cy.on('mouseover', 'node', (event) => event.target.addClass('hovered'))
    cy.on('mouseout', 'node', (event) => event.target.removeClass('hovered'))
    instance.current = cy
    return () => cy.destroy()
  }, [papers, citations, onSelect, layoutMode])
  useEffect(() => {
    const cy = instance.current
    if (!cy) return
    cy.nodes().unselect()
    cy.nodes().removeClass('related')
    cy.edges().removeClass('highlighted muted')
    if (!selected) return
    const node = cy.getElementById(selected)
    if (node.length) {
      node.select()
      cy.edges().addClass('muted')
      let bestDistance = Number.POSITIVE_INFINITY
      let bestPath = cy.collection()
      cy.nodes('[seed = "yes"]').forEach((seed) => {
        const result = cy.elements().aStar({ root: node, goal: seed, directed: false })
        if (result.found && result.distance < bestDistance) {
          bestDistance = result.distance
          bestPath = result.path
        }
      })
      const traceEdges = bestPath.edges().length ? bestPath.edges() : node.connectedEdges()
      traceEdges.removeClass('muted').addClass('highlighted')
      bestPath.nodes().not(node).addClass('related')
      if (!bestPath.edges().length) node.neighborhood('node').addClass('related')
    }
  }, [selected, papers, layoutMode])
  return <><div className="graph-tools" aria-label="Graph layout controls">
    <span>Layout</span>
    <button className={layoutMode === 'layers' ? 'active' : ''} onClick={() => setLayoutMode('layers')}>Citation layers</button>
    <button className={layoutMode === 'force' ? 'active' : ''} onClick={() => setLayoutMode('force')}>Connections</button>
    <button className={layoutMode === 'grid' ? 'active' : ''} onClick={() => setLayoutMode('grid')}>Grid</button>
    <button title="Fit graph to view" aria-label="Fit graph to view" onClick={() => instance.current?.fit(undefined, 36)}><Maximize2 size={14} /></button>
  </div><div className="layer-guide" aria-hidden="true"><span>← Backward references</span><b>Seeds</b><span>Forward citations →</span></div><div className="graph-canvas" ref={container} aria-label="Interactive citation graph" /></>
}

