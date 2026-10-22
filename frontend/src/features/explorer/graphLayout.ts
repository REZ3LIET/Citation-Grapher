import type { Citation, Paper } from '../../types'

export type PositionedPaper = {
  paper: Paper
  layer: number
  position: { x: number; y: number }
}

function distancesFromSeeds(
  seedIds: string[],
  adjacency: Map<string, string[]>,
): Map<string, number> {
  const distances = new Map(seedIds.map((id) => [id, 0]))
  let frontier = [...seedIds]
  while (frontier.length) {
    const next: string[] = []
    frontier.forEach((id) => {
      const distance = distances.get(id) ?? 0
      ;(adjacency.get(id) ?? []).forEach((neighbor) => {
        if (distances.has(neighbor)) return
        distances.set(neighbor, distance + 1)
        next.push(neighbor)
      })
    })
    frontier = next
  }
  return distances
}

export function assignCitationLayers(papers: Paper[], citations: Citation[]): Map<string, number> {
  const ids = new Set(papers.map((paper) => paper.id))
  const seeds = papers.filter((paper) => paper.is_seed).map((paper) => paper.id)
  const backward = new Map<string, string[]>()
  const forward = new Map<string, string[]>()
  citations.forEach(({ source, target }) => {
    if (!ids.has(source) || !ids.has(target)) return
    backward.set(source, [...(backward.get(source) ?? []), target])
    forward.set(target, [...(forward.get(target) ?? []), source])
  })
  const backwardDistance = distancesFromSeeds(seeds, backward)
  const forwardDistance = distancesFromSeeds(seeds, forward)

  return new Map(papers.map((paper) => {
    if (paper.is_seed) return [paper.id, 0]
    const directions = new Set<string>(paper.provenance?.directions ?? [])
    const magnitude = Math.max(1, paper.depth)
    if (directions.has('backward') && !directions.has('forward')) return [paper.id, -magnitude]
    if (directions.has('forward') && !directions.has('backward')) return [paper.id, magnitude]

    const back = backwardDistance.get(paper.id)
    const ahead = forwardDistance.get(paper.id)
    if (back !== undefined && (ahead === undefined || back <= ahead)) return [paper.id, -magnitude]
    if (ahead !== undefined) return [paper.id, magnitude]
    return [paper.id, 0]
  }))
}

export function buildLayeredPositions(
  papers: Paper[],
  citations: Citation[],
  columnGap = 260,
  rowGap = 58,
): PositionedPaper[] {
  const assigned = assignCitationLayers(papers, citations)
  const columns = new Map<number, Paper[]>()
  papers.forEach((paper) => {
    const layer = assigned.get(paper.id) ?? 0
    columns.set(layer, [...(columns.get(layer) ?? []), paper])
  })

  const positions: PositionedPaper[] = []
  ;[...columns.entries()].sort(([left], [right]) => left - right).forEach(([layer, column]) => {
    column.sort((left, right) => (
      Number(right.is_seed) - Number(left.is_seed)
      || right.year - left.year
      || left.title.localeCompare(right.title)
      || left.id.localeCompare(right.id)
    ))
    const midpoint = (column.length - 1) / 2
    column.forEach((paper, index) => positions.push({
      paper,
      layer,
      position: { x: layer * columnGap, y: (index - midpoint) * rowGap },
    }))
  })
  return positions
}

