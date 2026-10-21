from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="CITATION_GRAPHER_", extra="ignore"
    )

    database_url: str = "sqlite:///./data/citation_grapher.db"
    runs_dir: Path = Path("./data/runs")
    openalex_base_url: str = "https://api.openalex.org"
    grobid_base_url: str = "http://localhost:8070"
    max_pages_per_query: int = 3
    max_candidates_per_parent_direction: int = 600
    max_pending_candidates_per_depth: int = 10_000
    max_provider_requests_per_run: int = 1_500
    max_topic_search_requests: int = 4
    paper_warning_threshold: int = 500
    paper_hard_limit: int = 1_000
    topic_threshold: float = 0.35
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    request_timeout_seconds: float = 20.0
    provider_max_retries: int = 3
    provider_retry_base_seconds: float = 0.5
    provider_retry_max_seconds: float = 8.0
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite:///./"):
        Path(settings.database_url.removeprefix("sqlite:///./")).parent.mkdir(
            parents=True, exist_ok=True
        )
    return settings

