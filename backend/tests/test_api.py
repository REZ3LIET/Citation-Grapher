from fastapi.testclient import TestClient
import csv
import io
import json
import zipfile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.api.routes import expand_run
from app.models import Base, RunRecord
from app.schemas import RunExpand
from app.providers import Work


def test_health_endpoint():
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}


def test_topic_search_returns_bounded_review_candidates(monkeypatch):
    class SearchProvider:
        def __init__(self, *_args, **_kwargs):
            pass
        def close(self):
            pass
        def search(self, query, min_year, max_year, limit, consume):
            consume()
            assert (query, min_year, max_year, limit) == (
                "unlearning AND causal", 2022, 2026, 25,
            )
            return [Work(
                canonical_id="openalex:W1", openalex_id="W1", doi=None, arxiv_id=None,
                title="Found paper", authors=["Ada"], year=2025, venue="Venue",
                abstract="Abstract", url="https://openalex.org/W1", citation_count=4,
            )], {"retrieved": 1, "known_total": 9, "pages": 1, "capped": True,
                  "reason": "topic_search_limit"}
    monkeypatch.setattr("app.api.routes.OpenAlexClient", SearchProvider)
    with TestClient(app) as client:
        response = client.post("/api/topic-search", json={
            "query": "unlearning AND causal", "min_year": 2022, "max_year": 2026,
        })
    assert response.status_code == 200
    body = response.json()
    assert body["papers"][0]["openalex_id"] == "W1"
    assert body["coverage"]["retrieval_complete"] is False
    assert body["coverage"]["provider_requests"] == 1


def test_csv_pair_import_reconstructs_graph_without_provider_calls():
    papers = """paper_id,title,authors,year,venue,abstract,doi,url,is_seed,discovery_depth,topics,relevance_scores,provider_citation_count,internal_in_count,internal_out_count,classification_status,provenance
p1,Seed,"[""Ada""]",2024,,,,,true,0,"[""graphs""]","{""graphs"":0.8}",,1,0,classified,{}
p2,Found,"[""Ben""]",2025,,,,,false,1,"[""graphs""]","{""graphs"":0.7}",,0,1,classified,{}
"""
    citations = """citing_paper_id,cited_paper_id,citation_provenance,retrieval_date,citation_context
p2,p1,{},2026-10-20,
"""
    with TestClient(app) as client:
        response = client.post("/api/import", files={
            "papers_file": ("papers.csv", papers, "text/csv"),
            "citations_file": ("citations.csv", citations, "text/csv"),
        })
        assert response.status_code == 201, response.text
        run = response.json()
        graph = client.get(f"/api/runs/{run['id']}/graph").json()
        subset_response = client.post(f"/api/runs/{run['id']}/exports/subset", json={
            "paper_ids": ["p1"],
            "filter_expression": "graphs AND causal",
            "filters": {"min_year": 2024},
        })
    assert len(graph["papers"]) == 2
    assert graph["citations"] == [{"source": "p2", "target": "p1", "provenance": {}}]
    assert subset_response.status_code == 200
    assert subset_response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(subset_response.content)) as bundle:
        subset_papers = list(csv.DictReader(io.StringIO(bundle.read("papers.csv").decode())))
        subset_edges = list(csv.DictReader(io.StringIO(bundle.read("citations.csv").decode())))
    assert [row["paper_id"] for row in subset_papers] == ["p1"]
    assert subset_edges == []


def test_completed_level_can_resume_in_place(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    enqueued = []
    monkeypatch.setattr("app.api.routes.runner.enqueue", enqueued.append)
    with sessions() as session:
        session.add(RunRecord(
            id="expandable", phase="completed_partial", outcome="provider_retrieval_incomplete",
            config_json=json.dumps({"seeds": ["one", "two"], "depth": 1}),
            counters_json="{}", warnings_json="[]", exclusions_json="[]",
            coverage_json='{"highest_completed_level":1}',
            checkpoint_json=json.dumps({
                "depth": 1, "highest_completed_level": 1, "stage": "collecting",
                "frontier": ["paper-a"],
            }),
        ))
        session.commit()
        result = expand_run("expandable", RunExpand(target_level=2), session)
        run = session.get(RunRecord, "expandable")
        assert result.phase == "collecting_frontier"
        assert run.outcome is None
        assert json.loads(run.config_json)["depth"] == 2
    assert enqueued == ["expandable"]

