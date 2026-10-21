import pytest
from pydantic import ValidationError

from app.schemas import RunCreate, RunExpand
from app.topics import TopicAnnotator


def test_run_configuration_normalizes_and_validates():
    request = RunCreate(
        seeds=[" doi:one ", "doi:two", "doi:one"], topics=[" graphs ", "graphs"],
        min_year=2020, max_year=2025,
    )
    assert request.seeds == ["doi:one", "doi:two"]
    assert request.topics == ["graphs"]
    assert request.direction == "both"
    assert request.depth == 1


def test_run_configuration_accepts_one_seed():
    request = RunCreate(
        seeds=["doi:one"], topics=["graphs"], min_year=2020, max_year=2025,
    )
    assert request.seeds == ["doi:one"]


@pytest.mark.parametrize("payload", [
    {"seeds": [], "topics": ["topic"], "min_year": 2020, "max_year": 2025},
    {"seeds": ["one", "two"], "topics": [], "min_year": 2020, "max_year": 2025},
    {"seeds": ["one", "two"], "topics": ["topic"], "min_year": 2026, "max_year": 2025},
    {"seeds": ["one", "two"], "topics": ["topic"], "min_year": 2020, "max_year": 2025, "depth": 4},
])
def test_invalid_run_configuration_is_rejected(payload):
    with pytest.raises(ValidationError):
        RunCreate(**payload)


def test_topic_annotation_preserves_all_scores_and_unclassified_state(monkeypatch):
    annotator = TopicAnnotator("model-not-installed", 0.0)
    results, metadata = annotator.annotate(
        [{"title": "Citation graph retrieval", "abstract": "Research paper discovery"},
         {"title": "x", "abstract": None}],
        ["citation networks", "protein folding"],
    )
    assert set(results[0]["scores"]) == {"citation networks", "protein folding"}
    assert results[0]["topics"] == ["citation networks", "protein folding"]
    assert results[1] == {"topics": [], "scores": {}, "status": "unclassified"}
    assert metadata["interpretation"] == "heuristic_not_probability"


def test_level_expansion_is_bounded():
    assert RunExpand(target_level=2).target_level == 2
    with pytest.raises(ValidationError):
        RunExpand(target_level=4)

