from __future__ import annotations

from pathlib import Path
from typing import Sequence

import chromadb

from core.models import MemorySegment, SourceDocument
from providers.embeddings import SentenceTransformerProvider


class VectorMemory:
    def __init__(
        self,
        path: Path,
        collection_name: str,
        embedder: SentenceTransformerProvider,
    ) -> None:
        self.client = chromadb.PersistentClient(path=str(path))
        self.collection_name = collection_name
        self.collection = self._get_collection()
        self.embedder = embedder

    def _get_collection(self):
        return self.client.get_or_create_collection(
            self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_document(
        self,
        doc: SourceDocument,
        segments: Sequence[MemorySegment],
        deleted_ids: Sequence[str] = (),
    ) -> None:
        if deleted_ids:
            self.collection.delete(ids=list(deleted_ids))

        if not segments:
            return

        documents = [segment.text for segment in segments]
        embeddings = self.embedder.embed_documents(
            [
                (
                    f"Title: {doc.title}\n"
                    f"Section: {segment.heading or '(none)'}\n"
                    f"Concepts: {', '.join(segment.concepts)}\n\n"
                    f"{segment.text}"
                )
                for segment in segments
            ]
        )

        self.collection.upsert(
            ids=[segment.segment_id for segment in segments],
            documents=documents,
            embeddings=embeddings,
            metadatas=[
                {
                    "source_id": doc.source_id,
                    "source_path": doc.relative_path,
                    "title": doc.title,
                    "heading": segment.heading or "",
                    "importance": segment.importance,
                    "content_hash": segment.content_hash,
                    "memory_state": int(segment.memory_state),
                    "memory_type": int(segment.memory_type),
                    "memory_origin": int(segment.memory_origin),
                }
                for segment in segments
            ],
        )

    def replace_document(
        self,
        doc: SourceDocument,
        segments: Sequence[MemorySegment],
    ) -> None:
        existing = self.collection.get(
            where={"source_id": doc.source_id},
            include=[],
        )
        deleted_ids = existing.get("ids") or []
        self.upsert_document(doc, segments, deleted_ids=deleted_ids)

    def search(
        self,
        query: str,
        limit: int = 50,
        *,
        memory_state: int | None = None,
    ) -> list[dict]:
        if self.collection.count() == 0:
            return []

        query_args = {
            "query_embeddings": [self.embedder.embed_query(query)],
            "n_results": min(limit, self.collection.count()),
            "include": ["distances", "documents", "metadatas"],
        }
        if memory_state is not None:
            query_args["where"] = {"memory_state": int(memory_state)}
        result = self.collection.query(**query_args)

        hits: list[dict] = []
        for index, segment_id in enumerate(result["ids"][0]):
            distance = float(result["distances"][0][index])
            hits.append(
                {
                    "segment_id": segment_id,
                    "vector_score": max(0.0, 1.0 - distance),
                    "text": result["documents"][0][index],
                    "metadata": result["metadatas"][0][index],
                }
            )
        return hits

    def update_lifecycle(
        self,
        segment_id: str,
        *,
        memory_state: int,
        memory_type: int,
        memory_origin: int,
    ) -> None:
        result = self.collection.get(
            ids=[segment_id],
            include=["metadatas"],
        )
        ids = result.get("ids") or []
        metadatas = result.get("metadatas") or []
        if not ids or not metadatas:
            return

        metadata = dict(metadatas[0])
        metadata.update(
            {
                "memory_state": int(memory_state),
                "memory_type": int(memory_type),
                "memory_origin": int(memory_origin),
            }
        )
        self.collection.update(ids=[segment_id], metadatas=[metadata])

    def update_weighting(self, segment_id: str, *, importance: float) -> None:
        result = self.collection.get(ids=[segment_id], include=["metadatas"])
        ids = result.get("ids") or []
        metadatas = result.get("metadatas") or []
        if not ids or not metadatas:
            return
        metadata = dict(metadatas[0])
        metadata["importance"] = float(importance)
        self.collection.update(ids=[segment_id], metadatas=[metadata])

    def delete(self, segment_ids: Sequence[str]) -> None:
        if segment_ids:
            self.collection.delete(ids=list(segment_ids))

    def clear(self) -> None:
        try:
            self.client.delete_collection(self.collection_name)
        except Exception:
            existing = self.collection.get(include=[])
            if existing.get("ids"):
                self.collection.delete(ids=existing["ids"])
        self.collection = self._get_collection()

    def count(self) -> int:
        return self.collection.count()
