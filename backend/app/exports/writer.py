from __future__ import annotations

import csv
import io
import json
import os
import zipfile
from pathlib import Path

import networkx as nx
from sqlalchemy import select

from ..models import CitationRecord, PaperRecord, RunRecord


PAPER_COLUMNS = [
    "paper_id", "title", "authors", "year", "venue", "abstract", "doi", "url",
    "is_seed", "discovery_depth", "topics", "relevance_scores",
    "provider_citation_count", "internal_in_count", "internal_out_count",
    "classification_status", "provenance",
]
CITATION_COLUMNS = [
    "citing_paper_id", "cited_paper_id", "citation_provenance",
    "retrieval_date", "citation_context",
]


def _safe_cell(value):
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _atomic_text(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _paper_row(paper: PaperRecord) -> dict:
    return {
        "paper_id": paper.canonical_id,
        "title": _safe_cell(paper.title),
        "authors": paper.authors_json,
        "year": paper.year,
        "venue": _safe_cell(paper.venue or ""),
        "abstract": _safe_cell(paper.abstract or ""),
        "doi": paper.doi or "",
        "url": paper.url or "",
        "is_seed": str(paper.is_seed).lower(),
        "discovery_depth": paper.depth,
        "topics": paper.topics_json,
        "relevance_scores": paper.relevance_scores_json,
        "provider_citation_count": paper.provider_citation_count if paper.provider_citation_count is not None else "",
        "internal_in_count": paper.internal_in_count,
        "internal_out_count": paper.internal_out_count,
        "classification_status": paper.classification_status,
        "provenance": paper.provenance_json,
    }


def _citation_row(edge: CitationRecord) -> dict:
    return {
        "citing_paper_id": edge.citing_paper_id,
        "cited_paper_id": edge.cited_paper_id,
        "citation_provenance": edge.provenance_json,
        "retrieval_date": edge.retrieval_date,
        "citation_context": _safe_cell(edge.citation_context or ""),
    }


def _csv_text(columns: list[str], rows: list[dict]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _graph(papers: list[PaperRecord], citations: list[CitationRecord]) -> nx.DiGraph:
    graph = nx.DiGraph()
    for paper in papers:
        graph.add_node(
            paper.canonical_id,
            title=paper.title,
            year=paper.year,
            is_seed=paper.is_seed,
            depth=paper.depth,
            topics=paper.topics_json,
        )
    for edge in citations:
        graph.add_edge(edge.citing_paper_id, edge.cited_paper_id)
    return graph


def export_run(session, run: RunRecord, runs_dir: Path) -> dict[str, str]:
    directory = runs_dir / run.id
    directory.mkdir(parents=True, exist_ok=True)
    papers = session.scalars(
        select(PaperRecord).where(PaperRecord.run_id == run.id).order_by(PaperRecord.canonical_id)
    ).all()
    citations = session.scalars(
        select(CitationRecord).where(CitationRecord.run_id == run.id).order_by(
            CitationRecord.citing_paper_id, CitationRecord.cited_paper_id
        )
    ).all()
    paper_ids = {paper.canonical_id for paper in papers}
    if any(edge.citing_paper_id not in paper_ids or edge.cited_paper_id not in paper_ids for edge in citations):
        raise ValueError("Citation export contains an endpoint absent from papers.csv")

    papers_path = directory / "papers.csv"
    temporary = papers_path.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PAPER_COLUMNS)
        writer.writeheader()
        for paper in papers:
            writer.writerow(_paper_row(paper))
    os.replace(temporary, papers_path)

    citations_path = directory / "citations.csv"
    temporary = citations_path.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CITATION_COLUMNS)
        writer.writeheader()
        for edge in citations:
            writer.writerow(_citation_row(edge))
    os.replace(temporary, citations_path)

    metadata = {
        "run_id": run.id,
        "status": {"phase": run.phase, "outcome": run.outcome},
        "configuration": json.loads(run.config_json),
        "statistics": json.loads(run.counters_json),
        "coverage": json.loads(run.coverage_json),
        "warnings": json.loads(run.warnings_json),
        "exclusions": json.loads(run.exclusions_json),
        "limitations": [
            "Each discovered paper is citation-connected to at least one supplied seed; seed components may be disconnected.",
            "Retrieval completeness does not imply complete scholarly-literature coverage.",
            "Topic similarity scores are heuristic indicators, not probabilities.",
        ],
    }
    metadata_path = directory / "run_metadata.json"
    _atomic_text(metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2))

    graph = _graph(papers, citations)
    graphml_path = directory / "graph.graphml"
    temporary_graph = graphml_path.with_suffix(".graphml.tmp")
    nx.write_graphml(graph, temporary_graph)
    os.replace(temporary_graph, graphml_path)

    return {
        "papers.csv": str(papers_path),
        "citations.csv": str(citations_path),
        "run_metadata.json": str(metadata_path),
        "graph.graphml": str(graphml_path),
    }


def build_subset_archive(
    session,
    run: RunRecord,
    paper_ids: list[str],
    filter_expression: str | None,
    filters: dict,
) -> bytes:
    requested = set(paper_ids)
    papers = session.scalars(
        select(PaperRecord).where(
            PaperRecord.run_id == run.id,
            PaperRecord.canonical_id.in_(requested),
        ).order_by(PaperRecord.canonical_id)
    ).all()
    found = {paper.canonical_id for paper in papers}
    missing = requested - found
    if missing:
        raise ValueError(f"Subset contains {len(missing)} paper IDs outside this run")
    citations = [
        edge for edge in session.scalars(
            select(CitationRecord).where(CitationRecord.run_id == run.id).order_by(
                CitationRecord.citing_paper_id, CitationRecord.cited_paper_id
            )
        ).all()
        if edge.citing_paper_id in found and edge.cited_paper_id in found
    ]
    metadata = {
        "run_id": run.id,
        "export_type": "filtered_subset",
        "filter_expression": filter_expression,
        "filters": filters,
        "statistics": {"papers": len(papers), "citations": len(citations)},
        "coverage": json.loads(run.coverage_json),
        "note": "Only citations whose citing and cited endpoints are both in this subset are included.",
    }
    graphml = "\n".join(nx.generate_graphml(_graph(papers, citations)))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("papers.csv", _csv_text(PAPER_COLUMNS, [_paper_row(paper) for paper in papers]))
        bundle.writestr("citations.csv", _csv_text(CITATION_COLUMNS, [_citation_row(edge) for edge in citations]))
        bundle.writestr("graph.graphml", graphml)
        bundle.writestr("subset_metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
    return archive.getvalue()

