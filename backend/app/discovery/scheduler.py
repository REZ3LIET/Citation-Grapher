from __future__ import annotations

from dataclasses import dataclass, field

from ..providers import Work


@dataclass
class Candidate:
    work: Work
    parents: set[str] = field(default_factory=set)
    directions: set[str] = field(default_factory=set)
    frontiers: set[str] = field(default_factory=set)
    providers: set[str] = field(default_factory=lambda: {"openalex"})

    @property
    def sort_key(self) -> tuple:
        missing_count = self.work.citation_count is None
        count = self.work.citation_count if self.work.citation_count is not None else 0
        year = self.work.year if self.work.year is not None else -1
        return missing_count, count, -year, self.work.canonical_id

    def merge(self, other: "Candidate") -> None:
        self.parents.update(other.parents)
        self.directions.update(other.directions)
        self.frontiers.update(other.frontiers)
        self.providers.update(other.providers)

    def to_checkpoint(self) -> dict:
        evidence = {
            key: self.work.raw[key]
            for key in ("bibliography_evidence", "seed_source", "provider", "anthology_id")
            if key in self.work.raw
        }
        return {
            "work": {
                "canonical_id": self.work.canonical_id,
                "openalex_id": self.work.openalex_id,
                "doi": self.work.doi,
                "arxiv_id": self.work.arxiv_id,
                "title": self.work.title,
                "authors": self.work.authors,
                "year": self.work.year,
                "venue": self.work.venue,
                "abstract": self.work.abstract,
                "url": self.work.url,
                "citation_count": self.work.citation_count,
                "referenced_works": self.work.referenced_works,
                # Provider payloads can be very large. Checkpoints need only
                # relationship evidence; normalized fields are stored above.
                "raw": evidence,
            },
            "parents": sorted(self.parents),
            "directions": sorted(self.directions),
            "frontiers": sorted(self.frontiers),
            "providers": sorted(self.providers),
        }

    @classmethod
    def from_checkpoint(cls, value: dict) -> "Candidate":
        return cls(
            work=Work(**value["work"]),
            parents=set(value["parents"]),
            directions=set(value["directions"]),
            frontiers=set(value["frontiers"]),
            providers=set(value["providers"]),
        )


def merge_candidates(candidates: list[Candidate]) -> dict[str, Candidate]:
    merged: dict[str, Candidate] = {}
    for candidate in candidates:
        existing = merged.get(candidate.work.canonical_id)
        if existing:
            existing.merge(candidate)
        else:
            merged[candidate.work.canonical_id] = candidate
    return merged


def schedule_balanced(candidates: list[Candidate], seed_order: list[str]) -> list[Candidate]:
    """Deterministically interleave sorted seed-frontier queues.

    A candidate shared by multiple frontiers appears once. Its first appearance
    consumes one turn for that frontier; all contribution provenance remains on
    the candidate.
    """
    merged = merge_candidates(candidates)
    queues = {
        seed: sorted(
            (candidate for candidate in merged.values() if seed in candidate.frontiers),
            key=lambda candidate: candidate.sort_key,
        )
        for seed in seed_order
    }
    positions = {seed: 0 for seed in seed_order}
    emitted: set[str] = set()
    result: list[Candidate] = []
    while True:
        progressed = False
        for seed in seed_order:
            queue = queues[seed]
            while positions[seed] < len(queue):
                candidate = queue[positions[seed]]
                positions[seed] += 1
                if candidate.work.canonical_id in emitted:
                    continue
                emitted.add(candidate.work.canonical_id)
                result.append(candidate)
                progressed = True
                break
        if not progressed:
            break
    # Candidates with no recognized seed provenance remain deterministic.
    result.extend(
        sorted(
            (candidate for key, candidate in merged.items() if key not in emitted),
            key=lambda candidate: candidate.sort_key,
        )
    )
    return result

