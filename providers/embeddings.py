from __future__ import annotations

from functools import cached_property
from typing import Sequence

from sentence_transformers import SentenceTransformer


class SentenceTransformerProvider:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    @cached_property
    def model(self) -> SentenceTransformer:
        return SentenceTransformer(self.model_name, trust_remote_code=False)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        method = getattr(self.model, "encode_document", self.model.encode)
        values = method(list(texts), normalize_embeddings=True, show_progress_bar=False)
        return [row.tolist() for row in values]

    def embed_query(self, text: str) -> list[float]:
        method = getattr(self.model, "encode_query", self.model.encode)
        return method([text], normalize_embeddings=True, show_progress_bar=False)[0].tolist()
