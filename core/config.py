from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _csv(value: object) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(part) for part in value]
    raise TypeError("Expected a comma-separated string or list")


CsvList = Annotated[list[str], BeforeValidator(_csv)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PM_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    prompt_dir: Path = Path("./prompts")
    data_dir: Path = Path("./data")
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    collection_name: str = "prompt_segments"
    chunk_size: int = Field(default=1800, ge=300, le=12000)
    chunk_overlap: int = Field(default=220, ge=0, le=3000)
    default_top_k: int = Field(default=8, ge=1, le=50)
    max_context_chars: int = Field(default=18000, ge=1000, le=200000)
    include_globs: CsvList = ["*.md", "*.txt", "*.prompt"]
    exclude_dirs: CsvList = [".git", ".venv", "__pycache__", "node_modules"]

    def prepare(self) -> None:
        self.prompt_dir = self.prompt_dir.expanduser().resolve()
        self.data_dir = self.data_dir.expanduser().resolve()
        self.prompt_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "prompt_memory.sqlite3"

    @property
    def chroma_path(self) -> Path:
        return self.data_dir / "chroma"
