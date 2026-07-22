# Prompt Memory MCP

A local-first, Myriad-inspired persistent memory server for reusable prompt building blocks.

## Layers

- **Source repository:** canonical files and indexing state in SQLite.
- **Segment repository:** structured Markdown sections and prompt fragments.
- **Vector memory:** persistent ChromaDB embeddings.
- **Knowledge graph:** concepts and typed relationships in SQLite.
- **Retrieval engine:** vector, lexical, graph, and importance reranking.
- **Context builder:** returns clean source-attributed Markdown for the active context window.
- **MCP adapter:** thin tool layer over the core `PromptMemoryMatrix` facade.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Place saved prompts in `./prompts`, then index them:

```bash
prompt-memory-index scan
prompt-memory-index search "realistic character reference sheet"
prompt-memory-index context "Create a gender-swapped character model sheet"
```

Run the MCP server over stdio:

```bash
prompt-memory-mcp
```

## MCP tools

- `scan_prompt_directory`
- `search_prompt_memory`
- `build_active_context`
- `remember_text`
- `inspect_concept`
- `memory_stats`
- `forget_source`

The Markdown files remain the source of truth. ChromaDB and SQLite can be rebuilt from them.
