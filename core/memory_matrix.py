from __future__ import annotations

from dataclasses import replace
from functools import cached_property
from pathlib import Path
from typing import Iterable

from core.config import Settings
from core.context_builder import ContextBuilder
from core.importance import ImportancePolicy
from core.importance_service import ImportanceRunResult, ImportanceService
from core.ingestion_service import IngestionService
from core.lifecycle import LifecyclePolicy
from core.lifecycle_service import LifecycleRunResult, LifecycleService
from core.models import SearchHit
from core.retrieval_engine import RetrievalEngine
from core.stores import (
    MemoryRef,
    MemoryStoreConfig,
    StoreMode,
    StoreRegistry,
    load_store_manifest,
)
from database.migrations import MIGRATIONS
from database.repositories import SQLiteRepository
from database.vector_memory import VectorMemory
from providers.embeddings import SentenceTransformerProvider


class StoreAccessError(PermissionError):
    pass


class MemoryStoreRuntime:
    """One independently persisted memory store."""

    def __init__(self, settings: Settings, config: MemoryStoreConfig) -> None:
        self.settings = settings
        self.config = config
        if config.mode == StoreMode.READ_WRITE:
            config.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            config.chroma_path.mkdir(parents=True, exist_ok=True)
        elif not config.sqlite_path.exists():
            raise FileNotFoundError(
                f"Locked memory store database does not exist: {config.sqlite_path}"
            )

        self.repository = SQLiteRepository(
            config.sqlite_path,
            read_only=config.mode != StoreMode.READ_WRITE,
            immutable=config.mode == StoreMode.IMMUTABLE,
        )
        if config.mode == StoreMode.READ_WRITE:
            self.repository.initialize()
        else:
            self._validate_locked_schema()

    def _validate_locked_schema(self) -> None:
        import sqlite3
        with sqlite3.connect(f"file:{self.config.sqlite_path}?mode=ro", uri=True) as db:
            row = db.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()
        actual = int(row[0] or 0)
        expected = MIGRATIONS[-1][0]
        if actual != expected:
            raise RuntimeError(
                f"Store {self.config.store_id!r} has schema version {actual}; "
                f"expected {expected}. Locked stores are never migrated automatically."
            )

    def require_writable(self) -> None:
        if self.config.mode != StoreMode.READ_WRITE:
            raise StoreAccessError(
                f"Memory store {self.config.store_id!r} is {self.config.mode.name}"
            )

    @cached_property
    def embedder(self) -> SentenceTransformerProvider:
        return SentenceTransformerProvider(self.settings.embedding_model)

    @cached_property
    def vectors(self) -> VectorMemory:
        return VectorMemory(
            self.config.chroma_path,
            self.config.collection_name,
            self.embedder,
        )

    @cached_property
    def ingestion(self) -> IngestionService:
        self.require_writable()
        return IngestionService(self.settings, self.repository, self.vectors)

    @cached_property
    def retrieval(self) -> RetrievalEngine:
        return RetrievalEngine(self.settings, self.repository, self.vectors)

    @cached_property
    def lifecycle(self) -> LifecycleService:
        self.require_writable()
        policy = LifecyclePolicy(
            promotion_importance=self.settings.lifecycle_promotion_importance,
            promotion_access_count=self.settings.lifecycle_promotion_access_count,
            minimum_confidence=self.settings.lifecycle_minimum_confidence,
            minimum_source_quality=self.settings.lifecycle_minimum_source_quality,
            archive_importance=self.settings.lifecycle_archive_importance,
            archive_after_days=self.settings.lifecycle_archive_after_days,
        )
        return LifecycleService(self.repository, policy)

    @cached_property
    def importance(self) -> ImportanceService:
        self.require_writable()
        policy = ImportancePolicy(
            access_gain=self.settings.importance_access_gain,
            decay_per_30_days=self.settings.importance_decay_per_30_days,
            decay_grace_days=self.settings.importance_decay_grace_days,
            minimum_importance=self.settings.importance_minimum,
            maximum_importance=self.settings.importance_maximum,
        )
        return ImportanceService(self.repository, policy)

    def run_importance(self, *, apply: bool = True) -> ImportanceRunResult:
        self.require_writable()
        result = self.importance.run(apply=apply)
        if apply:
            for segment_id in result.changed_segment_ids:
                metadata = self.repository.source_metadata([segment_id])[segment_id]
                self.vectors.update_weighting(segment_id, importance=float(metadata["importance"]))
        return result

    def run_lifecycle(self, *, apply: bool = True) -> LifecycleRunResult:
        self.require_writable()
        result = self.lifecycle.run(apply=apply)
        if apply:
            for segment_id in result.changed_segment_ids:
                metadata = self.repository.lifecycle_metadata(segment_id)
                self.vectors.update_lifecycle(
                    segment_id,
                    memory_state=int(metadata["memory_state"]),
                    memory_type=int(metadata["memory_type"]),
                    memory_origin=int(metadata["memory_origin"]),
                )
        return result


