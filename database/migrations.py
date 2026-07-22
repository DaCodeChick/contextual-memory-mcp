from __future__ import annotations

import sqlite3
from collections.abc import Callable

Migration = Callable[[sqlite3.Connection], None]


def _column_names(db: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in db.execute(f"PRAGMA table_info({table})")}


def migration_0001_identity_and_hashes(db: sqlite3.Connection) -> None:
    columns = _column_names(db, "segments")
    if "identity_key" not in columns:
        db.execute("ALTER TABLE segments ADD COLUMN identity_key TEXT")
    if "content_hash" not in columns:
        db.execute("ALTER TABLE segments ADD COLUMN content_hash TEXT")

    # Existing rows predate stable segment identity. Their ordinal is the only
    # stable locator available, so preserve it as the migration identity.
    db.execute(
        """
        UPDATE segments
        SET identity_key = COALESCE(identity_key, 'legacy:' || ordinal)
        """
    )
    db.execute(
        """
        UPDATE segments
        SET content_hash = COALESCE(content_hash, sha256_text(text))
        """
    )
    db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_segments_source_identity
        ON segments(source_id, identity_key)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_segments_content_hash
        ON segments(content_hash)
        """
    )


MIGRATIONS: list[tuple[int, str, Migration]] = [
    (1, "segment identity and content hashes", migration_0001_identity_and_hashes),
]


def apply_migrations(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied = {
        int(row[0])
        for row in db.execute("SELECT version FROM schema_migrations")
    }
    for version, name, migration in MIGRATIONS:
        if version in applied:
            continue
        migration(db)
        db.execute(
            "INSERT INTO schema_migrations(version, name) VALUES(?, ?)",
            (version, name),
        )
