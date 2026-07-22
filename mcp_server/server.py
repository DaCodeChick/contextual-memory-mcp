from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from core.enums import MemoryOrigin, MemoryState, MemoryType
from core.memory_matrix import ContextualMemoryMatrix
from core.stores import MemoryStoreConfig, StoreMode


MCP_INSTRUCTIONS = """
Use recall_memory whenever stored context may help answer the user's request.

REQUIRED STORE RESOLUTION:
Before any memory write, determine the destination store. If a writable target
store is not already explicitly established in the current conversation or
tool context, call list_memory_stores first and choose from the returned stores.
Never guess a store ID, never assume "main", and never wait for a failed write
to discover valid values. Reuse a previously resolved target only while it
remains unambiguous in the current context.

REQUIRED AUTOMATIC MEMORY CAPTURE:
Before drafting the conversational response, call store_memory whenever the
current user message explicitly states durable information that could improve
future conversations. This includes durable facts, preferences, relationships,
projects, goals, skills, procedures, and personal history.

The model must estimate semantic memory type and importance. The server
validates those values and remains responsible for lifecycle state, origin,
confidence, and source quality.

The user does not need to say "remember this". Do not ask permission solely to
call the tool, do not announce routine memory capture, and continue the
conversation normally after the call.

Use store_memory only for information directly stated by the user. Use
store_memory_candidate only for useful model-generated inferences,
interpretations, hypotheses, or guesses. Never replace store_memory with store_memory_candidate when the user directly
stated the information.

Do not store transient chatter, authentication secrets, financial credentials,
private keys, session tokens, or information the user explicitly asks not to
retain.
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
    memory_type: int,
    importance: float,
    concepts: list[str] | None = None,
) -> dict:
    """Automatically store durable information directly stated by the user.

    This tool call is required before drafting the response whenever the current
    user message explicitly states durable information that may improve future
    conversations. Do not skip storage in order to respond first, ask permission
    solely for the tool call, or announce routine memory capture.

    The model extracts the direct user statement and assigns its semantic type
    and future conversational importance. The server validates those values and
    determines lifecycle state, origin, confidence, and source quality.

    Args:
        target_store:
            Explicit writable store receiving the memory. If the destination
            is not already established in the current context, call
            list_memory_stores before this tool. Never guess or assume a store
            ID and never use a failed write to discover valid values.
        title:
            A concise, descriptive title for the stored memory.
        content:
            A complete standalone statement preserving what the user said.
        memory_type:
            Integer MemoryType classification: 0 unknown, 1 preference,
            2 fact, 3 relationship, 4 project, 5 skill, 6 procedure,
            7 observation, 8 inference.
        importance:
            Estimated future conversational value from 0.0 to 2.0.
            Use 0.0 for trivial or fleeting details, 0.5 for ordinary durable
            context, 1.0 for clearly useful context, 1.5 for major life or
            project context, and 2.0 for foundational information. Judge
            usefulness rather than emotional intensity.
        concepts:
            Optional normalized topics connecting related memories.
    """
    return memory.remember(
        target_store=target_store,
        title=title,
        text=content,
        concepts=concepts,
        memory_type=memory_type,
        importance=importance,
        memory_origin=MemoryOrigin.EXPLICIT_USER,
    )


@mcp.tool()
def store_memory_candidate(
    target_store: str,
    title: str,
    content: str,
    memory_type: int,
    importance: float,
    concepts: list[str] | None = None,
) -> dict:
    """Store a useful model-generated inference as a candidate.

    Use this only for interpretations, hypotheses, or inferred context that the
    user did not directly state. Never use it instead of store_memory when the
    user directly stated the information. Do not ask permission solely to retain
    the candidate or announce
    routine candidate capture.

    The model assigns semantic type and estimated future conversational
    importance. The server validates those values and determines lifecycle
    state, confidence, source quality, and origin metadata.

    Args:
        target_store:
            Explicit writable store receiving the candidate. Call
            list_memory_stores before this tool if the destination is not
            already established in the current context. Never guess or assume
            a store ID and never use a failed write to discover valid values.
        title:
            A concise, descriptive title for the inferred memory.
        content:
            The proposed memory in standalone form.
        memory_type:
            Integer MemoryType classification: 0 unknown, 1 preference,
            2 fact, 3 relationship, 4 project, 5 skill, 6 procedure,
            7 observation, 8 inference.
        importance:
            Estimated future conversational value from 0.0 to 2.0.
        concepts:
            Optional normalized graph concepts.
    """
    return memory.remember(
        target_store=target_store,
        title=title,
        text=content,
        concepts=concepts,
        memory_type=memory_type,
        importance=importance,
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
    """Resolve valid memory-store IDs and their access modes.

    Call this before any memory write when the destination store is not already
    explicitly established in the current conversation or tool context. Select
    a writable enabled store from this result; do not guess a store ID or wait
    for a write error to reveal valid values.
    """
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
