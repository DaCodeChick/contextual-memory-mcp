from __future__ import annotations

from dataclasses import replace as dataclass_replace
from functools import cached_property
from pathlib import Path
import re
import shutil
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
from core.web_acquisition import WebAcquisitionService
from core.stores import (
    MemoryRef,
    MemoryStoreConfig,
    StoreMode,
    StoreOverlays,
    discover_store_manifests,
    write_store_manifest,
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
    def web_acquisition(self) -> WebAcquisitionService:
        self.require_writable()
        return WebAcquisitionService(self.ingestion, settings=self.settings)

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
            overlays = self.matrix.overlays.overlays(
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
                config = self.matrix.store_config(store_id)
                if config.mode == StoreMode.READ_WRITE:
                    self.matrix.store(store_id).repository.record_access(ids)
                else:
                    self.matrix.overlays.record_external_access(store_id, ids)
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
        self.overlays = StoreOverlays(self.settings.overlays_path)
        self._runtimes: dict[str, MemoryStoreRuntime] = {}
        self.store("main")

    def _main_config(self) -> MemoryStoreConfig:
        return MemoryStoreConfig(
            store_id="main",
            display_name="Main Memory",
            sqlite_path=self.settings.sqlite_path,
            chroma_path=self.settings.chroma_path,
            collection_name=self.settings.collection_name,
            mode=StoreMode.READ_WRITE,
            enabled=True,
            priority=1.0,
        )

    def store_configs(self) -> list[MemoryStoreConfig]:
        configs = [self._main_config(), *discover_store_manifests(self.settings.stores_dir)]
        seen: set[str] = set()
        result: list[MemoryStoreConfig] = []
        for config in configs:
            if config.store_id in seen:
                raise ValueError(f"Duplicate memory store ID discovered: {config.store_id!r}")
            seen.add(config.store_id)
            result.append(config)
        return result

    def store_config(self, store_id: str) -> MemoryStoreConfig:
        for config in self.store_configs():
            if config.store_id == store_id:
                return config
        raise KeyError(f"Unknown memory store: {store_id}")

    def store(self, store_id: str) -> MemoryStoreRuntime:
        if store_id not in self._runtimes:
            self._runtimes[store_id] = MemoryStoreRuntime(
                self.settings, self.store_config(store_id)
            )
        return self._runtimes[store_id]

    def selected_store_configs(self, stores: list[str] | None = None) -> list[MemoryStoreConfig]:
        configs = [config for config in self.store_configs() if config.enabled]
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

    @staticmethod
    def _scan_store_id(target: Path, name: str | None) -> str:
        raw = (name if name is not None else target.expanduser().resolve().name).strip()
        if not raw:
            raise ValueError("The scan database name cannot be empty")
        store_id = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-._")
        if not store_id:
            raise ValueError(f"Invalid scan database name: {raw!r}")
        return store_id

    def _create_named_store(
        self, store_id: str, *, display_name: str, mutable: bool
    ) -> tuple[MemoryStoreConfig, Path]:
        if store_id == "main":
            return self._main_config(), self.settings.data_dir
        store_root = self.settings.data_dir / "stores" / store_id
        sqlite_path = store_root / f"{store_id}.sqlite3"
        chroma_path = store_root / "chroma"
        config = MemoryStoreConfig(
            store_id=store_id,
            display_name=display_name,
            sqlite_path=sqlite_path,
            chroma_path=chroma_path,
            collection_name=self.settings.collection_name,
            mode=StoreMode.READ_WRITE,
            enabled=True,
            priority=1.0,
            specialty="indexed-source",
        )
        self._runtimes[store_id] = MemoryStoreRuntime(self.settings, config)
        return config, store_root

    def scan(
        self,
        target: Path,
        *,
        name: str | None = None,
        mutable: bool = False,
        replace: bool = False,
        **kwargs,
    ) -> dict:
        resolved = target.expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Scan target does not exist: {resolved}")

        # No explicit database means the normal writable default store.
        store_id = self._scan_store_id(resolved, name) if name else "main"
        display_name = name.strip() if name else "Main Memory"
        existing = None
        try:
            existing = self.store_config(store_id)
        except KeyError:
            pass

        if replace and store_id == "main":
            raise ValueError("The default main store cannot be replaced by scan")
        if replace and existing is not None:
            self._runtimes.pop(store_id, None)
            store_root = self.settings.data_dir / "stores" / store_id
            shutil.rmtree(store_root, ignore_errors=True)
            existing = None

        created = existing is None
        original_mode = existing.mode if existing is not None else None
        if existing is None:
            build_config, store_root = self._create_named_store(
                store_id, display_name=display_name, mutable=mutable
            )
        elif existing.mode == StoreMode.READ_WRITE:
            build_config = existing
            store_root = (
                self.settings.data_dir
                if store_id == "main"
                else self.settings.data_dir / "stores" / store_id
            )
        else:
            # Temporarily reopen an indexed store for an explicit update, then
            # restore its locked mode after ingestion.
            self._runtimes.pop(store_id, None)
            build_config = dataclass_replace(existing, mode=StoreMode.READ_WRITE)
            store_root = self.settings.data_dir / "stores" / store_id
            self._runtimes[store_id] = MemoryStoreRuntime(self.settings, build_config)

        runtime = self.store(store_id) if store_id == "main" else self._runtimes[store_id]
        try:
            if resolved.is_file():
                result = runtime.ingestion.ingest_file(
                    resolved, force=bool(kwargs.get("force", False))
                )
                result.update({"target": str(resolved), "kind": "file", "discovered": 1})
            elif resolved.is_dir():
                result = runtime.ingestion.scan(
                    resolved,
                    force=bool(kwargs.get("force", False)),
                    excludes=kwargs.get("excludes"),
                )
                result["target"] = str(resolved)
                result["kind"] = "directory"
            else:
                raise ValueError(f"Unsupported scan target: {resolved}")
        except Exception:
            if created and store_id != "main":
                self._runtimes.pop(store_id, None)
                shutil.rmtree(store_root, ignore_errors=True)
            raise

        if store_id == "main":
            final_mode = StoreMode.READ_WRITE
        elif original_mode is not None:
            final_mode = original_mode
        else:
            final_mode = StoreMode.READ_WRITE if mutable else StoreMode.IMMUTABLE

        if store_id != "main":
            final_config = dataclass_replace(build_config, mode=final_mode)
            write_store_manifest(store_root, final_config)
            self._runtimes.pop(store_id, None)
        else:
            final_config = self._main_config()

        return {
            "store_id": store_id,
            "name": final_config.display_name,
            "created": created,
            "mutable": final_mode == StoreMode.READ_WRITE,
            "mode": int(final_mode),
            "mode_name": final_mode.name,
            **result,
        }

    def _prepare_ingestion_store(
        self,
        *,
        source_name: str,
        name: str | None,
        mutable: bool,
        replace: bool,
    ):
        store_id = self._scan_store_id(Path(source_name), name) if name else "main"
        display_name = name.strip() if name else "Main Memory"
        try:
            existing = self.store_config(store_id)
        except KeyError:
            existing = None
        if replace and store_id == "main":
            raise ValueError("The default main store cannot be replaced")
        if replace and existing is not None:
            self._runtimes.pop(store_id, None)
            shutil.rmtree(self.settings.data_dir / "stores" / store_id, ignore_errors=True)
            existing = None
        created = existing is None
        original_mode = existing.mode if existing is not None else None
        if existing is None:
            config, root = self._create_named_store(store_id, display_name=display_name, mutable=mutable)
        elif existing.mode == StoreMode.READ_WRITE:
            config = existing
            root = self.settings.data_dir if store_id == "main" else self.settings.data_dir / "stores" / store_id
        else:
            self._runtimes.pop(store_id, None)
            config = dataclass_replace(existing, mode=StoreMode.READ_WRITE)
            root = self.settings.data_dir / "stores" / store_id
            self._runtimes[store_id] = MemoryStoreRuntime(self.settings, config)
        runtime = self.store(store_id) if store_id == "main" else self._runtimes[store_id]
        return store_id, display_name, created, original_mode, config, root, runtime

    def _finish_ingestion_store(self, store_id, created, original_mode, config, root, mutable):
        if store_id == "main":
            final_mode = StoreMode.READ_WRITE
            final_config = self._main_config()
        else:
            final_mode = original_mode if original_mode is not None else (StoreMode.READ_WRITE if mutable else StoreMode.IMMUTABLE)
            final_config = dataclass_replace(config, mode=final_mode)
            write_store_manifest(root, final_config)
            self._runtimes.pop(store_id, None)
        return {
            "store_id": store_id,
            "name": final_config.display_name,
            "created": created,
            "mutable": final_mode == StoreMode.READ_WRITE,
            "mode": int(final_mode),
            "mode_name": final_mode.name,
        }

    def scan_url(self, url: str, *, name: str | None = None, mutable: bool = False, replace: bool = False, force: bool = False) -> dict:
        parsed_name = re.sub(r"[^A-Za-z0-9._-]+", "-", url).strip("-._")[:80] or "web"
        prepared = self._prepare_ingestion_store(source_name=parsed_name, name=name, mutable=mutable, replace=replace)
        store_id, _, created, original_mode, config, root, runtime = prepared
        try:
            result = runtime.web_acquisition.ingest_url(url, force=force)
        except Exception:
            if created and store_id != "main":
                self._runtimes.pop(store_id, None)
                shutil.rmtree(root, ignore_errors=True)
            raise
        return {**self._finish_ingestion_store(store_id, created, original_mode, config, root, mutable), "kind": "url", "target": url, **result}

    def scan_web_query(self, query: str, *, name: str | None = None, mutable: bool = False, replace: bool = False, force: bool = False, progress=None) -> dict:
        prepared = self._prepare_ingestion_store(source_name="web-search", name=name, mutable=mutable, replace=replace)
        store_id, _, created, original_mode, config, root, runtime = prepared
        try:
            runtime.web_acquisition.progress = progress
            if hasattr(runtime.web_acquisition.search_provider, "progress"):
                runtime.web_acquisition.search_provider.progress = progress
            result = runtime.web_acquisition.acquire(
                query,
                max_results=self.settings.web_acquisition_max_results,
                max_pages=self.settings.web_acquisition_max_pages,
                force=force,
            ).as_dict()
        except Exception:
            if created and store_id != "main":
                self._runtimes.pop(store_id, None)
                shutil.rmtree(root, ignore_errors=True)
            raise
        return {**self._finish_ingestion_store(store_id, created, original_mode, config, root, mutable), "kind": "web_search", **result}

    def acquire_web(
        self, query: str, *, target_store: str | None = None
    ) -> dict:
        store_id = target_store or self.settings.web_acquisition_store
        runtime = self.store(store_id)
        runtime.require_writable()
        result = runtime.web_acquisition.acquire(
            query,
            max_results=self.settings.web_acquisition_max_results,
            max_pages=self.settings.web_acquisition_max_pages,
        )
        return {"store_id": store_id, **result.as_dict()}

    def recall_with_acquisition(
        self,
        query: str,
        *,
        top_k: int = 8,
        stores: list[str] | None = None,
        acquire_if_missing: bool = True,
        target_store: str | None = None,
    ) -> tuple[list[SearchHit], dict | None]:
        hits = self.retrieval.search(query, top_k, stores=stores)
        best_score = hits[0].score if hits else 0.0
        if (
            not acquire_if_missing
            or not self.settings.web_acquisition_enabled
            or (hits and best_score >= self.settings.web_acquisition_min_score)
        ):
            return hits, None
        try:
            acquisition = self.acquire_web(query, target_store=target_store)
        except Exception as exc:
            return hits, {
                "store_id": target_store or self.settings.web_acquisition_store,
                "query": query,
                "discovered": 0,
                "fetched": 0,
                "indexed": 0,
                "unchanged": 0,
                "failed": 1,
                "sources": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
        refreshed = self.retrieval.search(query, top_k, stores=stores)
        return refreshed, acquisition

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
        result = self.overlays.set_overlay(ref.store_id, ref.segment_id, **kwargs)
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

    def list_stores(self) -> list[dict]:
        return [
            {**config.as_dict(), "loaded": config.store_id in self._runtimes}
            for config in self.store_configs()
        ]

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
        for config in self.store_configs():
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
