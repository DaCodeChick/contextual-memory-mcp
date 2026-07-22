from __future__ import annotations

from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from core.memory_matrix import PromptMemoryMatrix

mcp = FastMCP("Prompt Memory")
memory = PromptMemoryMatrix()


@mcp.tool()
def scan_prompt_directory(force: bool = False) -> dict:
    """Incrementally index the configured prompt directory."""
    return memory.ingestion.scan(force)


@mcp.tool()
def search_prompt_memory(query: str, top_k: int = 8) -> dict:
    """Search vector, lexical, and graph memory for reusable prompt fragments."""
    hits = memory.retrieval.search(query, top_k)
    return {"query": query, "results": [asdict(hit) for hit in hits]}


@mcp.tool()
def build_active_context(task: str, top_k: int = 8, max_chars: int = 18000) -> str:
    """Build clean Markdown memory blocks for insertion into an active LLM context."""
    return memory.context.build(task, top_k, max_chars)


@mcp.tool()
def remember_text(title: str, text: str, concepts: list[str] | None = None) -> dict:
    """Store an explicit durable memory outside the watched file directory."""
    return memory.ingestion.remember(title, text, concepts)


@mcp.tool()
def inspect_concept(concept: str, limit: int = 20) -> dict:
    """Inspect a graph concept, related concepts, and supporting segments."""
    return memory.repository.inspect_concept(concept, limit)


@mcp.tool()
def memory_stats() -> dict:
    """Return source, segment, concept, edge, and vector counts."""
    return memory.stats()


@mcp.tool()
def forget_source(source_path_or_id: str) -> dict:
    """Remove one indexed source and its vector entries."""
    removed, segment_ids = memory.repository.delete_source(source_path_or_id)
    if removed:
        memory.vectors.delete(segment_ids)
    return {"removed": removed, "segments_deleted": len(segment_ids)}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
