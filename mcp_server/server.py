from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from core.memory_matrix import ContextualMemoryMatrix


mcp = FastMCP(
    "Contextual Memory",
    instructions=(
        "Use recall_memory whenever stored context may help answer the "
        "user's request. The result is source-attributed Markdown intended "
        "to be read and incorporated into the current response. Use "
        "remember_memory only for durable information worth retaining "
        "beyond the current conversation. Do not store transient chatter, "
        "secrets, or information the user did not intend to preserve."
    ),
)
memory = ContextualMemoryMatrix()


@mcp.tool()
def recall_memory(
    query: str,
    top_k: int = 8,
    max_chars: int = 18000,
) -> str:
    """Recall relevant long-term memory for the current task.

    Call this before answering when previously indexed files or durable
    memories may contain useful instructions, examples, constraints, facts,
    preferences, or project context.

    The result is source-attributed Markdown ready to use as supporting
    context. The current user request always overrides conflicting memory.

    Args:
        query:
            A complete natural-language description of what context is
            needed. Include the task, important entities, and constraints.
        top_k:
            Maximum number of distinct memory segments to retrieve.
        max_chars:
            Maximum size of the returned Markdown context.
    """
    return memory.context.build(
        task=query,
        top_k=top_k,
        max_chars=max_chars,
    )


@mcp.tool()
def remember_memory(
    title: str,
    content: str,
    concepts: list[str] | None = None,
) -> dict:
    """Store an explicit durable memory for later conversations.

    Use this only when information should remain available long-term, such
    as a stable user preference, project decision, reusable procedure,
    confirmed fact, or compact session summary.

    Args:
        title:
            A concise descriptive title.
        content:
            The complete memory in clear standalone Markdown.
        concepts:
            Optional normalized topics that should connect this memory to
            related material in the knowledge graph.
    """
    return memory.ingestion.remember(
        title=title,
        text=content,
        concepts=concepts,
    )


@mcp.tool()
def explore_memory(
    concept: str,
    limit: int = 20,
) -> str:
    """Explore relationships around a stored concept.

    Use this when recall_memory surfaces a concept that should be expanded,
    or when the task depends on relationships among projects, constraints,
    people, systems, formats, or other indexed ideas.

    Args:
        concept:
            The concept name to inspect.
        limit:
            Maximum related concepts and supporting memories to return.
    """
    return memory.context.explore_concept(
        concept=concept,
        limit=limit,
    )


@mcp.tool()
def update_memory_weighting(
    segment_id: str,
    importance: float | None = None,
    confidence: float | None = None,
    source_quality: float | None = None,
    pinned: bool | None = None,
) -> dict:
    """Update persistent ranking metadata for one memory segment.

    Args:
        segment_id:
            The Memory ID returned by recall_memory.
        importance:
            Intrinsic importance from 0.0 to 2.0.
        confidence:
            Confidence in the memory from 0.0 to 1.0.
        source_quality:
            Reliability of the source from 0.0 to 1.0.
        pinned:
            Whether to give the memory an explicit ranking boost.
    """
    return memory.repository.set_segment_weighting(
        segment_id,
        importance=importance,
        confidence=confidence,
        source_quality=source_quality,
        pinned=pinned,
    )


@mcp.tool()
def explain_memory_ranking(query: str, top_k: int = 8) -> list[dict]:
    """Explain how candidate memories were ranked for a query."""
    return memory.retrieval.explain(query, top_k)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
