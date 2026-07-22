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


class StoreRegistry:
    """Persistent registry plus writable overlays for locked stores."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_stores (
                    store_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    sqlite_path TEXT NOT NULL,
                    chroma_path TEXT NOT NULL,
                    collection_name TEXT NOT NULL,
                    mode INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    priority REAL NOT NULL DEFAULT 1.0,
                    specialty TEXT
                );
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

    def upsert(self, config: MemoryStoreConfig) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO memory_stores(
                    store_id, display_name, sqlite_path, chroma_path,
                    collection_name, mode, enabled, priority, specialty
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(store_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    sqlite_path=excluded.sqlite_path,
                    chroma_path=excluded.chroma_path,
                    collection_name=excluded.collection_name,
                    mode=excluded.mode,
                    enabled=excluded.enabled,
                    priority=excluded.priority,
                    specialty=excluded.specialty
                """,
                (
                    config.store_id, config.display_name,
                    str(config.sqlite_path), str(config.chroma_path),
                    config.collection_name, int(config.mode),
                    int(config.enabled), config.priority, config.specialty,
                ),
            )

    def remove(self, store_id: str) -> bool:
        if store_id == "main":
            raise ValueError("The main store cannot be unmounted")
        with self._connect() as db:
            cursor = db.execute("DELETE FROM memory_stores WHERE store_id=?", (store_id,))
            return cursor.rowcount > 0

    def set_enabled(self, store_id: str, enabled: bool) -> MemoryStoreConfig:
        if store_id == "main" and not enabled:
            raise ValueError("The main store cannot be disabled")
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE memory_stores SET enabled=? WHERE store_id=?",
                (int(enabled), store_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Unknown memory store: {store_id}")
        return self.get(store_id)

    def list(self) -> list[MemoryStoreConfig]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM memory_stores ORDER BY store_id").fetchall()
        return [
            MemoryStoreConfig(
                store_id=str(row["store_id"]),
                display_name=str(row["display_name"]),
                sqlite_path=Path(str(row["sqlite_path"])),
                chroma_path=Path(str(row["chroma_path"])),
                collection_name=str(row["collection_name"]),
                mode=StoreMode(int(row["mode"])),
                enabled=bool(row["enabled"]),
                priority=float(row["priority"]),
                specialty=row["specialty"],
            )
            for row in rows
        ]

    def get(self, store_id: str) -> MemoryStoreConfig:
        for config in self.list():
            if config.store_id == store_id:
                return config
        raise KeyError(f"Unknown memory store: {store_id}")

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


def load_store_manifest(path: Path, base_dir: Path) -> list[MemoryStoreConfig]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("stores", payload) if isinstance(payload, dict) else payload
    result: list[MemoryStoreConfig] = []
    for item in entries:
        sqlite_path = Path(item["sqlite_path"])
        chroma_path = Path(item["chroma_path"])
        if not sqlite_path.is_absolute():
            sqlite_path = base_dir / sqlite_path
        if not chroma_path.is_absolute():
            chroma_path = base_dir / chroma_path
        result.append(
            MemoryStoreConfig(
                store_id=str(item["store_id"]),
                display_name=str(item.get("display_name", item["store_id"])),
                sqlite_path=sqlite_path.expanduser().resolve(),
                chroma_path=chroma_path.expanduser().resolve(),
                collection_name=str(item.get("collection_name", "context_segments")),
                mode=StoreMode(int(item.get("mode", 0))),
                enabled=bool(item.get("enabled", True)),
                priority=float(item.get("priority", 1.0)),
                specialty=item.get("specialty"),
            )
        )
    return result
