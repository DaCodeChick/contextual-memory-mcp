from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from core.enums import MemoryOrigin, MemoryState, MemoryType
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
    memory_type: int = int(MemoryType.UNKNOWN),
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
        memory_type:
            Integer MemoryType value: 0 unknown, 1 preference, 2 fact,
            3 relationship, 4 project, 5 skill, 6 procedure,
            7 observation, or 8 inference.
    """
    return memory.ingestion.remember(
        title=title,
        text=content,
        concepts=concepts,
        memory_state=MemoryState.ACTIVE,
        memory_type=memory_type,
        memory_origin=MemoryOrigin.EXPLICIT_USER,
    )


@mcp.tool()
def store_memory_candidate(
    title: str,
    content: str,
    concepts: list[str] | None = None,
    memory_type: int = int(MemoryType.INFERENCE),
) -> dict:
    """Store a proposed memory without making it eligible for recall.

    Use this for model-inferred or automatically extracted information that
    may be durable but should be reviewed or reinforced before activation.

    Args:
        title:
            A concise descriptive title.
        content:
            The proposed memory in standalone form.
        concepts:
            Optional normalized graph concepts.
        memory_type:
            Integer MemoryType value. Inference (8) is the default.
    """
    return memory.ingestion.remember(
        title=title,
        text=content,
        concepts=concepts,
        memory_state=MemoryState.CANDIDATE,
        memory_type=memory_type,
        memory_origin=MemoryOrigin.MODEL_INFERENCE,
    )


@mcp.tool()
def update_memory_lifecycle(
    segment_id: str,
    memory_state: int | None = None,
    memory_type: int | None = None,
    memory_origin: int | None = None,
) -> dict:
    """Update integer-backed lifecycle metadata for a memory segment.

    MemoryState values: 0 candidate, 1 active, 2 archived, 3 rejected.
    MemoryType values: 0 unknown, 1 preference, 2 fact, 3 relationship,
    4 project, 5 skill, 6 procedure, 7 observation, 8 inference.
    MemoryOrigin values: 0 unknown, 1 explicit user, 2 imported file,
    3 generated summary, 4 model inference, 5 specialty.
    """
    return memory.update_lifecycle(
        segment_id,
        memory_state=memory_state,
        memory_type=memory_type,
        memory_origin=memory_origin,
    )


@mcp.tool()
def run_memory_maintenance(dry_run: bool = False) -> dict:
    """Reinforce/decay importance, then evaluate lifecycle transitions."""
    result = memory.run_maintenance(apply=not dry_run)
    importance = result["importance"]
    lifecycle = result["lifecycle"]
    return {
        "importance": {
            "evaluated": importance.evaluated,
            "adjusted": importance.adjusted,
            "changed_segment_ids": list(importance.changed_segment_ids),
            "decisions": [
                {
                    "segment_id": decision.segment_id,
                    "previous_importance": decision.previous_importance,
                    "target_importance": decision.target_importance,
                    "reason_code": int(decision.reason_code),
                    "reason_code_name": decision.reason_code.name,
                    "reason": decision.reason,
                }
                for decision in importance.decisions
            ],
        },
        "lifecycle": {
            "evaluated": lifecycle.evaluated,
            "changed": lifecycle.changed,
            "changed_segment_ids": list(lifecycle.changed_segment_ids),
        },
    }


@mcp.tool()
def run_memory_lifecycle(dry_run: bool = False) -> dict:
    """Evaluate automatic memory promotion and archival rules.

    Args:
        dry_run:
            When true, return the proposed transitions without applying them.
    """
    result = memory.run_lifecycle(apply=not dry_run)
    return {
        "evaluated": result.evaluated,
        "changed": result.changed,
        "changed_segment_ids": list(result.changed_segment_ids),
        "decisions": [
            {
                "action": int(decision.action),
                "action_name": decision.action.name,
                "current_state": int(decision.current_state),
                "current_state_name": decision.current_state.name,
                "target_state": int(decision.target_state),
                "target_state_name": decision.target_state.name,
                "reason_code": int(decision.reason_code),
                "reason_code_name": decision.reason_code.name,
                "reason": decision.reason,
            }
            for decision in result.decisions
        ],
    }


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
