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
    stores_file: Path | None = None

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

    automatic_memory_importance: float = Field(default=0.5, ge=0.0, le=2.0)
    automatic_memory_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    automatic_memory_source_quality: float = Field(default=1.0, ge=0.0, le=1.0)

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
        if self.stores_file is not None:
            self.stores_file = self.stores_file.expanduser().resolve()

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "contextual_memory.sqlite3"

    @property
    def chroma_path(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def store_registry_path(self) -> Path:
        return self.data_dir / "store_registry.sqlite3"
