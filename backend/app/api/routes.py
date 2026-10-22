from __future__ import annotations

import csv
import io
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.database import get_db
from ..core.runner import dumps, loads, runner
from ..exports import build_subset_archive, export_run
from ..models import CitationRecord, PaperRecord, RunRecord
from ..providers import OpenAlexClient, ProviderBudgetExceeded, ProviderRateLimited
from ..providers.grobid import identify_pdf
from ..providers.arxiv import search_arxiv
from ..schemas import (
    CitationView, GraphView, PaperView, RunCreate, RunExpand, RunSummary, SubsetExportRequest,
    TopicSearchPaper, TopicSearchRequest, TopicSearchResponse,
)


router = APIRouter(prefix="/api")
settings = get_settings()
ALLOWED_EXPORTS = {"papers.csv", "citations.csv", "run_metadata.json", "graph.graphml"}


def summarize(run: RunRecord) -> RunSummary:
    return RunSummary(
        id=run.id,
        phase=run.phase,
        outcome=run.outcome,
        config=loads(run.config_json, {}),
        counters=loads(run.counters_json, {}),
        warnings=loads(run.warnings_json, []),
        exclusions=loads(run.exclusions_json, []),
        coverage=loads(run.coverage_json, {}),
        error_code=run.outcome if run.phase == "failed" else None,
        error=run.error,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def get_run_or_404(run_id: str, db: Session) -> RunRecord:
    run = db.get(RunRecord, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/topic-search", response_model=TopicSearchResponse)
def topic_search(payload: TopicSearchRequest) -> TopicSearchResponse:
    requests_used = 0

    def consume_request() -> None:
        nonlocal requests_used
        if requests_used >= settings.max_topic_search_requests:
            raise ProviderBudgetExceeded("Topic-search request budget reached")
        requests_used += 1

    provider = OpenAlexClient(
        settings.openalex_base_url,
        settings.request_timeout_seconds,
        max_retries=settings.provider_max_retries,
        retry_base_seconds=settings.provider_retry_base_seconds,
        retry_max_seconds=settings.provider_retry_max_seconds,
    )
    fallback_reason = None
    try:
        works, report = provider.search(
            payload.query, payload.min_year, payload.max_year, payload.limit, consume_request,
        )
    except ProviderBudgetExceeded as exc:
        raise HTTPException(429, str(exc)) from exc
    except ProviderRateLimited as exc:
        fallback_reason = "openalex_daily_budget" if exc.daily_budget_exhausted else "openalex_rate_limited"
        try:
            works, report = search_arxiv(
                payload.query, payload.min_year, payload.max_year, payload.limit,
                consume_request, settings.request_timeout_seconds,
            )
        except Exception as fallback_exc:
            detail = "Keyless OpenAlex search is temporarily unavailable and the arXiv fallback failed."
            if exc.retry_after_seconds:
                detail += f" OpenAlex retry window: approximately {int(exc.retry_after_seconds)} seconds."
            raise HTTPException(503, f"{detail} arXiv: {type(fallback_exc).__name__}: {fallback_exc}") from fallback_exc
    except Exception as exc:
        raise HTTPException(503, f"Topic search provider unavailable: {type(exc).__name__}: {exc}") from exc
    finally:
        provider.close()
    report.update({
        "provider": "arxiv" if fallback_reason else "openalex",
        "provider_requests": requests_used,
        "retrieval_complete": not report.get("capped", False),
        "limit": payload.limit,
        "fallback_reason": fallback_reason,
    })
    return TopicSearchResponse(
        query=payload.query,
        papers=[TopicSearchPaper(
            id=work.canonical_id, openalex_id=work.openalex_id, doi=work.doi,
            title=work.title, authors=work.authors, year=work.year,
            venue=work.venue, abstract=work.abstract, url=work.url,
            citation_count=work.citation_count,
        ) for work in works if work.year is not None],
        coverage=report,
    )


@router.post("/seed-pdfs/identify")
async def identify_seed_pdf(file: UploadFile = File(...)) -> dict:
    if file.content_type != "application/pdf" and not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "A PDF file is required")
    content = await file.read(25_000_001)
    if len(content) > 25_000_000:
        raise HTTPException(413, "PDF must be no larger than 25 MB")
    if not content.startswith(b"%PDF"):
        raise HTTPException(400, "File does not have a valid PDF signature")
    try:
        return identify_pdf(content, settings.grobid_base_url)
    except Exception as exc:
        raise HTTPException(503, f"Local PDF metadata extraction is unavailable: {exc}") from exc


@router.post("/runs", response_model=RunSummary, status_code=201)
def create_run(payload: RunCreate, db: Session = Depends(get_db)) -> RunSummary:
    run_id = str(uuid.uuid4())
    config = payload.model_dump()
    config["collection_budgets"] = {
        "pages_per_query": settings.max_pages_per_query,
        "candidates_per_parent_direction": settings.max_candidates_per_parent_direction,
        "pending_candidates_per_depth": settings.max_pending_candidates_per_depth,
        "provider_requests_per_run": settings.max_provider_requests_per_run,
    }
    run = RunRecord(
        id=run_id,
        phase="created",
        config_json=dumps(config),
        counters_json=dumps({"provider_requests": 0}),
        warnings_json="[]",
        exclusions_json="[]",
        checkpoint_json="{}",
        coverage_json=dumps({
            "retrieval_complete": True,
            "literature_coverage_complete": False,
            "collection_budgets": config["collection_budgets"],
        }),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    runner.enqueue(run_id)
    return summarize(run)


@router.get("/runs", response_model=list[RunSummary])
def list_runs(db: Session = Depends(get_db)) -> list[RunSummary]:
    records = db.scalars(select(RunRecord).order_by(RunRecord.created_at.desc())).all()
    return [summarize(run) for run in records]


@router.get("/runs/{run_id}", response_model=RunSummary)
def get_run(run_id: str, db: Session = Depends(get_db)) -> RunSummary:
    return summarize(get_run_or_404(run_id, db))


@router.post("/runs/{run_id}/continue", response_model=RunSummary)
def continue_run(run_id: str, db: Session = Depends(get_db)) -> RunSummary:
    run = get_run_or_404(run_id, db)
    if run.phase != "awaiting_continue":
        raise HTTPException(409, "Run is not waiting for confirmation")
    checkpoint = loads(run.checkpoint_json, {})
    checkpoint["warning_acknowledged"] = True
    run.checkpoint_json = dumps(checkpoint)
    run.phase = checkpoint.get("stage") == "collecting" and "collecting_frontier" or "scheduling_frontier"
    db.commit()
    db.refresh(run)
    runner.enqueue(run_id)
    return summarize(run)


@router.post("/runs/{run_id}/expand", response_model=RunSummary)
def expand_run(run_id: str, payload: RunExpand, db: Session = Depends(get_db)) -> RunSummary:
    run = get_run_or_404(run_id, db)
    if run.phase not in {"completed", "completed_partial"}:
        raise HTTPException(409, "Run must finish its current level before expansion")
    config = loads(run.config_json, {})
    checkpoint = loads(run.checkpoint_json, {})
    if not config.get("seeds"):
        raise HTTPException(409, "Imported graphs cannot be expanded")
    completed_level = int(checkpoint.get("highest_completed_level", checkpoint.get("depth", 0)))
    if payload.target_level <= completed_level:
        raise HTTPException(409, f"Level {completed_level} is already complete")
    if checkpoint.get("stage") != "collecting" or checkpoint.get("force_finalize"):
        raise HTTPException(409, "This partial run stopped before a complete level boundary")
    if not checkpoint.get("frontier"):
        raise HTTPException(409, "The completed level has no papers to expand")
    config["depth"] = payload.target_level
    run.config_json = dumps(config)
    run.phase = "collecting_frontier"
    run.outcome = None
    run.error = None
    run.stop_requested = False
    db.commit()
    db.refresh(run)
    runner.enqueue(run_id)
    return summarize(run)


@router.post("/runs/{run_id}/stop", response_model=RunSummary)
def stop_run(run_id: str, db: Session = Depends(get_db)) -> RunSummary:
    run = get_run_or_404(run_id, db)
    if run.phase in {"completed", "completed_partial", "failed"}:
        raise HTTPException(409, "Run has already finished")
    run.stop_requested = True
    if run.phase == "awaiting_continue":
        run.phase = "scheduling_frontier"
    db.commit()
    db.refresh(run)
    runner.enqueue(run_id)
    return summarize(run)


@router.get("/runs/{run_id}/graph", response_model=GraphView)
def get_graph(run_id: str, db: Session = Depends(get_db)) -> GraphView:
    run = get_run_or_404(run_id, db)
    papers = db.scalars(
        select(PaperRecord).where(PaperRecord.run_id == run_id).order_by(
            PaperRecord.year.desc(), PaperRecord.title
        )
    ).all()
    citations = db.scalars(select(CitationRecord).where(CitationRecord.run_id == run_id)).all()
    return GraphView(
        run=summarize(run),
        papers=[PaperView(
            id=paper.canonical_id, title=paper.title, authors=loads(paper.authors_json, []),
            year=paper.year, venue=paper.venue, abstract=paper.abstract, doi=paper.doi,
            url=paper.url, is_seed=paper.is_seed, depth=paper.depth,
            provider_citation_count=paper.provider_citation_count,
            internal_in_count=paper.internal_in_count, internal_out_count=paper.internal_out_count,
            topics=loads(paper.topics_json, []),
            relevance_scores=loads(paper.relevance_scores_json, {}),
            classification_status=paper.classification_status,
            provenance=loads(paper.provenance_json, {}),
        ) for paper in papers],
        citations=[CitationView(
            source=edge.citing_paper_id, target=edge.cited_paper_id,
            provenance=loads(edge.provenance_json, {}),
        ) for edge in citations],
    )


@router.get("/runs/{run_id}/exports/{filename}")
def download_export(run_id: str, filename: str, db: Session = Depends(get_db)):
    get_run_or_404(run_id, db)
    if filename not in ALLOWED_EXPORTS:
        raise HTTPException(404, "Unknown export")
    path = (settings.runs_dir / run_id / filename).resolve()
    expected_parent = (settings.runs_dir / run_id).resolve()
    if path.parent != expected_parent or not path.is_file():
        raise HTTPException(404, "Export is not available")
    return FileResponse(path, filename=filename)


@router.post("/runs/{run_id}/exports/subset")
def download_subset_export(run_id: str, payload: SubsetExportRequest, db: Session = Depends(get_db)):
    run = get_run_or_404(run_id, db)
    try:
        archive = build_subset_archive(
            db, run, payload.paper_ids, payload.filter_expression, payload.filters,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return Response(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="citation-subset-{run_id[:8]}.zip"'},
    )


def _parse_json_cell(value: str, expected):
    try:
        parsed = json.loads(value or ("[]" if expected is list else "{}"))
        return parsed if isinstance(parsed, expected) else expected()
    except json.JSONDecodeError:
        return expected()


@router.post("/import", response_model=RunSummary, status_code=201)
async def import_csv_pair(
    papers_file: UploadFile = File(...),
    citations_file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> RunSummary:
    if papers_file.filename != "papers.csv" or citations_file.filename != "citations.csv":
        raise HTTPException(400, "Upload files named papers.csv and citations.csv")
    papers_bytes = await papers_file.read(10_000_001)
    citations_bytes = await citations_file.read(10_000_001)
    if len(papers_bytes) > 10_000_000 or len(citations_bytes) > 10_000_000:
        raise HTTPException(413, "Each CSV must be no larger than 10 MB")
    try:
        paper_rows = list(csv.DictReader(io.StringIO(papers_bytes.decode("utf-8-sig"))))
        citation_rows = list(csv.DictReader(io.StringIO(citations_bytes.decode("utf-8-sig"))))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise HTTPException(400, f"Invalid CSV: {exc}") from exc
    required_papers = {"paper_id", "title", "authors", "year", "is_seed", "discovery_depth"}
    required_edges = {"citing_paper_id", "cited_paper_id"}
    if not paper_rows or not required_papers.issubset(paper_rows[0]):
        raise HTTPException(400, "papers.csv is missing canonical columns")
    if citation_rows and not required_edges.issubset(citation_rows[0]):
        raise HTTPException(400, "citations.csv is missing canonical columns")
    run = RunRecord(
        id=str(uuid.uuid4()), phase="completed", outcome="imported_csv",
        config_json=dumps({"source": "csv_import", "topics": []}),
        counters_json="{}", warnings_json="[]", exclusions_json="[]", checkpoint_json="{}",
        coverage_json=dumps({"retrieval_complete": None, "literature_coverage_complete": False,
                             "source": "canonical_csv_import"}),
    )
    db.add(run)
    db.flush()
    ids: set[str] = set()
    for row in paper_rows:
        paper_id = row["paper_id"].strip()
        if not paper_id or paper_id in ids:
            raise HTTPException(400, f"Duplicate or blank paper ID: {paper_id!r}")
        ids.add(paper_id)
        try:
            year = int(row["year"])
            depth = int(row["discovery_depth"])
        except ValueError as exc:
            raise HTTPException(400, f"Invalid numeric paper field for {paper_id}") from exc
        db.add(PaperRecord(
            run_id=run.id, canonical_id=paper_id, title=row["title"],
            authors_json=dumps(_parse_json_cell(row.get("authors", ""), list)), year=year,
            venue=row.get("venue") or None, abstract=row.get("abstract") or None,
            doi=row.get("doi") or None, url=row.get("url") or None,
            is_seed=row["is_seed"].lower() == "true", depth=depth,
            provider_citation_count=int(row["provider_citation_count"]) if row.get("provider_citation_count") else None,
            internal_in_count=int(row.get("internal_in_count") or 0),
            internal_out_count=int(row.get("internal_out_count") or 0),
            topics_json=dumps(_parse_json_cell(row.get("topics", ""), list)),
            relevance_scores_json=dumps(_parse_json_cell(row.get("relevance_scores", ""), dict)),
            classification_status=row.get("classification_status") or "unknown",
            provenance_json=dumps(_parse_json_cell(row.get("provenance", ""), dict)),
        ))
    seen_edges: set[tuple[str, str]] = set()
    for row in citation_rows:
        edge = row["citing_paper_id"].strip(), row["cited_paper_id"].strip()
        if edge in seen_edges or not set(edge).issubset(ids):
            raise HTTPException(400, f"Invalid or duplicate citation edge: {edge}")
        seen_edges.add(edge)
        db.add(CitationRecord(
            run_id=run.id, citing_paper_id=edge[0], cited_paper_id=edge[1],
            provenance_json=dumps(_parse_json_cell(row.get("citation_provenance", ""), dict)),
            retrieval_date=row.get("retrieval_date") or "unknown",
            citation_context=row.get("citation_context") or None,
        ))
    run.counters_json = dumps({"papers": len(ids), "citations": len(seen_edges),
                               "discovered_papers": sum(row["is_seed"].lower() != "true" for row in paper_rows)})
    db.commit()
    db.refresh(run)
    export_run(db, run, settings.runs_dir)
    return summarize(run)

