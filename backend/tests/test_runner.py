import json

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.core.runner as runner_module
from app.core.config import Settings
from app.core.runner import DiscoveryRunner
from app.models import Base, PaperRecord, RunRecord
from app.providers import ProviderRateLimited, Work


def make_work(identifier: str, year: int = 2024) -> Work:
    return Work(
        canonical_id=f"openalex:{identifier}", openalex_id=identifier, doi=None, arxiv_id=None,
        title=f"Paper {identifier}", authors=["Researcher"], year=year, venue="Venue",
        abstract="citation connected literature discovery", url=f"https://openalex.org/{identifier}",
        citation_count=1, referenced_works=[], raw={"id": f"https://openalex.org/{identifier}", "referenced_works": []},
    )


class FakeProvider:
    def __init__(self, *_args, **_kwargs):
        pass

    def close(self):
        pass

    def resolve(self, value, consume):
        consume()
        return make_work("S1" if value == "seed one" else "S2")

    def backward(self, work, _limit, consume):
        consume()
        child = make_work("C1" if work.openalex_id == "S1" else "C2", 2025)
        return [child], {"retrieved": 1, "known_total": 1, "capped": False, "reason": None}

    def forward(self, *_args, **_kwargs):
        raise AssertionError("forward should not be called")


class DisconnectedRegressionProvider:
    def __init__(self, *_args, **_kwargs):
        pass

    def close(self):
        pass

    def resolve(self, value, consume):
        consume()
        if value == "https://aclanthology.org/2025.semeval-1.308/":
            work = make_work("W4417091017", 2025)
            work.canonical_id = "doi:10.48550/arxiv.2504.12996"
            work.doi = "10.48550/arxiv.2504.12996"
            work.title = "SHA256 at SemEval-2025 Task 4: Selective Amnesia -- Constrained Unlearning for Large Language Models via Knowledge Isolation"
            work.authors = ["Saransh Agrawal", "Kuan-Hao Huang"]
            work.citation_count = 0
            work.resolution_method = "conservative_title_author_match:acl_to_openalex"
            return work
        work = make_work("W7154940247", 2026)
        work.canonical_id = "doi:10.48550/arxiv.2604.15847"
        work.doi = "10.48550/arxiv.2604.15847"
        work.title = "CiPO: Counterfactual Unlearning for Large Reasoning Models through Iterative Preference Optimization"
        work.authors = ["Junyi Li", "Yongqiang Chen", "Ningning Ding"]
        work.citation_count = 0
        work.resolution_method = "provider_identifier:arxiv_doi"
        return work

    def backward(self, _work, _limit, _consume):
        return [], {"retrieved": 0, "known_total": 0, "capped": False, "reason": None}

    def forward(self, _work, _min_year, _max_year, _max_pages, _candidate_limit, consume):
        consume()
        return [], {"retrieved": 0, "known_total": 0, "pages": 1, "capped": False, "reason": None}


class IncompleteCitationProvider(DisconnectedRegressionProvider):
    def forward(self, _work, _min_year, _max_year, _max_pages, _candidate_limit, consume):
        consume()
        raise RuntimeError("provider temporarily unavailable")


class PartlyUnresolvedProvider:
    def __init__(self, *_args, **_kwargs):
        pass

    def close(self):
        pass

    def resolve(self, value, consume):
        consume()
        return make_work("ONLY", 2025) if value == "valid seed" else None


class LevelProvider(FakeProvider):
    def backward(self, work, _limit, consume):
        consume()
        children = {"S1": "A1", "S2": "A2", "A1": "B1", "A2": "B2"}
        identifier = children.get(work.openalex_id)
        found = [make_work(identifier, 2025)] if identifier else []
        return found, {
            "retrieved": len(found), "known_total": len(found),
            "capped": False, "reason": None,
        }


