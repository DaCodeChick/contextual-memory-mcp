from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from core.enums import MemoryOrigin, MemoryState, MemoryType
from core.memory_matrix import ContextualMemoryMatrix
from core.stores import MemoryStoreConfig, StoreMode


MCP_INSTRUCTIONS = """
Use recall_memory whenever stored context may help answer the user's request.

Silently and automatically call store_memory when the user provides durable
information that could improve future conversations. The user does not need to
say "remember this", and you must not ask for permission merely because a fact
may be stored. Memory capture is an internal action and should not interrupt or
be announced in the conversational response.

Store direct user statements with store_memory. Use store_memory_candidate only
for model inferences, interpretations, guesses, or other information not directly
stated by the user. Never present an inference as a direct user statement.

Do not store transient chatter, authentication secrets, financial credentials,
private keys, session tokens, or information the user explicitly asks not to
retain. The server determines lifecycle state, type, importance, confidence, and
source quality.
""".strip()


mcp = FastMCP("Contextual Memory", instructions=MCP_INSTRUCTIONS)
memory = ContextualMemoryMatrix()


@mcp.tool()
def recall_memory(
    query: str,
    top_k: int = 8,
    max_chars: int = 18000,
    stores: list[str] | None = None,
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
        stores=stores,
    )


@mcp.tool()
def store_memory(
    target_store: str,
    title: str,
    content: str,
    concepts: list[str] | None = None,
) -> dict:
    """Silently capture durable information directly stated by the user.

    Call this automatically when the current user message contains information
    that may improve future conversations. The user does not need to request
    storage, and you must not ask permission solely to call this tool. Continue
    the conversation normally after the call without announcing routine storage.

    The server determines lifecycle state, memory type, importance, confidence,
    source quality, and origin metadata.

    Args:
        target_store:
            Explicit writable store receiving the memory.
        title:
            A concise, descriptive title for the stored memory.
        content:
            A complete standalone statement preserving what the user said.
        concepts:
            Optional normalized topics connecting related memories.
    """
    return memory.remember(
        target_store=target_store,
        title=title,
        text=content,
        concepts=concepts,
        memory_origin=MemoryOrigin.EXPLICIT_USER,
    )


@mcp.tool()
def store_memory_candidate(
    target_store: str,
    title: str,
    content: str,
    concepts: list[str] | None = None,
) -> dict:
    """Silently store a model inference as a non-recallable candidate.

    Call this automatically for useful interpretations, hypotheses, or inferred
    context that the user did not directly state. Do not ask permission merely
    to retain the candidate, and never use this tool to rewrite a direct user
    statement as though it were a model inference.

    The server determines lifecycle state, memory type, importance, confidence,
    source quality, and origin metadata.

    Args:
        target_store:
            Explicit writable store receiving the candidate.
        title:
            A concise, descriptive title for the inferred memory.
        content:
            The proposed memory in standalone form.
        concepts:
            Optional normalized graph concepts.
    """
    return memory.remember(
        target_store=target_store,
        title=title,
        text=content,
        concepts=concepts,
        memory_origin=MemoryOrigin.MODEL_INFERENCE,
    )


@mcp.tool()
def update_memory_lifecycle(
    memory_ref: str,
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
        memory_ref,
        memory_state=memory_state,
        memory_type=memory_type,
        memory_origin=memory_origin,
    )


@mcp.tool()
def run_memory_maintenance(
    dry_run: bool = False, stores: list[str] | None = None
) -> dict:
    """Reinforce/decay importance, then evaluate lifecycle transitions."""
    result = memory.run_maintenance(apply=not dry_run, stores=stores)
    formatted = {}
    for store_id, store_result in result.items():
        if store_result.get("skipped"):
            formatted[store_id] = store_result
            continue
        importance = store_result["importance"]
        lifecycle = store_result["lifecycle"]
        formatted[store_id] = {
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
    return formatted


@mcp.tool()
def run_memory_lifecycle(
    store_id: str, dry_run: bool = False
) -> dict:
    """Evaluate automatic memory promotion and archival rules.

    Args:
        dry_run:
            When true, return the proposed transitions without applying them.
    """
    result = memory.run_lifecycle(apply=not dry_run, store_id=store_id)
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
    store_id: str,
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
        store_id=store_id,
        concept=concept,
        limit=limit,
    )


@mcp.tool()
def update_memory_weighting(
    memory_ref: str,
    importance: float | None = None,
    confidence: float | None = None,
    source_quality: float | None = None,
    pinned: bool | None = None,
) -> dict:
    """Update persistent ranking metadata for one memory segment.

    Args:
        memory_ref:
            The store-qualified Memory ID returned by recall_memory.
        importance:
            Intrinsic importance from 0.0 to 2.0.
        confidence:
            Confidence in the memory from 0.0 to 1.0.
        source_quality:
            Reliability of the source from 0.0 to 1.0.
        pinned:
            Whether to give the memory an explicit ranking boost.
    """
    return memory.update_weighting(
        memory_ref,
        importance=importance,
        confidence=confidence,
        source_quality=source_quality,
        pinned=pinned,
    )


@mcp.tool()
def explain_memory_ranking(
    query: str, top_k: int = 8, stores: list[str] | None = None
) -> list[dict]:
    """Explain how candidate memories were ranked for a query."""
    return memory.retrieval.explain(query, top_k, stores=stores)



@mcp.tool()
def list_memory_stores() -> list[dict]:
    """List mounted memory stores and their integer-backed access modes."""
    return memory.list_stores()


@mcp.tool()
def mount_memory_store(
    store_id: str,
    display_name: str,
    sqlite_path: str,
    chroma_path: str,
    mode: int = int(StoreMode.IMMUTABLE),
    priority: float = 1.0,
    collection_name: str = "context_segments",
    specialty: str | None = None,
) -> dict:
    """Mount an existing dedicated memory store. Mode: 0 writable, 1 read-only, 2 immutable."""
    config = MemoryStoreConfig(
        store_id=store_id,
        display_name=display_name,
        sqlite_path=Path(sqlite_path).expanduser().resolve(),
        chroma_path=Path(chroma_path).expanduser().resolve(),
        collection_name=collection_name,
        mode=StoreMode(mode),
        enabled=True,
        priority=priority,
        specialty=specialty,
    )
    return memory.mount_store(config)


@mcp.tool()
def set_memory_store_enabled(store_id: str, enabled: bool) -> dict:
    """Enable or disable a mounted store without deleting or unmounting it."""
    return memory.set_store_enabled(store_id, enabled)


@mcp.tool()
def unmount_memory_store(store_id: str) -> dict:
    """Unmount a dedicated store without deleting its files."""
    return {"store_id": store_id, "unmounted": memory.unmount_store(store_id)}


@mcp.tool()
def update_locked_memory_overlay(
    memory_ref: str,
    local_boost: float | None = None,
    hidden: bool | None = None,
    pinned_override: bool | None = None,
) -> dict:
    """Set mutable local ranking preferences for a read-only or immutable memory."""
    return memory.update_weighting(
        memory_ref,
        local_boost=local_boost,
        hidden=hidden,
        pinned_override=pinned_override,
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
