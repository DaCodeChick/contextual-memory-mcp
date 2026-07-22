from __future__ import annotations

from pathlib import Path
from typing import Sequence

import chromadb

from core.models import PromptSegment, SourceDocument
from providers.embeddings import SentenceTransformerProvider


class VectorMemory:
    def __init__(self, path: Path, collection_name: str, embedder: SentenceTransformerProvider) -> None:
        self.client = chromadb.PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(collection_name, metadata={"hnsw:space": "cosine"})
        self.embedder = embedder

    def replace_document(self, doc: SourceDocument, segments: Sequence[PromptSegment]) -> None:
        existing = self.collection.get(where={"source_id": doc.source_id}, include=[])
        if existing.get("ids"):
            self.collection.delete(ids=existing["ids"])
        if not segments:
            return
        documents = [segment.text for segment in segments]
        embeddings = self.embedder.embed_documents([
            f"Title: {doc.title}\nSection: {segment.heading or '(none)'}\nConcepts: {', '.join(segment.concepts)}\n\n{segment.text}"
            for segment in segments
        ])
        self.collection.add(
            ids=[segment.segment_id for segment in segments],
            documents=documents,
            embeddings=embeddings,
            metadatas=[{
                "source_id": doc.source_id,
                "source_path": doc.relative_path,
                "title": doc.title,
                "heading": segment.heading or "",
                "importance": segment.importance,
            } for segment in segments],
        )

    def search(self, query: str, limit: int = 50) -> list[dict]:
        if self.collection.count() == 0:
            return []
        result = self.collection.query(
            query_embeddings=[self.embedder.embed_query(query)],
            n_results=min(limit, self.collection.count()),
            include=["distances", "documents", "metadatas"],
        )
        hits: list[dict] = []
        for index, segment_id in enumerate(result["ids"][0]):
            distance = float(result["distances"][0][index])
            hits.append({
                "segment_id": segment_id,
                "vector_score": max(0.0, 1.0 - distance),
                "text": result["documents"][0][index],
                "metadata": result["metadatas"][0][index],
            })
        return hits

    def delete(self, segment_ids: Sequence[str]) -> None:
        if segment_ids:
            self.collection.delete(ids=list(segment_ids))

    def count(self) -> int:
        return self.collection.count()
