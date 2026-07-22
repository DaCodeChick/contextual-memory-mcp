# Contextual Memory MCP

A local-first persistent memory service for extending the useful context
available to AI models.

The project is intentionally being developed in stages. The first stage indexes
files from a user-selected directory into persistent source, segment, vector,
and graph storage. Retrieval and active-context assembly will be refined after
the ingestion model is stable.

## Current capabilities

- Scan any directory supplied by the user.
- Include Markdown, text, and `.prompt` files.
- Exclude subdirectories by name or relative path.
- Incrementally update changed files.
- Remove indexed files that disappeared from a previously scanned root.
- Persist source metadata and graph data in SQLite.
- Persist embeddings in ChromaDB.
- Clear the complete database.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

## Scan a directory

The source directory is required. It is not fixed to a repository-local
`./prompts` folder.

```bash
contextual-memory-index scan /path/to/saved/prompts
```

Exclude subdirectories by name:

```bash
contextual-memory-index scan /path/to/saved/prompts   --exclude archive   --exclude experiments
```

Exclude a relative path:

```bash
contextual-memory-index scan /path/to/saved/prompts   --exclude old/deprecated
```

Force a complete re-index of the selected directory:

```bash
contextual-memory-index scan /path/to/saved/prompts --force
```

## Clear all stored memory

Interactive confirmation:

```bash
contextual-memory-index clear
```

Non-interactive confirmation:

```bash
contextual-memory-index clear --yes
```

## Run the MCP server

```bash
contextual-memory-mcp
```

The initial MCP surface contains only:

- `scan_directory`
- `clear_memory`

The scanner accepts the directory at call time, allowing the host AI or user to
choose which directory is indexed rather than relying on a hardcoded source
folder.

## Storage

By default, persistent data is written beneath `./data`:

- `contextual_memory.sqlite3`
- `chroma/`

Change the location with `CM_DATA_DIR`.

## Project direction

Saved prompt building blocks are the first ingestion target, not the final
scope. Later stages can add other document types, explicit memories, multiple
collections, session context, retrieval policies, graph inspection, and
active-context assembly without changing the basic storage facade.
