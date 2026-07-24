from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from providers.web import SearchResult


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


@dataclass(frozen=True)
class AcquisitionHistory:
    query: str
    status: str
    pages_indexed: int
    last_attempt_at: str
    error: str | None = None


class WebAcquisitionCache:
    """Persistent search-result cache and acquisition-attempt history."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS search_cache(
                    query_hash TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    results_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_search_cache_expires
                    ON search_cache(expires_at);

                CREATE TABLE IF NOT EXISTS acquisition_history(
                    query_hash TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    status TEXT NOT NULL,
                    pages_indexed INTEGER NOT NULL DEFAULT 0,
                    last_attempt_at TEXT NOT NULL,
                    retry_after TEXT,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_acquisition_retry
                    ON acquisition_history(retry_after);
                """
            )

    @staticmethod
    def query_hash(query: str) -> str:
        normalized = " ".join(query.casefold().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def get_search(self, query: str) -> tuple[str, list[SearchResult]] | None:
        key = self.query_hash(query)
        now = _iso(_utcnow())
        with self._connect() as db:
            row = db.execute(
                "SELECT provider, results_json FROM search_cache WHERE query_hash=? AND expires_at>?",
                (key, now),
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(str(row["results_json"]))
            results = [
                SearchResult(
                    title=str(item.get("title") or ""),
                    url=str(item.get("url") or ""),
                    snippet=str(item.get("snippet") or ""),
                )
                for item in payload
                if isinstance(item, dict)
            ]
        except (json.JSONDecodeError, TypeError):
            return None
        return str(row["provider"]), results

    def put_search(
        self,
        query: str,
        provider: str,
        results: Iterable[SearchResult],
        *,
        ttl_days: int,
    ) -> None:
        now = _utcnow()
        payload = [
            {"title": item.title, "url": item.url, "snippet": item.snippet}
            for item in results
        ]
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO search_cache(query_hash, query, provider, created_at, expires_at, results_json)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(query_hash) DO UPDATE SET
                    query=excluded.query,
                    provider=excluded.provider,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at,
                    results_json=excluded.results_json
                """,
                (
                    self.query_hash(query), query, provider, _iso(now),
                    _iso(now + timedelta(days=max(0, ttl_days))),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )

    def should_skip(self, query: str) -> AcquisitionHistory | None:
        key = self.query_hash(query)
        now = _iso(_utcnow())
        with self._connect() as db:
            row = db.execute(
                """
                SELECT query, status, pages_indexed, last_attempt_at, error
                FROM acquisition_history
                WHERE query_hash=? AND retry_after IS NOT NULL AND retry_after>?
                """,
                (key, now),
            ).fetchone()
        if not row:
            return None
        return AcquisitionHistory(
            query=str(row["query"]), status=str(row["status"]),
            pages_indexed=int(row["pages_indexed"]),
            last_attempt_at=str(row["last_attempt_at"]),
            error=str(row["error"]) if row["error"] is not None else None,
        )

    def record_attempt(
        self,
        query: str,
        *,
        status: str,
        pages_indexed: int,
        retry_after_days: int,
        error: str | None = None,
    ) -> None:
        now = _utcnow()
        retry_after = now + timedelta(days=max(0, retry_after_days))
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO acquisition_history(
                    query_hash, query, status, pages_indexed, last_attempt_at, retry_after, error
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(query_hash) DO UPDATE SET
                    query=excluded.query,
                    status=excluded.status,
                    pages_indexed=excluded.pages_indexed,
                    last_attempt_at=excluded.last_attempt_at,
                    retry_after=excluded.retry_after,
                    error=excluded.error
                """,
                (
                    self.query_hash(query), query, status, pages_indexed,
                    _iso(now), _iso(retry_after), error,
                ),
            )
