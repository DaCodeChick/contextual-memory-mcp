from __future__ import annotations

from core.config import Settings
from core.retrieval_engine import RetrievalEngine


class ContextBuilder:
    def __init__(self, settings: Settings, retrieval: RetrievalEngine) -> None:
        self.settings = settings
        self.retrieval = retrieval

    def build(self, task: str, top_k: int | None = None, max_chars: int | None = None) -> str:
        hits = self.retrieval.search(task, top_k)
        budget = max_chars or self.settings.max_context_chars
        parts = [
            "# Retrieved Prompt Memory",
            "",
            f"Current task: {task}",
            "",
            "The current user request overrides conflicting retrieved material. Reuse only relevant building blocks.",
            "",
        ]
        used = len("\n".join(parts))
        for index, hit in enumerate(hits, 1):
            heading = f" — {hit.heading}" if hit.heading else ""
            block = (
                f"## Memory {index}: {hit.title}{heading}\n"
                f"Source: `{hit.source_path}`\n"
                + (f"Concepts: {', '.join(hit.concepts[:10])}\n" if hit.concepts else "")
                + f"\n{hit.text.strip()}\n"
            )
            if used + len(block) > budget:
                remaining = budget - used
                if remaining > 300:
                    parts.append(block[:remaining].rstrip() + "\n\n[context truncated]")
                break
            parts.append(block)
            used += len(block)
        return "\n".join(parts).strip()
