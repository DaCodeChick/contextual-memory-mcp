# Contextual Memory MCP

A local-first persistent contextual-memory engine with an MCP adapter for AI
models such as Qwen.

The project is being developed incrementally. The first ingestion target is a
directory of reusable Markdown prompt material, but the storage and retrieval
layers are general-purpose.

## Architecture

```text
Files and explicit memories
          |
          v
Ingestion and segmentation
          |
          +--> SQLite source and graph storage
          |
          +--> ChromaDB vector storage
          |
          v
Hybrid retrieval and context assembly
          |
          v
Thin MCP adapter used by Qwen
```

The CLI performs administrative work. The MCP server exposes memory operations
that are useful to the model.

## Install with uv

```bash
uv venv --python 3.12
uv pip install -e .
cp .env.example .env
```

Python 3.12 or 3.13 is recommended for broad compatibility with the current
machine-learning dependencies.

## Index a directory

The source directory is selected by the user at scan time:

```bash
uv run contextual-memory-index scan /path/to/saved/prompts
```

Exclude subdirectories by name or relative path:

```bash
uv run contextual-memory-index scan /path/to/saved/prompts \
  --exclude archive \
  --exclude experiments \
  --exclude old/deprecated
```

Force unchanged files to be indexed again:

```bash
uv run contextual-memory-index scan /path/to/saved/prompts --force
```

## Clear stored data

Interactive confirmation:

```bash
uv run contextual-memory-index clear
```

Non-interactive confirmation:

```bash
uv run contextual-memory-index clear --yes
```

Scanning and clearing are deliberately CLI-only maintenance operations. They are
not exposed to the model through MCP.

## Run the MCP server

```bash
uv run contextual-memory-mcp
```

The MCP server exposes model-facing recall, ingestion, lifecycle, and maintenance tools:

### `recall_memory`

Retrieves semantically, lexically, and graph-related memory and returns clean,
source-attributed Markdown that Qwen can use in its active context.

Typical model call:

```text
recall_memory(
  query="Create a gender-swapped character reference sheet while preserving identity, colors, and species traits"
)
```

### `store_memory`

Automatically captures durable information directly stated by the user. The
model is instructed to call it before drafting its response whenever the current
message contains durable information, including during ordinary conversation. The user does not need to say
“remember this,” and routine storage must not trigger a permission question or
an announcement. The model supplies an integer memory type and a normalized
importance score from 0.0 to 2.0. The server validates those values and assigns
lifecycle state, origin, confidence, source quality, and conservative
server-owned lifecycle policy.

### `store_memory_candidate`

Stores model-generated hypotheses and interpretations as candidate inferences.
It is not a substitute for `store_memory` when the user directly stated the
information, whenever that statement is durable. The
model supplies semantic type and importance, while the server assigns lifecycle
state, origin, confidence, source quality, and conservative retention policy.

### `explore_memory`

Traverses the knowledge graph around a concept and returns related concepts plus
supporting memory excerpts.

The MCP does **not** expose scan, clear, stats, or database-deletion tools. Those
are administrative concerns and remain under direct user control.

## LM Studio configuration

Add the server as a stdio MCP using the repository's virtual environment. A
typical configuration resembles:

```json
{
  "mcpServers": {
    "contextual-memory": {
      "command": "/absolute/path/to/contextual-memory-mcp/.venv/bin/contextual-memory-mcp",
      "args": [],
      "cwd": "/absolute/path/to/contextual-memory-mcp"
    }
  }
}
```

Alternatively, invoke it through uv:

```json
{
  "mcpServers": {
    "contextual-memory": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/contextual-memory-mcp",
        "contextual-memory-mcp"
      ]
    }
  }
}
```

Use absolute paths when LM Studio is launched outside a terminal, because GUI
applications may not inherit the same shell PATH.

## Storage

Persistent data is stored beneath `CM_DATA_DIR`, which defaults to `./data`:

- `contextual_memory.sqlite3`
- `chroma/`
- `store_registry.sqlite3` (mounted stores and locked-store overlays)

The embedding model is downloaded and cached locally by Sentence Transformers
on first use.

## Current retrieval path

`recall_memory` currently combines:

- semantic similarity from ChromaDB
- SQLite full-text relevance
- graph relationships
- segment importance
- per-source diversity
- a configurable context-size budget

The returned value is Markdown rather than an embedding blob or database
record, so the model receives reusable source material directly.


## Memory importance and lifecycle

Memory importance is persistent and evolves through an explicit maintenance pass:

```text
new recall accesses
      +
configured access gain
      -
elapsed inactivity decay
      |
      v
updated importance
      |
      v
promotion / archival policy
```

Run `run_memory_maintenance` through MCP to reinforce accessed memories, decay
inactive unpinned memories, synchronize vector metadata, and then evaluate
candidate promotion or active-memory archival. Pass `dry_run=true` to inspect
all proposed changes without mutating storage.

All state, type, origin, lifecycle-reason, and importance-reason enums are
stored as SQLite integers and exposed in Python as `IntEnum` values.


## Multiple memory stores

The server provides a writable `main` store. Additional stores can be mounted
as writable, read-only, or immutable databases and searched together. Returned
memory IDs are globally qualified, for example `ghidra-core:seg_abcd`. APIs
require store-qualified memory references and explicit write destinations.

Store modes are SQLite integers exposed through `StoreMode`:

```text
0 READ_WRITE
1 READ_ONLY
2 IMMUTABLE
```

Writes require an explicit `target_store`; they are never broadcast.
Maintenance runs only against writable stores. Read-only and immutable SQLite
databases are opened with SQLite read-only URI modes and are never migrated
automatically. Their recall access counts and user-specific ranking choices are
kept in the writable registry overlay instead of changing canonical content.

A store manifest may be loaded at startup with `CM_STORES_FILE`:

```json
{
  "stores": [
    {
      "store_id": "reference",
      "display_name": "Reference Knowledge",
      "sqlite_path": "stores/reference/memory.sqlite3",
      "chroma_path": "stores/reference/chroma",
      "mode": 2,
      "priority": 1.15,
      "specialty": "documentation"
    }
  ]
}
```

The MCP also exposes store listing, mounting, unmounting, filtered recall, and
locked-memory overlays (`local_boost`, `hidden`, and `pinned_override`). This is
the completed generic foundation for future specialties; no Ghidra-specific
code is included yet.
