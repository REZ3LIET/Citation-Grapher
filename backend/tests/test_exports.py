import csv
import io
import json
import zipfile

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.exports import build_subset_archive, export_run
from app.models import Base, CitationRecord, PaperRecord, RunRecord


def test_export_pair_is_referentially_consistent_and_metadata_reports_coverage(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        run = RunRecord(
            id="run-1", phase="completed_partial", outcome="collection_budget_reached",
            config_json=json.dumps({"topics": ["graphs"]}), counters_json=json.dumps({"papers": 2}),
            warnings_json="[]", exclusions_json="[]", checkpoint_json="{}",
            coverage_json=json.dumps({"retrieval_complete": False}),
        )
        session.add(run)
        for identifier, seed in [("p1", True), ("p2", False)]:
            session.add(PaperRecord(
                run_id=run.id, canonical_id=identifier, title=f"={identifier}", authors_json="[]",
                year=2024, is_seed=seed, depth=0 if seed else 1,
            ))
        session.add(CitationRecord(
            run_id=run.id, citing_paper_id="p2", cited_paper_id="p1",
            provenance_json="{}", retrieval_date="2026-10-20",
        ))
        session.commit()
        paths = export_run(session, run, tmp_path)
    with open(paths["papers.csv"], newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    with open(paths["citations.csv"], newline="", encoding="utf-8") as handle:
        edges = list(csv.DictReader(handle))
    metadata = json.loads((tmp_path / "run-1" / "run_metadata.json").read_text())
    assert {row["paper_id"] for row in rows} == {"p1", "p2"}
    assert edges == [{
        "citing_paper_id": "p2", "cited_paper_id": "p1", "citation_provenance": "{}",
        "retrieval_date": "2026-10-20", "citation_context": "",
    }]
    assert rows[0]["title"].startswith("'")
    assert metadata["coverage"]["retrieval_complete"] is False


def test_subset_archive_preserves_csv_schema_and_only_internal_subset_edges():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        run = RunRecord(
            id="subset-run", phase="completed", outcome="fully_processed_attempted_traversal",
            config_json="{}", counters_json="{}", warnings_json="[]", exclusions_json="[]",
            checkpoint_json="{}", coverage_json='{"retrieval_complete":true}',
        )
        session.add(run)
        for identifier in ("seed", "included", "excluded"):
            session.add(PaperRecord(
                run_id=run.id, canonical_id=identifier, title=identifier,
                authors_json="[]", year=2025, is_seed=identifier == "seed",
                depth=0 if identifier == "seed" else 1,
            ))
        session.add_all([
            CitationRecord(
                run_id=run.id, citing_paper_id="included", cited_paper_id="seed",
                provenance_json="{}", retrieval_date="2026-10-22",
            ),
            CitationRecord(
                run_id=run.id, citing_paper_id="excluded", cited_paper_id="seed",
                provenance_json="{}", retrieval_date="2026-10-22",
            ),
        ])
        session.commit()
        archive = build_subset_archive(
            session, run, ["seed", "included"], "unlearning AND causal",
            {"min_year": 2020, "max_year": 2026},
        )

    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        assert set(bundle.namelist()) == {
            "papers.csv", "citations.csv", "graph.graphml", "subset_metadata.json",
        }
        papers = list(csv.DictReader(io.StringIO(bundle.read("papers.csv").decode())))
        citations = list(csv.DictReader(io.StringIO(bundle.read("citations.csv").decode())))
        metadata = json.loads(bundle.read("subset_metadata.json"))
    assert {row["paper_id"] for row in papers} == {"seed", "included"}
    assert [(row["citing_paper_id"], row["cited_paper_id"]) for row in citations] == [
        ("included", "seed"),
    ]
    assert metadata["filter_expression"] == "unlearning AND causal"
    assert metadata["statistics"] == {"papers": 2, "citations": 1}

