from __future__ import annotations

from pathlib import Path

import pytest

from core.config import Settings
from core.enums import MemoryOrigin, MemoryState, MemoryType
from core.memory_matrix import ContextualMemoryMatrix, StoreAccessError
from core.models import SearchHit
from core.stores import MemoryRef, MemoryStoreConfig, StoreMode, StoreRegistry
from database.repositories import SQLiteRepository


def make_locked_store(tmp_path: Path, store_id: str = "reference") -> MemoryStoreConfig:
    root = tmp_path / store_id
    sqlite_path = root / "memory.sqlite3"
    chroma_path = root / "chroma"
    root.mkdir(parents=True)
    chroma_path.mkdir()
    SQLiteRepository(sqlite_path).initialize()
    return MemoryStoreConfig(
        store_id=store_id,
        display_name="Reference Store",
        sqlite_path=sqlite_path,
        chroma_path=chroma_path,
        mode=StoreMode.IMMUTABLE,
        priority=1.25,
    )


def test_memory_ref_requires_store_qualification_and_round_trips() -> None:
    with pytest.raises(ValueError):
        MemoryRef.parse("seg_1")
    assert str(MemoryRef.parse("ghidra:seg_2")) == "ghidra:seg_2"


def test_registry_persists_integer_modes_and_overlays(tmp_path: Path) -> None:
    registry = StoreRegistry(tmp_path / "registry.sqlite3")
    config = make_locked_store(tmp_path)
    registry.upsert(config)

    loaded = registry.get("reference")
    assert loaded.mode is StoreMode.IMMUTABLE
    assert loaded.priority == 1.25

    overlay = registry.set_overlay(
        "reference", "segment", local_boost=0.4, hidden=True,
        pinned_override=True,
    )
    assert overlay["local_boost"] == 0.4
    assert overlay["hidden"] == 1
    assert overlay["pinned_override"] == 1


def test_locked_store_rejects_writes_and_is_skipped_by_maintenance(
    tmp_path: Path,
) -> None:
    matrix = ContextualMemoryMatrix(Settings(data_dir=tmp_path / "main"))
    config = make_locked_store(tmp_path)
    matrix.mount_store(config)

    with pytest.raises(StoreAccessError):
        matrix.remember(
            target_store="reference",
            title="No write",
            text="This must be rejected",
            memory_type=2,
            importance=0.5,
            memory_origin=MemoryOrigin.EXPLICIT_USER,
        )

    result = matrix.run_maintenance(apply=False, stores=["reference"])
    assert result["reference"] == {"skipped": True, "reason": "IMMUTABLE"}


def test_locked_store_weight_changes_use_registry_overlay(tmp_path: Path) -> None:
    matrix = ContextualMemoryMatrix(Settings(data_dir=tmp_path / "main"))
    matrix.mount_store(make_locked_store(tmp_path))

    result = matrix.update_weighting(
        "reference:segment", local_boost=0.75, hidden=False,
        pinned_override=True,
    )
    assert result["memory_ref"] == "reference:segment"
    assert result["local_boost"] == 0.75
    assert result["pinned_override"] == 1

    with pytest.raises(StoreAccessError):
        matrix.update_weighting("reference:segment", importance=2.0)


class FakeRetrieval:
    def __init__(self, hit: SearchHit) -> None:
        self.hit = hit

    def search(self, query: str, top_k: int, *, record_access: bool) -> list[SearchHit]:
        return [self.hit]


class FakeRepository:
    def __init__(self) -> None:
        self.accesses: list[str] = []

    def record_access(self, ids: list[str]) -> None:
        self.accesses.extend(ids)


class FakeRuntime:
    def __init__(self, hit: SearchHit) -> None:
        self.retrieval = FakeRetrieval(hit)
        self.repository = FakeRepository()


