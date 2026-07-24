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

## Index files and directories

The CLI accepts either one file or an entire directory. With no `--name`, the
content is added to the normal writable `main` store:

```bash
uv run contextual-memory-index scan /path/to/character.md
uv run contextual-memory-index scan /path/to/saved/prompts
```

Provide `--name` to add the target to a named database. If that database does
not exist, it is created automatically:

```bash
uv run contextual-memory-index scan /path/to/character.md --name roleplay
```

New named databases are immutable after indexing by default. Use `--mutable`
when the named database should remain writable:

```bash
uv run contextual-memory-index scan /path/to/saved/prompts --name prompt-library --mutable
```

A later explicit scan can update an existing named database. Locked databases
are reopened only for that update and then returned to their previous mode.
Use `--replace` when the entire named database should be rebuilt instead:

```bash
uv run contextual-memory-index scan /path/to/saved/prompts --name prompt-library --replace
```

Directory scans support exclusions, and either kind of scan can force unchanged
content to be indexed again:

```bash
uv run contextual-memory-index scan /path/to/saved/prompts --exclude archive --force
```

## Clear stored data

Interactive confirmation:

```bash
uv run contextual-memory-index clear --store main
```

Non-interactive confirmation:

```bash
uv run contextual-memory-index clear --store main --yes
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
- `store_overlays.sqlite3` (local ranking overlays for immutable stores)
- `stores/<name>/manifest.json` plus each scanned store database

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

The server provides a writable `main` store. Scanned databases live beneath
`data/stores/<name>/` and contain their own `manifest.json`. The filesystem is
the source of truth: there is no separate store registry, registration step,
mount operation, or startup fixture.

`list_memory_stores` discovers manifests directly from disk. A named store is
opened lazily when recall or another operation addresses it. Returned memory
IDs are globally qualified, for example `ghidra-core:seg_abcd`.

Store modes are SQLite integers exposed through `StoreMode`:

```text
0 READ_WRITE
1 READ_ONLY
2 IMMUTABLE
```

Writes require an explicit `target_store`; they are never broadcast. Before a
write, clients must call `list_memory_stores` whenever the destination is not
already established in the current context. Store IDs must not be guessed or
discovered by intentionally causing a failed write.

Maintenance runs only against writable stores. Read-only and immutable SQLite
databases are opened with SQLite read-only URI modes and are never migrated
automatically. Their recall access counts and user-specific ranking choices are
kept in `store_overlays.sqlite3` instead of changing canonical content.

Creating a scanned database is sufficient to make it discoverable:

```bash
uv run contextual-memory-index scan ./project --name project-memory
```

This creates:

```text
data/stores/project-memory/
├── manifest.json
├── project-memory.sqlite3
└── chroma/
```

No registration or mounting command is required.


## Web search providers

Automatic web acquisition can use multiple search providers in priority order. Providers that need credentials are skipped unless configured, and failures automatically fall through to the next provider.

```env
CM_WEB_SEARCH_PROVIDERS=exa,brave,tavily,searxng,duckduckgo
CM_WEB_SEARCH_TIMEOUT=12
CM_EXA_API_KEY=
CM_BRAVE_SEARCH_API_KEY=
CM_TAVILY_API_KEY=
CM_SEARXNG_URL=http://localhost:8080
```

With no API keys or SearXNG URL, DuckDuckGo is used as the zero-configuration fallback. For a self-hosted setup, place `searxng` first and set `CM_SEARXNG_URL`. The configured SearXNG instance must permit JSON search responses.


## Web acquisition and indexing

Weak or empty `recall_memory` results can automatically trigger web discovery, page ingestion, and a second local recall. Search providers are attempted in configured priority order; unconfigured providers are skipped and failures fall through to the next provider.

```env
CM_WEB_SEARCH_PROVIDERS=exa,brave,tavily,searxng,duckduckgo
CM_WEB_SEARCH_CACHE_DAYS=7
CM_WEB_ACQUISITION_RETRY_DAYS=7
CM_WEB_ACQUISITION_REFRESH_DAYS=90
```

Search results are cached in `data/web_acquisition.sqlite3`. Acquisition history suppresses repeated searches for unavailable topics and schedules successful topics for a later refresh.

The index CLI accepts directories, individual files, direct URLs, and search queries:

```bash
python main.py scan ./prompts
python main.py scan ./character.md --name roleplay
python main.py scan https://example.org/wiki/Character --name roleplay
python main.py scan --search "Character franchise personality dialogue" --name roleplay
```

When `--name` is omitted, content is indexed into the writable `main` store. Missing named stores are created automatically and are immutable after indexing unless `--mutable` is supplied. MediaWiki pages use their API when available, and GitHub `blob` URLs are fetched through their raw-content endpoint.