class OrderingProvider(FakeProvider):
    calls = []

    def forward(self, work, _min_year, _max_year, _max_pages, _candidate_limit, consume):
        consume()
        self.calls.append(f"forward:{work.openalex_id}")
        return [], {"retrieved": 0, "known_total": 0, "capped": False, "reason": None}

    def backward(self, work, _limit, consume):
        consume()
        self.calls.append(f"backward:{work.openalex_id}")
        return [], {"retrieved": 0, "known_total": 0, "capped": False, "reason": None}


class RateLimitedSeedProvider(OrderingProvider):
    def resolve(self, _value, consume):
        consume()
        raise ProviderRateLimited(3600, daily_budget_exhausted=True)


def test_rate_limited_seed_resolution_uses_arxiv_fallback(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(runner_module, "SessionLocal", sessions)
    monkeypatch.setattr(runner_module, "OpenAlexClient", RateLimitedSeedProvider)
    monkeypatch.setattr(runner_module, "resolve_arxiv", lambda _seed, consume: (
        consume() or {"arxiv_id": "2501.12345", "title": "Fallback paper",
                      "authors": ["Ada"], "year": 2025, "abstract": "Abstract",
                      "url": "https://arxiv.org/abs/2501.12345"}
    ))
    settings = Settings(database_url="sqlite://", runs_dir=tmp_path, max_provider_requests_per_run=20)
    config = {"seeds": ["https://arxiv.org/abs/2501.12345"], "topics": ["unlearning"],
              "min_year": 2022, "max_year": 2026, "direction": "backward", "depth": 1}
    with sessions() as session:
        session.add(RunRecord(
            id="rate-limited-seed", phase="created", config_json=json.dumps(config),
            counters_json='{"provider_requests":0}', warnings_json="[]", exclusions_json="[]",
            checkpoint_json="{}", coverage_json='{"retrieval_complete":true}',
        ))
        session.commit()
    DiscoveryRunner(settings)._execute("rate-limited-seed")
    with sessions() as session:
        run = session.get(RunRecord, "rate-limited-seed")
        assert json.loads(run.counters_json)["resolved_seeds"] == 1
        assert any(item["code"] == "provider_daily_budget" for item in json.loads(run.warnings_json))

def test_one_seed_runs_bfs_and_forward_is_scheduled_first(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(runner_module, "SessionLocal", sessions)
    monkeypatch.setattr(runner_module, "OpenAlexClient", OrderingProvider)
    OrderingProvider.calls = []
    settings = Settings(database_url="sqlite://", runs_dir=tmp_path, max_provider_requests_per_run=20)
    config = {
        "seeds": ["seed one"], "topics": ["unlearning"],
        "min_year": 2022, "max_year": 2026, "direction": "both", "depth": 1,
    }
    with sessions() as session:
        session.add(RunRecord(
            id="one-seed", phase="created", config_json=json.dumps(config),
            counters_json='{"provider_requests":0}', warnings_json="[]", exclusions_json="[]",
            checkpoint_json="{}", coverage_json='{"retrieval_complete":true}',
        ))
        session.commit()

    DiscoveryRunner(settings)._execute("one-seed")

    with sessions() as session:
        run = session.get(RunRecord, "one-seed")
        assert run.phase == "completed"
        assert json.loads(run.counters_json)["resolved_seeds"] == 1
    assert OrderingProvider.calls == ["forward:S1", "backward:S1"]


def test_exact_pause_survives_resume_and_hard_limit_finalizes(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(runner_module, "SessionLocal", sessions)
    monkeypatch.setattr(runner_module, "OpenAlexClient", FakeProvider)
    settings = Settings(
        database_url="sqlite://", runs_dir=tmp_path, paper_warning_threshold=3,
        paper_hard_limit=4, max_provider_requests_per_run=20,
    )
    config = {"seeds": ["seed one", "seed two"], "topics": ["literature discovery"],
              "min_year": 2020, "max_year": 2026, "direction": "backward", "depth": 1}
    with sessions() as session:
        session.add(RunRecord(
            id="durable-run", phase="created", config_json=json.dumps(config),
            counters_json='{"provider_requests":0}', warnings_json="[]", exclusions_json="[]",
            checkpoint_json="{}", coverage_json='{"retrieval_complete":true}',
        ))
        session.commit()

    first_process = DiscoveryRunner(settings)
    first_process._execute("durable-run")
    with sessions() as session:
        run = session.get(RunRecord, "durable-run")
        assert run.phase == "awaiting_continue"
        assert session.scalar(select(func.count(PaperRecord.id))) == 3
        checkpoint = json.loads(run.checkpoint_json)
        assert checkpoint["schedule_index"] == 1
        checkpoint["warning_acknowledged"] = True
        run.checkpoint_json = json.dumps(checkpoint)
        run.phase = "scheduling_frontier"
        session.commit()

    restarted_process = DiscoveryRunner(settings)
    restarted_process._execute("durable-run")
    with sessions() as session:
        run = session.get(RunRecord, "durable-run")
        assert run.phase == "completed_partial"
        assert run.outcome == "partial_limit_reached"
        assert session.scalar(select(func.count(PaperRecord.id))) == 4
    assert (tmp_path / "durable-run" / "papers.csv").is_file()
    assert (tmp_path / "durable-run" / "run_metadata.json").is_file()


def test_exact_reported_seeds_succeed_as_disconnected_components(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(runner_module, "SessionLocal", sessions)
    monkeypatch.setattr(runner_module, "OpenAlexClient", DisconnectedRegressionProvider)
    settings = Settings(database_url="sqlite://", runs_dir=tmp_path, max_provider_requests_per_run=20)
    config = {
        "seeds": [
            "https://aclanthology.org/2025.semeval-1.308/",
            "https://arxiv.org/abs/2604.15847",
        ],
        "topics": ["unlearning", "causal", "counterfactual"],
        "min_year": 2022, "max_year": 2026, "direction": "both", "depth": 1,
    }
    with sessions() as session:
        session.add(RunRecord(
            id="disconnected-seeds", phase="created", config_json=json.dumps(config),
            counters_json='{"provider_requests":0}', warnings_json="[]", exclusions_json="[]",
            checkpoint_json="{}", coverage_json='{"retrieval_complete":true}',
        ))
        session.commit()

    DiscoveryRunner(settings)._execute("disconnected-seeds")

    with sessions() as session:
        run = session.get(RunRecord, "disconnected-seeds")
        papers = session.scalars(select(PaperRecord).where(PaperRecord.run_id == run.id)).all()
        diagnostics = json.loads(run.coverage_json)["seed_diagnostics"]
        assert run.phase == "completed"
        assert run.outcome == "no_citation_candidates"
        assert {paper.canonical_id for paper in papers} == {
            "doi:10.48550/arxiv.2504.12996", "doi:10.48550/arxiv.2604.15847",
        }
        assert all(paper.is_seed for paper in papers)
        assert [item["publication_year"] for item in diagnostics] == [2025, 2026]
        assert all(item["candidates_retrieved"] == 0 for item in diagnostics)
        assert all(item["excluded_by_year"] == 0 for item in diagnostics)
        assert json.loads(run.coverage_json)["highest_completed_level"] == 1
    assert (tmp_path / "disconnected-seeds" / "papers.csv").is_file()
    assert (tmp_path / "disconnected-seeds" / "citations.csv").is_file()


def test_provider_retrieval_failure_preserves_resolved_seeds_and_exports(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(runner_module, "SessionLocal", sessions)
    monkeypatch.setattr(runner_module, "OpenAlexClient", IncompleteCitationProvider)
    settings = Settings(database_url="sqlite://", runs_dir=tmp_path, max_provider_requests_per_run=20)
    config = {
        "seeds": [
            "https://aclanthology.org/2025.semeval-1.308/",
            "https://arxiv.org/abs/2604.15847",
        ],
        "topics": ["unlearning", "causal", "counterfactual"],
        "min_year": 2022, "max_year": 2026, "direction": "forward", "depth": 1,
    }
    with sessions() as session:
        session.add(RunRecord(
            id="incomplete-provider", phase="created", config_json=json.dumps(config),
            counters_json='{"provider_requests":0}', warnings_json="[]", exclusions_json="[]",
            checkpoint_json="{}", coverage_json='{"retrieval_complete":true}',
        ))
        session.commit()

    DiscoveryRunner(settings)._execute("incomplete-provider")

    with sessions() as session:
        run = session.get(RunRecord, "incomplete-provider")
        papers = session.scalars(select(PaperRecord).where(PaperRecord.run_id == run.id)).all()
        assert run.phase == "completed_partial"
        assert run.outcome == "provider_retrieval_incomplete"
        assert len(papers) == 2
        assert all(paper.is_seed for paper in papers)
    assert (tmp_path / "incomplete-provider" / "papers.csv").is_file()


def test_seed_resolution_failure_is_distinct_from_insufficient_resolved_seeds(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(runner_module, "SessionLocal", sessions)
    monkeypatch.setattr(runner_module, "OpenAlexClient", PartlyUnresolvedProvider)
    settings = Settings(database_url="sqlite://", runs_dir=tmp_path, max_provider_requests_per_run=20)
    config = {
        "seeds": ["unresolved seed"], "topics": ["unlearning"],
        "min_year": 2022, "max_year": 2026, "direction": "both", "depth": 1,
    }
    with sessions() as session:
        session.add(RunRecord(
            id="bad-seeds", phase="created", config_json=json.dumps(config),
            counters_json='{"provider_requests":0}', warnings_json="[]", exclusions_json="[]",
            checkpoint_json="{}", coverage_json='{"retrieval_complete":true}',
        ))
        session.commit()

    DiscoveryRunner(settings)._execute_guarded("bad-seeds")

    with sessions() as session:
        run = session.get(RunRecord, "bad-seeds")
        diagnostics = json.loads(run.coverage_json)["seed_diagnostics"]
        exclusions = json.loads(run.exclusions_json)
        assert run.phase == "failed"
        assert run.outcome == "insufficient_resolved_seeds"
        assert diagnostics[0]["status"] == "seed_resolution_failure"
        assert exclusions[0]["reason"] == "seed_resolution_failure"


def test_requested_levels_are_completed_and_checkpointed_sequentially(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(runner_module, "SessionLocal", sessions)
    monkeypatch.setattr(runner_module, "OpenAlexClient", LevelProvider)
    settings = Settings(database_url="sqlite://", runs_dir=tmp_path, max_provider_requests_per_run=20)
    config = {
        "seeds": ["seed one", "seed two"], "topics": ["unlearning"],
        "min_year": 2022, "max_year": 2026, "direction": "backward", "depth": 2,
    }
    with sessions() as session:
        session.add(RunRecord(
            id="level-run", phase="created", config_json=json.dumps(config),
            counters_json='{"provider_requests":0}', warnings_json="[]", exclusions_json="[]",
            checkpoint_json="{}", coverage_json='{"retrieval_complete":true}',
        ))
        session.commit()

    DiscoveryRunner(settings)._execute("level-run")

    with sessions() as session:
        run = session.get(RunRecord, "level-run")
        papers = session.scalars(
            select(PaperRecord).where(PaperRecord.run_id == run.id)
        ).all()
        coverage = json.loads(run.coverage_json)
        checkpoint = json.loads(run.checkpoint_json)
        assert run.phase == "completed"
        assert coverage["completed_levels"] == [
            {"level": 1, "retained_papers": 2, "status": "checkpointed"},
            {"level": 2, "retained_papers": 2, "status": "checkpointed"},
        ]
        assert checkpoint["highest_completed_level"] == 2
        assert {paper.depth for paper in papers} == {0, 1, 2}

