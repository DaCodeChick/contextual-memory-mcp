from __future__ import annotations

from core.config import Settings
from core.retrieval_engine import RetrievalEngine


class ContextBuilder:
    def __init__(
        self,
        settings: Settings,
        retrieval: RetrievalEngine,
    ) -> None:
        self.settings = settings
        self.retrieval = retrieval

    def build(
        self,
        task: str,
        top_k: int | None = None,
        max_chars: int | None = None,
    ) -> str:
        hits = self.retrieval.search(task, top_k)
        budget = max_chars or self.settings.max_context_chars

        if not hits:
            return (
                "# Contextual Memory Recall\n\n"
                f"Query: {task}\n\n"
                "No relevant stored memory was found."
            )

        parts = [
            "# Contextual Memory Recall",
            "",
            f"Query: {task}",
            "",
            (
                "Use only the portions that help with the current request. "
                "The current conversation and user instructions override "
                "conflicting stored material."
            ),
            "",
        ]
        used = len("\n".join(parts))

        for index, hit in enumerate(hits, 1):
            heading = f" — {hit.heading}" if hit.heading else ""
            score = f"{hit.score:.3f}"
            block = (
                f"## Memory {index}: {hit.title}{heading}\n"
                f"Source: `{hit.source_path}`\n"
                f"Relevance: {score}\n"
                + (
                    f"Concepts: {', '.join(hit.concepts[:10])}\n"
                    if hit.concepts
                    else ""
                )
                + f"\n{hit.text.strip()}\n"
            )

            if used + len(block) > budget:
                remaining = budget - used
                if remaining > 300:
                    parts.append(
                        block[:remaining].rstrip()
                        + "\n\n[Memory context truncated]"
                    )
                break

            parts.append(block)
            used += len(block)

        return "\n".join(parts).strip()

    def explore_concept(
        self,
        concept: str,
        limit: int = 20,
    ) -> str:
        result = self.retrieval.repository.inspect_concept(
            concept,
            limit,
        )
        if not result.get("found"):
            return (
                "# Contextual Memory Concept\n\n"
                f"No stored concept named `{concept}` was found."
            )

        node = result["concept"]
        parts = [
            "# Contextual Memory Concept",
            "",
            f"## {node['name']}",
            "",
            f"Type: {node['concept_type']}",
            f"Importance: {float(node['importance']):.2f}",
        ]

        neighbors = result.get("neighbors", [])
        if neighbors:
            parts.extend(["", "### Related concepts", ""])
            for item in neighbors:
                parts.append(
                    "- "
                    f"{item['name']} "
                    f"({item['relation']}, "
                    f"weight {float(item['weight']):.2f}, "
                    f"{item['evidence_count']} evidence)"
                )

        segments = result.get("segments", [])
        if segments:
            parts.extend(["", "### Supporting memories", ""])
            for item in segments:
                heading = (
                    f" — {item['heading']}"
                    if item.get("heading")
                    else ""
                )
                parts.extend(
                    [
                        f"#### {item['source_path']}{heading}",
                        "",
                        str(item["excerpt"]).strip(),
                        "",
                    ]
                )

        return "\n".join(parts).strip()