class FederatedRetrievalEngine:
    def __init__(self, matrix: "ContextualMemoryMatrix") -> None:
        self.matrix = matrix

    def search(
        self,
        query: str,
        top_k: int | None = None,
        *,
        record_access: bool = True,
        stores: list[str] | None = None,
    ) -> list[SearchHit]:
        requested = max(1, min(top_k or self.matrix.settings.default_top_k, 50))
        selected_configs = self.matrix.selected_store_configs(stores)
        candidates: list[SearchHit] = []

        for config in selected_configs:
            runtime = self.matrix.store(config.store_id)
            local_hits = runtime.retrieval.search(
                query, max(requested * 3, 12), record_access=False
            )
            overlays = self.matrix.registry.overlays(
                config.store_id, [hit.segment_id for hit in local_hits]
            )
            for hit in local_hits:
                overlay = overlays.get(hit.segment_id, {})
                if bool(overlay.get("hidden", 0)):
                    continue
                local_boost = float(overlay.get("local_boost", 0.0))
                pinned_override = overlay.get("pinned_override")
                if pinned_override is not None:
                    hit.pinned = bool(pinned_override)
                hit.store_id = config.store_id
                hit.store_priority = config.priority
                hit.score = hit.score * config.priority + local_boost
                hit.metadata.update(
                    {
                        "store_id": config.store_id,
                        "store_mode": int(config.mode),
                        "store_mode_name": config.mode.name,
                        "store_priority": config.priority,
                        "local_boost": local_boost,
                    }
                )
                candidates.append(hit)

        candidates.sort(key=lambda hit: hit.score, reverse=True)
        chosen = candidates[:requested]
        if record_access:
            grouped: dict[str, list[str]] = {}
            for hit in chosen:
                grouped.setdefault(hit.store_id, []).append(hit.segment_id)
            for store_id, ids in grouped.items():
                config = self.matrix.registry.get(store_id)
                if config.mode == StoreMode.READ_WRITE:
                    self.matrix.store(store_id).repository.record_access(ids)
                else:
                    self.matrix.registry.record_external_access(store_id, ids)
        return chosen

    def inspect_concept(self, store_id: str, concept: str, limit: int) -> dict:
        return self.matrix.store(store_id).repository.inspect_concept(concept, limit)

    def explain(
        self, query: str, top_k: int | None = None, stores: list[str] | None = None
    ) -> list[dict]:
        return [
            {
                "memory_ref": hit.memory_ref,
                "store_id": hit.store_id,
                "segment_id": hit.segment_id,
                "source_path": hit.source_path,
                "title": hit.title,
                "heading": hit.heading,
                "score": hit.score,
                "store_priority": hit.store_priority,
                "weights": {
                    "importance": hit.importance,
                    "confidence": hit.confidence,
                    "source_quality": hit.source_quality,
                    "access_count": hit.access_count,
                    "pinned": hit.pinned,
                    "memory_state": int(hit.memory_state),
                    "memory_type": int(hit.memory_type),
                    "memory_origin": int(hit.memory_origin),
                },
                "ranking": hit.metadata["ranking"],
            }
            for hit in self.search(query, top_k, record_access=False, stores=stores)
        ]


