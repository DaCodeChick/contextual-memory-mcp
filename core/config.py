from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator, Field
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    SettingsConfigDict,
)


def _csv(value: object) -> list[str]:
    if isinstance(value, str):
        return [
            part.strip()
            for part in value.split(",")
            if part.strip()
        ]
    if isinstance(value, list):
        return [str(part) for part in value]
    raise TypeError("Expected a comma-separated string or list")


CsvList = Annotated[
    list[str],
    NoDecode,
    BeforeValidator(_csv),
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Path("./data")
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    collection_name: str = "context_segments"

    chunk_size: int = Field(default=1800, ge=300, le=12000)
    chunk_overlap: int = Field(default=220, ge=0, le=3000)
    default_top_k: int = Field(default=8, ge=1, le=50)
    max_context_chars: int = Field(
        default=18000,
        ge=1000,
        le=200000,
    )

    lifecycle_promotion_importance: float = Field(
        default=1.5, ge=0.0, le=2.0
    )
    lifecycle_promotion_access_count: int = Field(default=3, ge=0)
    lifecycle_minimum_confidence: float = Field(
        default=0.6, ge=0.0, le=1.0
    )
    lifecycle_minimum_source_quality: float = Field(
        default=0.5, ge=0.0, le=1.0
    )
    lifecycle_archive_importance: float = Field(
        default=0.35, ge=0.0, le=2.0
    )
    lifecycle_archive_after_days: int = Field(default=90, ge=0)

    importance_access_gain: float = Field(default=0.05, ge=0.0, le=2.0)
    importance_decay_per_30_days: float = Field(default=0.05, ge=0.0, le=2.0)
    importance_decay_grace_days: int = Field(default=30, ge=0)
    importance_minimum: float = Field(default=0.0, ge=0.0, le=2.0)
    importance_maximum: float = Field(default=2.0, ge=0.0, le=2.0)
    ranking_recency_half_life_days: float = Field(default=45.0, gt=0.0)

    automatic_memory_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    automatic_memory_source_quality: float = Field(default=1.0, ge=0.0, le=1.0)

    web_acquisition_enabled: bool = True
    web_acquisition_min_score: float = Field(default=0.28, ge=0.0)
    web_acquisition_max_results: int = Field(default=8, ge=1, le=30)
    web_acquisition_max_pages: int = Field(default=4, ge=1, le=12)
    web_acquisition_store: str = "main"
    web_search_providers: CsvList = ["exa", "brave", "tavily", "searxng", "duckduckgo"]
    web_search_timeout: float = Field(default=6.0, gt=0.0, le=120.0)
    web_fetch_timeout: float = Field(default=8.0, gt=0.0, le=120.0)
    web_acquisition_total_timeout: float = Field(default=45.0, gt=1.0, le=600.0)
    web_search_cache_days: int = Field(default=7, ge=0, le=365)
    web_acquisition_retry_days: int = Field(default=7, ge=0, le=365)
    web_acquisition_refresh_days: int = Field(default=90, ge=0, le=3650)
    exa_api_key: str | None = None
    brave_search_api_key: str | None = None
    tavily_api_key: str | None = None
    searxng_url: str | None = None

    include_globs: CsvList = ["*.md", "*.txt", "*.prompt"]
    exclude_dirs: CsvList = [
        ".git",
        ".venv",
        "__pycache__",
        "node_modules",
    ]

    def prepare(self) -> None:
        self.data_dir = self.data_dir.expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "contextual_memory.sqlite3"

    @property
    def chroma_path(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def overlays_path(self) -> Path:
        return self.data_dir / "store_overlays.sqlite3"

    @property
    def stores_dir(self) -> Path:
        return self.data_dir / "stores"

    @property
    def web_cache_path(self) -> Path:
        return self.data_dir / "web_acquisition.sqlite3"
