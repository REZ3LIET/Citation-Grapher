"""Initial durable run, paper, and citation schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("phase", sa.String(40), nullable=False),
        sa.Column("outcome", sa.String(60)), sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("counters_json", sa.Text(), nullable=False), sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("exclusions_json", sa.Text(), nullable=False), sa.Column("checkpoint_json", sa.Text(), nullable=False),
        sa.Column("coverage_json", sa.Text(), nullable=False), sa.Column("error", sa.Text()),
        sa.Column("stop_requested", sa.Boolean(), nullable=False), sa.Column("lease_owner", sa.String(80)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_runs_phase", "runs", ["phase"])
    op.create_table("papers",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("canonical_id", sa.String(300), nullable=False), sa.Column("openalex_id", sa.String(80)),
        sa.Column("doi", sa.String(300)), sa.Column("arxiv_id", sa.String(80)), sa.Column("title", sa.Text(), nullable=False),
        sa.Column("authors_json", sa.Text(), nullable=False), sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("venue", sa.Text()), sa.Column("abstract", sa.Text()), sa.Column("url", sa.Text()),
        sa.Column("is_seed", sa.Boolean(), nullable=False), sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("provider_citation_count", sa.Integer()), sa.Column("internal_in_count", sa.Integer(), nullable=False),
        sa.Column("internal_out_count", sa.Integer(), nullable=False), sa.Column("topics_json", sa.Text(), nullable=False),
        sa.Column("relevance_scores_json", sa.Text(), nullable=False), sa.Column("classification_status", sa.String(40), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=False), sa.Column("raw_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("run_id", "canonical_id"))
    op.create_index("ix_papers_run_id", "papers", ["run_id"])
    op.create_index("ix_papers_year", "papers", ["year"])
    op.create_index("ix_papers_depth", "papers", ["depth"])
    op.create_table("citations",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("citing_paper_id", sa.String(300), nullable=False), sa.Column("cited_paper_id", sa.String(300), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=False), sa.Column("retrieval_date", sa.String(10), nullable=False),
        sa.Column("citation_context", sa.Text()), sa.UniqueConstraint("run_id", "citing_paper_id", "cited_paper_id"))
    op.create_index("ix_citations_run_id", "citations", ["run_id"])


def downgrade() -> None:
    op.drop_table("citations")
    op.drop_table("papers")
    op.drop_table("runs")

