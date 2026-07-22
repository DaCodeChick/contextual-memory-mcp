from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

from core.enums import (
    LifecycleReason,
    MemoryOrigin,
    MemoryState,
    MemoryType,
    coerce_enum,
)
from core.lifecycle import LifecycleDecision
from core.models import MemorySegment, SourceDocument
from database.migrations import apply_migrations
from database.schema import SCHEMA


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def concept_id(name: str) -> str:
    return "con_" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:24]


class SQLiteRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.create_function(
            "sha256_text",
            1,
            lambda value: hashlib.sha256(str(value).encode("utf-8")).hexdigest(),
        )
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(SCHEMA)
            apply_migrations(db)

    def clear(self) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM concept_edges")
            db.execute("DELETE FROM segment_concepts")
            db.execute("DELETE FROM segments_fts")
            db.execute("DELETE FROM segments")
            db.execute("DELETE FROM concepts")
            db.execute("DELETE FROM sources")

    def source_hash(self, path: str) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT content_hash FROM sources WHERE source_path=?",
                (path,),
            ).fetchone()
            return str(row[0]) if row else None

    def file_paths(self) -> set[str]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT source_path FROM sources WHERE source_kind='file'"
            )
            return {str(row[0]) for row in rows}

    def file_paths_for_root(self, root: str) -> set[str]:
        prefix = f"{root}::%"
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT source_path
                FROM sources
                WHERE source_kind='file' AND source_path LIKE ?
                """,
                (prefix,),
            )
            return {str(row[0]) for row in rows}

    def reconcile_document(
        self,
        doc: SourceDocument,
        segments: Sequence[MemorySegment],
        source_kind: str = "file",
    ) -> dict[str, list[str]]:
        """Reconcile scanner-owned content while preserving segment identity.

        Existing rows are updated in place by ``identity_key``. This is the
        foundation for preserving future learned state such as pinning and
        access history across rescans.
        """
        with self.connect() as db:
            existing_rows = db.execute(
                """
                SELECT segment_id, identity_key, content_hash
                FROM segments
                WHERE source_id=?
                """,
                (doc.source_id,),
            ).fetchall()
            existing = {str(row["identity_key"]): row for row in existing_rows}
            incoming_keys = {segment.identity_key for segment in segments}

            deleted_ids = [
                str(row["segment_id"])
                for key, row in existing.items()
                if key not in incoming_keys
            ]

            db.execute(
                """
                INSERT INTO sources(
                    source_id, source_path, title, content_hash, modified_ns,
                    size_bytes, source_kind, indexed_at
                ) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(source_id) DO UPDATE SET
                    source_path=excluded.source_path,
                    title=excluded.title,
                    content_hash=excluded.content_hash,
                    modified_ns=excluded.modified_ns,
                    size_bytes=excluded.size_bytes,
                    source_kind=excluded.source_kind,
                    indexed_at=excluded.indexed_at
                """,
                (
                    doc.source_id,
                    doc.relative_path,
                    doc.title,
                    doc.content_hash,
                    doc.modified_ns,
                    doc.size_bytes,
                    source_kind,
                    now(),
                ),
            )

            if deleted_ids:
                db.executemany(
                    "DELETE FROM segments_fts WHERE segment_id=?",
                    [(segment_id,) for segment_id in deleted_ids],
                )
                marks = ",".join("?" for _ in deleted_ids)
                db.execute(
                    f"DELETE FROM segments WHERE segment_id IN ({marks})",
                    tuple(deleted_ids),
                )

            # Rebuild source-owned search/concept projections. Segment rows are
            # preserved and updated in place, so future learned columns survive.
            source_segment_ids = [
                str(row[0])
                for row in db.execute(
                    "SELECT segment_id FROM segments WHERE source_id=?",
                    (doc.source_id,),
                )
            ]
            if source_segment_ids:
                db.executemany(
                    "DELETE FROM segments_fts WHERE segment_id=?",
                    [(segment_id,) for segment_id in source_segment_ids],
                )
                marks = ",".join("?" for _ in source_segment_ids)
                db.execute(
                    f"DELETE FROM segment_concepts WHERE segment_id IN ({marks})",
                    tuple(source_segment_ids),
                )

            inserted_ids: list[str] = []
            updated_ids: list[str] = []
            unchanged_ids: list[str] = []

            for segment in segments:
                old = existing.get(segment.identity_key)
                if old is None:
                    db.execute(
                        """
                        INSERT INTO segments(
                            segment_id, source_id, ordinal, heading, text,
                            char_start, char_end, importance, confidence,
                            source_quality, memory_state, memory_type,
                            memory_origin, identity_key, content_hash
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            segment.segment_id, segment.source_id,
                            segment.ordinal, segment.heading, segment.text,
                            segment.char_start, segment.char_end,
                            segment.importance, segment.confidence,
                            segment.source_quality, int(segment.memory_state),
                            int(segment.memory_type), int(segment.memory_origin),
                            segment.identity_key, segment.content_hash,
                        ),
                    )
                    inserted_ids.append(segment.segment_id)
                else:
                    persistent_id = str(old["segment_id"])
                    segment.segment_id = persistent_id
                    db.execute(
                        """
                        UPDATE segments SET
                            ordinal=?, heading=?, text=?, char_start=?,
                            char_end=?, content_hash=?
                        WHERE segment_id=?
                        """,
                        (
                            segment.ordinal, segment.heading, segment.text,
                            segment.char_start, segment.char_end,
                            segment.content_hash, persistent_id,
                        ),
                    )
                    if str(old["content_hash"]) == segment.content_hash:
                        unchanged_ids.append(persistent_id)
                    else:
                        updated_ids.append(persistent_id)

                concept_ids: list[str] = []
                for name in segment.concepts:
                    current_concept_id = concept_id(name)
                    concept_ids.append(current_concept_id)
                    db.execute(
                        """
                        INSERT OR IGNORE INTO concepts(concept_id,name)
                        VALUES(?,?)
                        """,
                        (current_concept_id, name),
                    )
                    db.execute(
                        "INSERT INTO segment_concepts VALUES(?,?,?,?)",
                        (segment.segment_id, current_concept_id, "mentions", 1.0),
                    )

                db.execute(
                    "INSERT INTO segments_fts VALUES(?,?,?,?)",
                    (
                        segment.segment_id, segment.text,
                        segment.heading or "", " ".join(segment.concepts),
                    ),
                )

            self._rebuild_concept_edges(db)
            db.execute(
                """
                DELETE FROM concepts
                WHERE concept_id NOT IN (SELECT concept_id FROM segment_concepts)
                """
            )

            return {
                "inserted": inserted_ids,
                "updated": updated_ids,
                "unchanged": unchanged_ids,
                "deleted": deleted_ids,
            }

    def replace_document(
        self,
        doc: SourceDocument,
        segments: Sequence[MemorySegment],
        source_kind: str = "file",
    ) -> None:
        """Compatibility wrapper for callers from the initial prototype."""
        self.reconcile_document(doc, segments, source_kind=source_kind)

    @staticmethod
    def _rebuild_concept_edges(db: sqlite3.Connection) -> None:
        db.execute("DELETE FROM concept_edges")
        db.execute(
            """
            INSERT INTO concept_edges(
                source_concept_id, target_concept_id, relation, weight,
                evidence_count
            )
            SELECT
                CASE WHEN a.concept_id < b.concept_id
                     THEN a.concept_id ELSE b.concept_id END,
                CASE WHEN a.concept_id < b.concept_id
                     THEN b.concept_id ELSE a.concept_id END,
                'co_occurs',
                MIN(5.0, 1.0 + (COUNT(*) - 1) * 0.1),
                COUNT(*)
            FROM segment_concepts a
            JOIN segment_concepts b
              ON a.segment_id=b.segment_id
             AND a.concept_id < b.concept_id
            GROUP BY 1, 2
            """
        )

    def delete_source(self, path_or_id: str) -> tuple[bool, list[str]]:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT source_id
                FROM sources
                WHERE source_path=? OR source_id=?
                """,
                (path_or_id, path_or_id),
            ).fetchone()
            if not row:
                return False, []

            source_id = str(row[0])
            segment_ids = [
                str(item[0])
                for item in db.execute(
                    "SELECT segment_id FROM segments WHERE source_id=?",
                    (source_id,),
                )
            ]

            db.executemany(
                "DELETE FROM segments_fts WHERE segment_id=?",
                [(segment_id,) for segment_id in segment_ids],
            )
            db.execute(
                "DELETE FROM sources WHERE source_id=?",
                (source_id,),
            )
            db.execute(
                """
                DELETE FROM concepts
                WHERE concept_id NOT IN (
                    SELECT concept_id FROM segment_concepts
                )
                """
            )
            return True, segment_ids

    def lexical_scores(
        self,
        query: str,
        limit: int = 100,
    ) -> dict[str, float]:
        terms = [
            part
            for part in query.replace('"', " ").split()
            if len(part) > 2
        ]
        if not terms:
            return {}

        match = " OR ".join(f'"{term}"' for term in terms[:20])
        try:
            with self.connect() as db:
                rows = db.execute(
                    """
                    SELECT segment_id, bm25(segments_fts) AS rank
                    FROM segments_fts
                    WHERE segments_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (match, limit),
                ).fetchall()
        except sqlite3.OperationalError:
            return {}

        if not rows:
            return {}

        raw = [-float(row[1]) for row in rows]
        low, high = min(raw), max(raw)
        return {
            str(row[0]): (
                (raw[index] - low) / (high - low)
                if high > low
                else 1.0
            )
            for index, row in enumerate(rows)
        }

    def concepts_for(
        self,
        segment_ids: Sequence[str],
    ) -> dict[str, list[str]]:
        if not segment_ids:
            return {}

        marks = ",".join("?" for _ in segment_ids)
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT sc.segment_id, c.name
                FROM segment_concepts sc
                JOIN concepts c ON c.concept_id=sc.concept_id
                WHERE sc.segment_id IN ({marks})
                """,
                tuple(segment_ids),
            ).fetchall()

        result = {segment_id: [] for segment_id in segment_ids}
        for row in rows:
            result[str(row[0])].append(str(row[1]))
        return result

    def graph_scores(
        self,
        seed_names: Sequence[str],
    ) -> dict[str, float]:
        if not seed_names:
            return {}

        normalized_names = list(dict.fromkeys(seed_names))[:10]
        marks = ",".join("?" for _ in normalized_names)

        with self.connect() as db:
            rows = db.execute(
                f"""
                WITH seed_concepts AS (
                    SELECT concept_id
                    FROM concepts
                    WHERE name IN ({marks})
                ),
                related_concepts AS (
                    SELECT
                        e.target_concept_id AS concept_id,
                        e.weight AS weight
                    FROM concept_edges e
                    JOIN seed_concepts seed
                    ON seed.concept_id = e.source_concept_id

                    UNION ALL

                    SELECT
                        e.source_concept_id AS concept_id,
                        e.weight AS weight
                    FROM concept_edges e
                    JOIN seed_concepts seed
                    ON seed.concept_id = e.target_concept_id

                    UNION ALL

                    SELECT
                        concept_id,
                        5.0 AS weight
                    FROM seed_concepts
                ),
                best_concept_scores AS (
                    SELECT
                        concept_id,
                        MAX(weight) AS weight
                    FROM related_concepts
                    GROUP BY concept_id
                )
                SELECT
                    sc.segment_id,
                    MAX(scores.weight) AS score
                FROM best_concept_scores scores
                JOIN segment_concepts sc
                ON sc.concept_id = scores.concept_id
                GROUP BY sc.segment_id
                LIMIT 5000
                """,
                tuple(normalized_names),
            ).fetchall()

        return {
            str(row[0]): min(1.0, float(row[1]) / 5.0)
            for row in rows
        }

    def source_metadata(
        self,
        segment_ids: Sequence[str],
        *,
        active_only: bool = False,
    ) -> dict[str, dict]:
        if not segment_ids:
            return {}

        marks = ",".join("?" for _ in segment_ids)
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT
                    s.segment_id,
                    s.source_id,
                    s.heading,
                    s.text,
                    s.importance,
                    s.confidence,
                    s.source_quality,
                    s.access_count,
                    s.pinned,
                    s.last_accessed_at,
                    s.memory_state,
                    s.memory_type,
                    s.memory_origin,
                    s.lifecycle_reason,
                    s.state_changed_at,
                    s.promoted_at,
                    s.archived_at,
                    d.source_path,
                    d.title,
                    d.indexed_at
                FROM segments s
                JOIN sources d ON d.source_id=s.source_id
                WHERE s.segment_id IN ({marks})
                  AND (?=0 OR s.memory_state=?)
                """,
                (*segment_ids, 1 if active_only else 0, int(MemoryState.ACTIVE)),
            ).fetchall()

        return {str(row[0]): dict(row) for row in rows}

    def set_segment_weighting(
        self,
        segment_id: str,
        *,
        importance: float | None = None,
        confidence: float | None = None,
        source_quality: float | None = None,
        pinned: bool | None = None,
    ) -> dict:
        updates: list[str] = []
        values: list[object] = []

        for name, value, low, high in (
            ("importance", importance, 0.0, 2.0),
            ("confidence", confidence, 0.0, 1.0),
            ("source_quality", source_quality, 0.0, 1.0),
        ):
            if value is None:
                continue
            numeric = float(value)
            if not low <= numeric <= high:
                raise ValueError(f"{name} must be between {low} and {high}")
            updates.append(f"{name}=?")
            values.append(numeric)

        if pinned is not None:
            updates.append("pinned=?")
            values.append(1 if pinned else 0)

        if not updates:
            raise ValueError("At least one weighting field must be supplied")

        values.append(segment_id)
        with self.connect() as db:
            cursor = db.execute(
                f"UPDATE segments SET {', '.join(updates)} WHERE segment_id=?",
                tuple(values),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Unknown segment: {segment_id}")
            row = db.execute(
                """
                SELECT segment_id, importance, confidence, source_quality,
                       access_count, pinned, last_accessed_at
                FROM segments WHERE segment_id=?
                """,
                (segment_id,),
            ).fetchone()
        result = dict(row)
        result["pinned"] = bool(result["pinned"])
        return result

    def lifecycle_metadata(self, segment_id: str) -> dict:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT segment_id, memory_state, importance, confidence,
                       source_quality, access_count, pinned, last_accessed_at,
                       lifecycle_reason, state_changed_at, promoted_at,
                       archived_at
                FROM segments
                WHERE segment_id=?
                """,
                (segment_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown segment: {segment_id}")
        return dict(row)

    def lifecycle_candidates(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT segment_id, memory_state, importance, confidence,
                       source_quality, access_count, pinned, last_accessed_at,
                       lifecycle_reason, state_changed_at, promoted_at,
                       archived_at
                FROM segments
                WHERE memory_state IN (?, ?) OR pinned=1
                ORDER BY segment_id
                """,
                (int(MemoryState.CANDIDATE), int(MemoryState.ACTIVE)),
            ).fetchall()
        return [dict(row) for row in rows]

    def apply_lifecycle_decision(
        self,
        segment_id: str,
        decision: LifecycleDecision,
        *,
        changed_at: datetime | None = None,
    ) -> dict:
        if not decision.changes_state:
            return self.lifecycle_metadata(segment_id)

        timestamp = (changed_at or datetime.now(timezone.utc)).isoformat()
        promoted_at = (
            timestamp if decision.target_state is MemoryState.ACTIVE else None
        )
        archived_at = (
            timestamp if decision.target_state is MemoryState.ARCHIVED else None
        )

        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE segments
                SET memory_state=?, lifecycle_reason=?, state_changed_at=?,
                    promoted_at=COALESCE(?, promoted_at),
                    archived_at=COALESCE(?, archived_at)
                WHERE segment_id=? AND memory_state=?
                """,
                (
                    int(decision.target_state),
                    int(decision.reason_code),
                    timestamp,
                    promoted_at,
                    archived_at,
                    segment_id,
                    int(decision.current_state),
                ),
            )
            if cursor.rowcount == 0:
                row = db.execute(
                    "SELECT memory_state FROM segments WHERE segment_id=?",
                    (segment_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"Unknown segment: {segment_id}")
                raise RuntimeError(
                    "Lifecycle state changed after evaluation; "
                    "decision was not applied"
                )

        return self.lifecycle_metadata(segment_id)

    def set_segment_lifecycle(
        self,
        segment_id: str,
        *,
        memory_state: int | MemoryState | None = None,
        memory_type: int | MemoryType | None = None,
        memory_origin: int | MemoryOrigin | None = None,
    ) -> dict:
        updates: list[str] = []
        values: list[object] = []

        enum_fields = (
            ("memory_state", memory_state, MemoryState),
            ("memory_type", memory_type, MemoryType),
            ("memory_origin", memory_origin, MemoryOrigin),
        )
        for name, value, enum_type in enum_fields:
            if value is None:
                continue
            member = coerce_enum(enum_type, value)
            updates.append(f"{name}=?")
            values.append(int(member))

        if not updates:
            raise ValueError("At least one lifecycle field must be supplied")

        if memory_state is not None:
            updates.extend(["lifecycle_reason=?", "state_changed_at=?"])
            values.extend([int(LifecycleReason.MANUAL), now()])

        values.append(segment_id)
        with self.connect() as db:
            cursor = db.execute(
                f"UPDATE segments SET {', '.join(updates)} WHERE segment_id=?",
                tuple(values),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Unknown segment: {segment_id}")
            row = db.execute(
                """
                SELECT segment_id, memory_state, memory_type, memory_origin,
                       lifecycle_reason, state_changed_at, promoted_at,
                       archived_at
                FROM segments WHERE segment_id=?
                """,
                (segment_id,),
            ).fetchone()

        result = dict(row)
        result["memory_state_name"] = MemoryState(
            result["memory_state"]
        ).name
        result["memory_type_name"] = MemoryType(
            result["memory_type"]
        ).name
        result["memory_origin_name"] = MemoryOrigin(
            result["memory_origin"]
        ).name
        return result

    def record_access(self, segment_ids: Sequence[str]) -> None:
        if not segment_ids:
            return
        unique_ids = list(dict.fromkeys(segment_ids))
        with self.connect() as db:
            db.executemany(
                """
                UPDATE segments
                SET access_count=access_count+1, last_accessed_at=?
                WHERE segment_id=?
                """,
                [(now(), segment_id) for segment_id in unique_ids],
            )

    def inspect_concept(
        self,
        name: str,
        limit: int = 20,
    ) -> dict:
        with self.connect() as db:
            node = db.execute(
                """
                SELECT concept_id,name,concept_type,importance
                FROM concepts
                WHERE name=? COLLATE NOCASE
                """,
                (name,),
            ).fetchone()
            if not node:
                return {"found": False, "concept": name}

            neighbors = db.execute(
                """
                SELECT
                    CASE
                        WHEN a.concept_id=? THEN b.name
                        ELSE a.name
                    END AS name,
                    e.relation,
                    e.weight,
                    e.evidence_count
                FROM concept_edges e
                JOIN concepts a
                  ON a.concept_id=e.source_concept_id
                JOIN concepts b
                  ON b.concept_id=e.target_concept_id
                WHERE a.concept_id=? OR b.concept_id=?
                ORDER BY e.weight DESC,e.evidence_count DESC
                LIMIT ?
                """,
                (node[0], node[0], node[0], limit),
            ).fetchall()

            segments = db.execute(
                """
                SELECT
                    s.segment_id,
                    d.source_path,
                    s.heading,
                    substr(s.text,1,500) AS excerpt
                FROM segment_concepts sc
                JOIN segments s ON s.segment_id=sc.segment_id
                JOIN sources d ON d.source_id=s.source_id
                WHERE sc.concept_id=?
                LIMIT ?
                """,
                (node[0], limit),
            ).fetchall()

        return {
            "found": True,
            "concept": dict(node),
            "neighbors": [dict(row) for row in neighbors],
            "segments": [dict(row) for row in segments],
        }

    def stats(self) -> dict:
        with self.connect() as db:
            return {
                table: db.execute(
                    f"SELECT count(*) FROM {table}"
                ).fetchone()[0]
                for table in (
                    "sources",
                    "segments",
                    "concepts",
                    "concept_edges",
                )
            }
