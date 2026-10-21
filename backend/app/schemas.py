from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


Direction = Literal["backward", "forward", "both"]


class RunCreate(BaseModel):
    seeds: list[str] = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    min_year: int = Field(ge=1000, le=3000)
    max_year: int = Field(ge=1000, le=3000)
    direction: Direction = "both"
    depth: int = Field(default=1, ge=1, le=3)

    @model_validator(mode="after")
    def validate_configuration(self):
        self.seeds = list(dict.fromkeys(seed.strip() for seed in self.seeds if seed.strip()))
        self.topics = list(dict.fromkeys(topic.strip() for topic in self.topics if topic.strip()))
        if not self.seeds:
            raise ValueError("At least one seed paper is required")
        if not self.topics:
            raise ValueError("At least one guiding topic is required")
        if self.min_year > self.max_year:
            raise ValueError("Minimum year must not exceed maximum year")
        return self


class TopicSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    min_year: int = Field(ge=1000, le=3000)
    max_year: int = Field(ge=1000, le=3000)
    limit: int = Field(default=25, ge=1, le=100)

    @model_validator(mode="after")
    def validate_search(self):
        self.query = " ".join(self.query.split())
        if self.min_year > self.max_year:
            raise ValueError("Minimum year must not exceed maximum year")
        return self


class TopicSearchPaper(BaseModel):
    id: str
    openalex_id: str | None
    doi: str | None
    title: str
    authors: list[str]
    year: int
    venue: str | None
    abstract: str | None
    url: str | None
    citation_count: int | None


class TopicSearchResponse(BaseModel):
    query: str
    papers: list[TopicSearchPaper]
    coverage: dict


class RunExpand(BaseModel):
    target_level: int = Field(ge=2, le=3)


class RunSummary(BaseModel):
    id: str
    phase: str
    outcome: str | None
    config: dict
    counters: dict
    warnings: list
    exclusions: list
    coverage: dict
    error_code: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class PaperView(BaseModel):
    id: str
    title: str
    authors: list[str]
    year: int
    venue: str | None
    abstract: str | None
    doi: str | None
    url: str | None
    is_seed: bool
    depth: int
    provider_citation_count: int | None
    internal_in_count: int
    internal_out_count: int
    topics: list[str]
    relevance_scores: dict[str, float]
    classification_status: str
    provenance: dict


class CitationView(BaseModel):
    source: str
    target: str
    provenance: dict


class GraphView(BaseModel):
    run: RunSummary
    papers: list[PaperView]
    citations: list[CitationView]

