from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from core.memory_matrix import ContextualMemoryMatrix


mcp = FastMCP("Contextual Memory")
memory = ContextualMemoryMatrix()


@mcp.tool()
def scan_directory(
    directory: str,
    exclude: list[str] | None = None,
    force: bool = False,
) -> dict:
    """Index supported files from a user-specified directory.

    Args:
        directory:
            Absolute or relative directory to scan.
        exclude:
            Optional subdirectory names or relative paths to skip.
        force:
            Re-index files whose content has not changed.
    """
    return memory.ingestion.scan(
        directory=Path(directory),
        force=force,
        excludes=exclude,
    )


@mcp.tool()
def clear_memory(confirm: bool = False) -> dict:
    """Delete every indexed source, segment, concept, graph edge, and vector."""
    if not confirm:
        return {
            "cleared": False,
            "error": "Set confirm=true to clear the memory database.",
        }
    return memory.clear()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