def make_hit(segment_id: str, score: float) -> SearchHit:
    return SearchHit(
        segment_id=segment_id,
        source_id=f"source-{segment_id}",
        source_path=f"memory://{segment_id}",
        title=segment_id,
        heading=None,
        text="memory",
        score=score,
        vector_score=score,
        lexical_score=0.0,
        graph_score=0.0,
        importance=1.0,
        confidence=1.0,
        source_quality=1.0,
        access_count=0,
        pinned=False,
        memory_state=MemoryState.ACTIVE,
        memory_type=MemoryType.FACT,
        memory_origin=MemoryOrigin.EXPLICIT_USER,
        concepts=[],
        store_id="main",
        store_priority=1.0,
        metadata={"ranking": {"score": score}},
    )


def test_federated_retrieval_qualifies_ids_and_applies_store_priority(
    tmp_path: Path,
) -> None:
    matrix = ContextualMemoryMatrix(Settings(data_dir=tmp_path / "main"))
    config = make_locked_store(tmp_path)
    matrix.registry.upsert(config)

    matrix._runtimes["main"] = FakeRuntime(make_hit("main-hit", 0.8))  # type: ignore[assignment]
    matrix._runtimes["reference"] = FakeRuntime(make_hit("locked-hit", 0.7))  # type: ignore[assignment]

    hits = matrix.retrieval.search("query", top_k=2)
    assert [hit.memory_ref for hit in hits] == [
        "reference:locked-hit",
        "main:main-hit",
    ]
    assert hits[0].score == pytest.approx(0.875)

    overlay = matrix.registry.overlays("reference", ["locked-hit"])
    assert overlay["locked-hit"]["access_count"] == 1
    main_runtime = matrix._runtimes["main"]
    assert main_runtime.repository.accesses == ["main-hit"]  # type: ignore[attr-defined]


def test_main_store_cannot_be_unmounted(tmp_path: Path) -> None:
    matrix = ContextualMemoryMatrix(Settings(data_dir=tmp_path))
    with pytest.raises(ValueError):
        matrix.unmount_store("main")


def test_store_can_be_disabled_but_main_cannot(tmp_path: Path) -> None:
    matrix = ContextualMemoryMatrix(Settings(data_dir=tmp_path / "main"))
    matrix.mount_store(make_locked_store(tmp_path))
    result = matrix.set_store_enabled("reference", False)
    assert result["enabled"] is False
    assert [item.store_id for item in matrix.selected_store_configs()] == ["main"]
    with pytest.raises(ValueError):
        matrix.set_store_enabled("main", False)


def test_scan_store_id_uses_directory_name_and_normalizes_explicit_name(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "My Project"
    directory.mkdir()
    assert ContextualMemoryMatrix._scan_store_id(directory, None) == "My-Project"
    assert ContextualMemoryMatrix._scan_store_id(directory, "  Custom Database  ") == "Custom-Database"


def test_scan_creates_immutable_named_store_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    matrix = ContextualMemoryMatrix(Settings(data_dir=tmp_path / "data"))

    class FakeIngestion:
        def scan(self, directory: Path, **kwargs: object) -> dict:
            assert directory == source.resolve()
            return {"discovered": 0, "indexed": 0, "segments": 0}

    class FakeRuntime:
        ingestion = FakeIngestion()

    monkeypatch.setattr(matrix, "store", lambda store_id: FakeRuntime())
    result = matrix.scan(source, name="Reference DB")

    assert result["store_id"] == "Reference-DB"
    assert result["mutable"] is False
    assert result["mode_name"] == "IMMUTABLE"
    assert matrix.registry.get("Reference-DB").mode is StoreMode.IMMUTABLE


def test_scan_mutable_and_replace_are_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    matrix = ContextualMemoryMatrix(Settings(data_dir=tmp_path / "data"))

    class FakeIngestion:
        def scan(self, directory: Path, **kwargs: object) -> dict:
            return {"discovered": 0, "indexed": 0, "segments": 0}

    class FakeRuntime:
        ingestion = FakeIngestion()

    monkeypatch.setattr(matrix, "store", lambda store_id: FakeRuntime())
    first = matrix.scan(source, mutable=True)
    assert first["mode_name"] == "READ_WRITE"

    with pytest.raises(FileExistsError):
        matrix.scan(source, mutable=True)

    replaced = matrix.scan(source, mutable=True, replace=True)
    assert replaced["store_id"] == "source"
    assert matrix.registry.get("source").mode is StoreMode.READ_WRITE
