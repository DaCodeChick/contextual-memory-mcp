from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

from core.models import PromptSegment, SourceDocument
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

    def replace_document(
        self,
        doc: SourceDocument,
        segments: Sequence[PromptSegment],
        source_kind: str = "file",
    ) -> None:
        with self.connect() as db:
            old = db.execute(
                "SELECT segment_id FROM segments WHERE source_id=?",
                (doc.source_id,),
            ).fetchall()
            db.executemany(
                "DELETE FROM segments_fts WHERE segment_id=?",
                [(row[0],) for row in old],
            )
            db.execute(
                "DELETE FROM sources WHERE source_id=?",
                (doc.source_id,),
            )
            db.execute(
                "INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",
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

            for segment in segments:
                db.execute(
                    "INSERT INTO segments VALUES(?,?,?,?,?,?,?,?)",
                    (
                        segment.segment_id,
                        segment.source_id,
                        segment.ordinal,
                        segment.heading,
                        segment.text,
                        segment.char_start,
                        segment.char_end,
                        segment.importance,
                    ),
                )

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
                        (
                            segment.segment_id,
                            current_concept_id,
                            "mentions",
                            1.0,
                        ),
                    )

                db.execute(
                    "INSERT INTO segments_fts VALUES(?,?,?,?)",
                    (
                        segment.segment_id,
                        segment.text,
                        segment.heading or "",
                        " ".join(segment.concepts),
                    ),
                )

                for index, left in enumerate(concept_ids):
                    for right in concept_ids[index + 1:]:
                        source_id, target_id = sorted((left, right))
                        db.execute(
                            """
                            INSERT INTO concept_edges
                            VALUES(?,?,'co_occurs',1.0,1)
                            ON CONFLICT(
                                source_concept_id,
                                target_concept_id,
                                relation
                            )
                            DO UPDATE SET
                                evidence_count=evidence_count+1,
                                weight=MIN(5.0,1.0+evidence_count*0.1)
                            """,
                            (source_id, target_id),
                        )

            db.execute(
                """
                DELETE FROM concepts
                WHERE concept_id NOT IN (
                    SELECT concept_id FROM segment_concepts
                )
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

        marks = ",".join("?" for _ in seed_names)
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT DISTINCT sc.segment_id, MAX(e.weight) AS score
                FROM concepts seed
                JOIN concept_edges e
                  ON seed.concept_id IN (
                    e.source_concept_id,
                    e.target_concept_id
                  )
                JOIN segment_concepts sc
                  ON sc.concept_id IN (
                    e.source_concept_id,
                    e.target_concept_id
                  )
                WHERE seed.name IN ({marks})
                GROUP BY sc.segment_id
                """,
                tuple(seed_names),
            ).fetchall()

        return {
            str(row[0]): min(1.0, float(row[1]) / 5.0)
            for row in rows
        }

    def source_metadata(
        self,
        segment_ids: Sequence[str],
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
                    d.source_path,
                    d.title,
                    d.indexed_at
                FROM segments s
                JOIN sources d ON d.source_id=s.source_id
                WHERE s.segment_id IN ({marks})
                """,
                tuple(segment_ids),
            ).fetchall()

        return {str(row[0]): dict(row) for row in rows}

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
