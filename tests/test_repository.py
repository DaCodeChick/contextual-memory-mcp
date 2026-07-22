from pathlib import Path

from core.models import PromptSegment, SourceDocument
from database.repositories import SQLiteRepository


def make_segment(text: str, content_hash: str = "hash-1") -> PromptSegment:
    return PromptSegment(
        "seg_1",
        "src_1",
        0,
        "Rules",
        text,
        0,
        len(text),
        "section:0:chunk:0",
        content_hash,
        1.4,
        ["identity"],
    )


def test_round_trip(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "memory.sqlite3")
    repo.initialize()
    doc = SourceDocument(
        "src_1", Path("a.md"), "a.md", "A", "hello", "hash", 0, 5
    )
    repo.reconcile_document(doc, [make_segment("Preserve identity")])
    assert repo.stats()["sources"] == 1
    assert repo.concepts_for(["seg_1"])["seg_1"] == ["identity"]


def test_reconcile_preserves_segment_id_across_content_change(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "memory.sqlite3")
    repo.initialize()
    doc = SourceDocument(
        "src_1", Path("a.md"), "a.md", "A", "hello", "hash", 0, 5
    )
    repo.reconcile_document(doc, [make_segment("Preserve identity")])

    changed = make_segment("Always preserve identity", "hash-2")
    changed.segment_id = "newly-generated-id"
    result = repo.reconcile_document(doc, [changed])

    assert result["updated"] == ["seg_1"]
    assert changed.segment_id == "seg_1"
    metadata = repo.source_metadata(["seg_1"])["seg_1"]
    assert metadata["text"] == "Always preserve identity"
