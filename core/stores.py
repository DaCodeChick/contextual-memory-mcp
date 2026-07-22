from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Iterable


class StoreMode(IntEnum):
    READ_WRITE = 0
    READ_ONLY = 1
    IMMUTABLE = 2


@dataclass(frozen=True, slots=True)
class MemoryRef:
    store_id: str
    segment_id: str

    def __str__(self) -> str:
        return f"{self.store_id}:{self.segment_id}"

    @classmethod
    def parse(cls, value: str) -> "MemoryRef":
        if ":" not in value:
            raise ValueError(f"Memory references must be store-qualified: {value!r}")
        store_id, segment_id = value.split(":", 1)
        if not store_id or not segment_id:
            raise ValueError(f"Invalid memory reference: {value!r}")
        return cls(store_id, segment_id)


@dataclass(frozen=True, slots=True)
class MemoryStoreConfig:
    store_id: str
    display_name: str
    sqlite_path: Path
    chroma_path: Path
    collection_name: str = "context_segments"
    mode: StoreMode = StoreMode.READ_WRITE
    enabled: bool = True
    priority: float = 1.0
    specialty: str | None = None

    def as_dict(self) -> dict:
        return {
            "store_id": self.store_id,
            "display_name": self.display_name,
            "sqlite_path": str(self.sqlite_path),
            "chroma_path": str(self.chroma_path),
            "collection_name": self.collection_name,
            "mode": int(self.mode),
            "mode_name": self.mode.name,
            "enabled": self.enabled,
            "priority": self.priority,
            "specialty": self.specialty,
        }


class StoreOverlays:
    """Persistent local usage and ranking overlays for locked stores."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS external_memory_usage (
                    store_id TEXT NOT NULL,
                    segment_id TEXT NOT NULL,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    last_accessed_at TEXT,
                    local_boost REAL NOT NULL DEFAULT 0.0,
                    hidden INTEGER NOT NULL DEFAULT 0,
                    pinned_override INTEGER,
                    PRIMARY KEY(store_id, segment_id)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def record_external_access(self, store_id: str, segment_ids: Iterable[str]) -> None:
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.executemany(
                """
                INSERT INTO external_memory_usage(
                    store_id, segment_id, access_count, last_accessed_at
                ) VALUES(?,?,1,?)
                ON CONFLICT(store_id, segment_id) DO UPDATE SET
                    access_count=access_count+1,
                    last_accessed_at=excluded.last_accessed_at
                """,
                [(store_id, segment_id, timestamp) for segment_id in segment_ids],
            )

    def overlays(self, store_id: str, segment_ids: Iterable[str]) -> dict[str, dict]:
        ids = list(segment_ids)
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM external_memory_usage WHERE store_id=? AND segment_id IN ({marks})",
                (store_id, *ids),
            ).fetchall()
        return {str(row["segment_id"]): dict(row) for row in rows}

    def set_overlay(
        self,
        store_id: str,
        segment_id: str,
        *,
        local_boost: float | None = None,
        hidden: bool | None = None,
        pinned_override: bool | None = None,
    ) -> dict:
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO external_memory_usage(store_id, segment_id) VALUES(?,?)",
                (store_id, segment_id),
            )
            updates: list[str] = []
            values: list[object] = []
            if local_boost is not None:
                updates.append("local_boost=?")
                values.append(float(local_boost))
            if hidden is not None:
                updates.append("hidden=?")
                values.append(int(hidden))
            if pinned_override is not None:
                updates.append("pinned_override=?")
                values.append(int(pinned_override))
            if updates:
                db.execute(
                    f"UPDATE external_memory_usage SET {', '.join(updates)} WHERE store_id=? AND segment_id=?",
                    (*values, store_id, segment_id),
                )
            row = db.execute(
                "SELECT * FROM external_memory_usage WHERE store_id=? AND segment_id=?",
                (store_id, segment_id),
            ).fetchone()
        return dict(row)


def write_store_manifest(store_root: Path, config: MemoryStoreConfig) -> Path:
    store_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "store_id": config.store_id,
        "display_name": config.display_name,
        "sqlite_path": config.sqlite_path.name,
        "chroma_path": config.chroma_path.name,
        "collection_name": config.collection_name,
        "mode": int(config.mode),
        "priority": config.priority,
        "specialty": config.specialty,
    }
    path = store_root / "manifest.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def discover_store_manifests(stores_root: Path) -> list[MemoryStoreConfig]:
    if not stores_root.exists():
        return []
    result: list[MemoryStoreConfig] = []
    for manifest in sorted(stores_root.glob("*/manifest.json")):
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        store_root = manifest.parent
        sqlite_path = Path(str(payload.get("sqlite_path", f"{store_root.name}.sqlite3")))
        chroma_path = Path(str(payload.get("chroma_path", "chroma")))
        if not sqlite_path.is_absolute():
            sqlite_path = store_root / sqlite_path
        if not chroma_path.is_absolute():
            chroma_path = store_root / chroma_path
        result.append(
            MemoryStoreConfig(
                store_id=str(payload.get("store_id", store_root.name)),
                display_name=str(payload.get("display_name", store_root.name)),
                sqlite_path=sqlite_path.resolve(),
                chroma_path=chroma_path.resolve(),
                collection_name=str(payload.get("collection_name", "context_segments")),
                mode=StoreMode(int(payload.get("mode", int(StoreMode.IMMUTABLE)))),
                enabled=True,
                priority=float(payload.get("priority", 1.0)),
                specialty=payload.get("specialty"),
            )
        )
    return result