class ContextualMemoryMatrix:
    """Federated facade over one or more persistent memory stores."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.settings.prepare()
        self.registry = StoreRegistry(self.settings.store_registry_path)
        self._runtimes: dict[str, MemoryStoreRuntime] = {}

        self.registry.upsert(
            MemoryStoreConfig(
                store_id="main",
                display_name="Main Memory",
                sqlite_path=self.settings.sqlite_path,
                chroma_path=self.settings.chroma_path,
                collection_name=self.settings.collection_name,
                mode=StoreMode.READ_WRITE,
                enabled=True,
                priority=1.0,
            )
        )
        if self.settings.stores_file is not None:
            for config in load_store_manifest(
                self.settings.stores_file, self.settings.stores_file.parent
            ):
                if config.store_id != "main":
                    self.registry.upsert(config)
        self.store("main")

    def store(self, store_id: str) -> MemoryStoreRuntime:
        if store_id not in self._runtimes:
            self._runtimes[store_id] = MemoryStoreRuntime(
                self.settings, self.registry.get(store_id)
            )
        return self._runtimes[store_id]

    def selected_store_configs(self, stores: list[str] | None = None) -> list[MemoryStoreConfig]:
        configs = [config for config in self.registry.list() if config.enabled]
        if stores is not None:
            wanted = set(stores)
            unknown = wanted - {config.store_id for config in configs}
            if unknown:
                raise KeyError(f"Unknown or disabled memory stores: {sorted(unknown)}")
            configs = [config for config in configs if config.store_id in wanted]
        return configs

    @cached_property
    def retrieval(self) -> FederatedRetrievalEngine:
        return FederatedRetrievalEngine(self)

    @cached_property
    def context(self) -> ContextBuilder:
        return ContextBuilder(self.settings, self.retrieval)

    def remember(self, *, target_store: str, **kwargs) -> dict:
        store_id = target_store
        result = self.store(store_id).ingestion.remember(**kwargs)
        return {"store_id": store_id, **result}

    def scan(self, directory: Path, *, target_store: str, **kwargs) -> dict:
        store_id = target_store
        result = self.store(store_id).ingestion.scan(directory, **kwargs)
        return {"store_id": store_id, **result}

    def update_lifecycle(self, memory_ref: str, **kwargs) -> dict:
        ref = MemoryRef.parse(memory_ref)
        runtime = self.store(ref.store_id)
        runtime.require_writable()
        result = runtime.repository.set_segment_lifecycle(ref.segment_id, **kwargs)
        runtime.vectors.update_lifecycle(
            ref.segment_id,
            memory_state=result["memory_state"],
            memory_type=result["memory_type"],
            memory_origin=result["memory_origin"],
        )
        return {"memory_ref": str(ref), "store_id": ref.store_id, **result}

    def update_weighting(self, memory_ref: str, **kwargs) -> dict:
        ref = MemoryRef.parse(memory_ref)
        runtime = self.store(ref.store_id)
        if runtime.config.mode == StoreMode.READ_WRITE:
            result = runtime.repository.set_segment_weighting(ref.segment_id, **kwargs)
            if kwargs.get("importance") is not None:
                runtime.vectors.update_weighting(
                    ref.segment_id, importance=float(result["importance"])
                )
            return {"memory_ref": str(ref), "store_id": ref.store_id, **result}
        allowed = {"local_boost", "hidden", "pinned_override"}
        invalid = set(kwargs) - allowed
        if invalid:
            raise StoreAccessError(
                f"Locked stores only support overlay fields: {sorted(allowed)}"
            )
        result = self.registry.set_overlay(ref.store_id, ref.segment_id, **kwargs)
        return {"memory_ref": str(ref), "store_id": ref.store_id, **result}

    def run_importance(self, *, apply: bool = True, store_id: str) -> ImportanceRunResult:
        runtime = self.store(store_id)
        runtime.require_writable()
        result = runtime.importance.run(apply=apply)
        vectors = runtime.vectors
        if apply:
            for segment_id in result.changed_segment_ids:
                metadata = runtime.repository.source_metadata([segment_id])[segment_id]
                vectors.update_weighting(segment_id, importance=float(metadata["importance"]))
        return result

    def run_lifecycle(self, *, apply: bool = True, store_id: str) -> LifecycleRunResult:
        runtime = self.store(store_id)
        runtime.require_writable()
        result = runtime.lifecycle.run(apply=apply)
        vectors = runtime.vectors
        if apply:
            for segment_id in result.changed_segment_ids:
                metadata = runtime.repository.lifecycle_metadata(segment_id)
                vectors.update_lifecycle(
                    segment_id,
                    memory_state=int(metadata["memory_state"]),
                    memory_type=int(metadata["memory_type"]),
                    memory_origin=int(metadata["memory_origin"]),
                )
        return result

    def run_maintenance(self, *, apply: bool = True, stores: list[str] | None = None) -> dict:
        results: dict[str, dict] = {}
        for config in self.selected_store_configs(stores):
            if config.mode != StoreMode.READ_WRITE:
                results[config.store_id] = {"skipped": True, "reason": config.mode.name}
                continue
            results[config.store_id] = {
                "importance": self.run_importance(apply=apply, store_id=config.store_id),
                "lifecycle": self.run_lifecycle(apply=apply, store_id=config.store_id),
            }
        return results

    def mount_store(self, config: MemoryStoreConfig) -> dict:
        if config.store_id == "main":
            raise ValueError("Use main configuration for the main store")
        self.registry.upsert(config)
        self._runtimes.pop(config.store_id, None)
        self.store(config.store_id)
        return config.as_dict()

    def unmount_store(self, store_id: str) -> bool:
        self._runtimes.pop(store_id, None)
        return self.registry.remove(store_id)

    def set_store_enabled(self, store_id: str, enabled: bool) -> dict:
        config = self.registry.set_enabled(store_id, enabled)
        return config.as_dict()

    def list_stores(self) -> list[dict]:
        return [config.as_dict() for config in self.registry.list()]

    def clear(self, store_id: str) -> dict:
        runtime = self.store(store_id)
        runtime.require_writable()
        vector_count = runtime.vectors.count()
        sqlite_counts = runtime.repository.stats()
        runtime.vectors.clear()
        runtime.repository.clear()
        return {
            "cleared": True,
            "store_id": store_id,
            "deleted": {**sqlite_counts, "vectors": vector_count},
        }

    def stats(self) -> dict:
        stores: dict[str, dict] = {}
        for config in self.registry.list():
            if not config.enabled:
                continue
            runtime = self.store(config.store_id)
            data = runtime.repository.stats()
            data.update(config.as_dict())
            try:
                data["vectors"] = runtime.vectors.count()
            except Exception:
                data["vectors"] = None
            stores[config.store_id] = data
        return {"stores": stores}
