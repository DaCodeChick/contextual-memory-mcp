from pathlib import Path

from core.models import PromptSegment, SourceDocument
from database.repositories import SQLiteRepository


def test_round_trip(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "memory.sqlite3")
    repo.initialize()
    doc = SourceDocument("src_1", Path("a.md"), "a.md", "A", "hello", "hash", 0, 5)
    segment = PromptSegment("seg_1", "src_1", 0, "Rules", "Preserve identity", 0, 17, 1.4, ["identity"])
    repo.replace_document(doc, [segment])
    assert repo.stats()["sources"] == 1
    assert repo.concepts_for(["seg_1"])["seg_1"] == ["identity"]
