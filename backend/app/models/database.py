from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class RunRecord(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    phase: Mapped[str] = mapped_column(String(40), default="created", index=True)
    outcome: Mapped[str | None] = mapped_column(String(60), nullable=True)
    config_json: Mapped[str] = mapped_column(Text)
    counters_json: Mapped[str] = mapped_column(Text, default="{}")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    exclusions_json: Mapped[str] = mapped_column(Text, default="[]")
    checkpoint_json: Mapped[str] = mapped_column(Text, default="{}")
    coverage_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_owner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PaperRecord(Base):
    __tablename__ = "papers"
    __table_args__ = (UniqueConstraint("run_id", "canonical_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    canonical_id: Mapped[str] = mapped_column(String(300))
    openalex_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(300), nullable=True)
    arxiv_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    authors_json: Mapped[str] = mapped_column(Text, default="[]")
    year: Mapped[int] = mapped_column(Integer, index=True)
    venue: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)
    depth: Mapped[int] = mapped_column(Integer, index=True)
    provider_citation_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    internal_in_count: Mapped[int] = mapped_column(Integer, default=0)
    internal_out_count: Mapped[int] = mapped_column(Integer, default=0)
    topics_json: Mapped[str] = mapped_column(Text, default="[]")
    relevance_scores_json: Mapped[str] = mapped_column(Text, default="{}")
    classification_status: Mapped[str] = mapped_column(String(40), default="pending")
    provenance_json: Mapped[str] = mapped_column(Text, default="{}")
    raw_json: Mapped[str] = mapped_column(Text, default="{}")


class CitationRecord(Base):
    __tablename__ = "citations"
    __table_args__ = (UniqueConstraint("run_id", "citing_paper_id", "cited_paper_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    citing_paper_id: Mapped[str] = mapped_column(String(300))
    cited_paper_id: Mapped[str] = mapped_column(String(300))
    provenance_json: Mapped[str] = mapped_column(Text, default="{}")
    retrieval_date: Mapped[str] = mapped_column(String(10))
    citation_context: Mapped[str | None] = mapped_column(Text, nullable=True)

