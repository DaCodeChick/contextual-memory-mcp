import sys
import types
from pathlib import Path

chromadb = types.ModuleType("chromadb")
chromadb.PersistentClient = object  # type: ignore[attr-defined]
sys.modules.setdefault("chromadb", chromadb)

sentence_transformers = types.ModuleType("sentence_transformers")
sentence_transformers.SentenceTransformer = object  # type: ignore[attr-defined]
sys.modules.setdefault("sentence_transformers", sentence_transformers)

from core.config import Settings
from core.enums import MemoryState
from core.memory_matrix import ContextualMemoryMatrix
from core.models import MemorySegment, SourceDocument


class FakeVectors:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def update_lifecycle(self, segment_id: str, **metadata: int) -> None:
        self.updates.append({"segment_id": segment_id, **metadata})


def test_matrix_uses_configured_policy_and_syncs_vector_metadata(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        lifecycle_promotion_importance=1.9,
    )
    matrix = ContextualMemoryMatrix(settings)
    fake_vectors = FakeVectors()
    matrix.store("main").__dict__["vectors"] = fake_vectors

    doc = SourceDocument(
        "source",
        Path("memory.md"),
        "memory.md",
        "memory",
        "content",
        "hash",
        0,
        7,
    )
    segment = MemorySegment(
        segment_id="candidate",
        source_id=doc.source_id,
        ordinal=0,
        heading=None,
        text="content",
        char_start=0,
        char_end=7,
        identity_key="memory",
        content_hash="hash",
        importance=1.8,
        memory_state=MemoryState.CANDIDATE,
    )
    matrix.store("main").repository.reconcile_document(doc, [segment], source_kind="memory")

    first = matrix.run_lifecycle(store_id="main")
    assert first.changed == 0
    assert fake_vectors.updates == []

    matrix.store("main").repository.set_segment_weighting("candidate", importance=2.0)
    second = matrix.run_lifecycle(store_id="main")

    assert second.changed_segment_ids == ("candidate",)
    assert fake_vectors.updates == [
        {
            "segment_id": "candidate",
            "memory_state": int(MemoryState.ACTIVE),
            "memory_type": 0,
            "memory_origin": 0,
        }
    ]
