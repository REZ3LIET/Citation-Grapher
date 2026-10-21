from app.discovery.scheduler import Candidate, schedule_balanced
from app.providers.openalex import Work


def work(identifier: str, citations: int | None, year: int) -> Work:
    return Work(
        canonical_id=identifier, openalex_id=identifier.upper(), doi=None, arxiv_id=None,
        title=identifier, authors=[], year=year, venue=None, abstract=None, url=None,
        citation_count=citations,
    )


def test_candidate_priority_and_balanced_frontiers_are_deterministic():
    candidates = [
        Candidate(work("a", 2, 2020), frontiers={"seed-1"}),
        Candidate(work("b", 3, 2024), frontiers={"seed-1"}),
        Candidate(work("c", 40, 2025), frontiers={"seed-2"}),
        Candidate(work("d", 1, 2022), frontiers={"seed-2"}),
    ]
    result = schedule_balanced(candidates, ["seed-1", "seed-2"])
    assert [item.work.canonical_id for item in result] == ["a", "d", "b", "c"]


def test_forward_backward_duplicates_merge_with_all_provenance():
    backward = Candidate(work("shared", 1, 2025), parents={"p1"}, directions={"backward"}, frontiers={"s1"})
    forward = Candidate(work("shared", 1, 2025), parents={"p2"}, directions={"forward"}, frontiers={"s2"})
    [merged] = schedule_balanced([backward, forward], ["s1", "s2"])
    assert merged.parents == {"p1", "p2"}
    assert merged.directions == {"backward", "forward"}
    assert merged.frontiers == {"s1", "s2"}


def test_missing_citation_count_sorts_after_known_counts():
    candidates = [
        Candidate(work("unknown", None, 2025), frontiers={"seed"}),
        Candidate(work("known", 999, 2020), frontiers={"seed"}),
    ]
    assert [item.work.canonical_id for item in schedule_balanced(candidates, ["seed"])] == ["known", "unknown"]


def test_checkpoint_discards_large_provider_payload_but_keeps_edge_evidence():
    item = work("compact", 1, 2025)
    item.raw = {
        "abstract_inverted_index": {"large": list(range(1000))},
        "authorships": [{"large": "provider payload"}],
        "bibliography_evidence": {"source_arxiv_id": "2504.12996", "raw_reference": "Evidence"},
    }
    checkpoint = Candidate(item).to_checkpoint()
    assert checkpoint["work"]["raw"] == {
        "bibliography_evidence": {
            "source_arxiv_id": "2504.12996", "raw_reference": "Evidence",
        }
    }

