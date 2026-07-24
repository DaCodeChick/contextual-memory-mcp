# Multi-store foundation

- Added integer-backed READ_WRITE, READ_ONLY, and IMMUTABLE store modes.
- Requires store-qualified memory references and explicit write routing.
- Added filesystem-discovered store manifests and lazy runtime opening.
- Added federated retrieval, store priorities, filters, and qualified memory refs.
- Added deterministic write routing and locked-store write rejection.
- Added writable overlays for access counts, local boosts, hiding, and pin overrides.
- Added store-aware maintenance, lifecycle, weighting, CLI, and MCP tools.
- Locked SQLite stores use read-only/immutable URI modes and are schema-validated without migration.
- Stopped before implementing any Ghidra specialty behavior.

## Strict pre-release API cleanup

- Removed prompt-era type and facade aliases.
- Removed the obsolete document replacement wrapper.
- Removed single-store facade properties from the federated matrix.
- Removed implicit default write routing.
- Required store-qualified memory references.
- Required explicit store IDs for lifecycle, importance, clear, scan, and concept exploration operations.

## Automatic memory capture

- Replaced the permission-oriented `remember_memory` MCP tool with
  `store_memory`, whose server instructions require silent automatic capture of
  durable direct-user information.
- Direct user statements can be stored as either active or candidate memories;
  special-case or one-off material no longer needs a conversational permission
  prompt merely to be retained conservatively.
- Model-generated hypotheses remain separated through
  `store_memory_candidate` and use model-inference origin metadata.
- Memory type and importance are now required model-supplied fields for both
  direct memories and inferred candidates.
- Importance is normalized to the supported `0.0` to `2.0` range; lifecycle,
  origin, confidence, source quality, and retention policy remain
  server-owned.
- Removed the previous server-side type and importance heuristics and their
  configuration settings without a compatibility path.

## Direct-user memory policy

- Fixed direct user memories always being stored as `ACTIVE`/`UNKNOWN`.
- Direct user statements are retained as `ACTIVE`; model-generated inferences are retained as `CANDIDATE`.
- Direct user memories now receive a server-assigned semantic type instead of
  defaulting unconditionally to `UNKNOWN`.
- Model inferences remain `CANDIDATE`/`INFERENCE`.
## Mandatory tool-call prompting

- Strengthened MCP server instructions so durable direct-user information is
  stored before the conversational response is drafted.
- Requires `store_memory` for durable direct-user statements before drafting the response.
- Clarified that `store_memory_candidate` must not replace `store_memory` for
  information the user directly stated.


## Named scan databases

- Replaced the scan command's required `--store` argument with optional `--name`.
- Derives the database name from the scanned directory when `--name` is omitted.
- Makes newly scanned databases immutable by default.
- Added mutually exclusive `--mutable` and `--immutable` flags.
- Added explicit `--replace`; existing named databases are never overwritten implicitly.
- Stores scan databases under `data/stores/<name>/` and writes their final mode to `manifest.json`.


## Filesystem store discovery

- Removed the persistent store registry and startup store fixture.
- Removed mount, unmount, and enable/disable MCP operations.
- Uses `data/stores/*/manifest.json` as the single source of truth.
- Discovers stores directly from disk and opens them lazily on first use.
- Kept locked-store usage and ranking overlays in a separate local overlay database.

## Search provider fallback chain

- Added provider-neutral search implementations for Exa, Brave Search, Tavily, SearXNG, and DuckDuckGo.
- Added configurable provider priority with automatic fallback after provider errors or empty results.
- Providers requiring credentials are skipped when not configured.
- DuckDuckGo remains the dependency-free final fallback.
- Added provider-chain tests covering errors, empty results, total failure, and configuration-based selection.


## Web search hang fix

- Reduced the default per-provider search timeout to 6 seconds.
- Added a separate 8-second page-fetch timeout.
- Added a 45-second overall acquisition budget.
- Switched the DuckDuckGo fallback to its lighter GET endpoint.
- Added flushed CLI progress messages on stderr for provider search, candidate discovery, fetching, indexing, and failures.
- Kept MCP operation silent unless a caller explicitly supplies a progress callback, preventing protocol corruption.
