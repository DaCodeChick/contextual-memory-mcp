# Multi-store foundation

- Added integer-backed READ_WRITE, READ_ONLY, and IMMUTABLE store modes.
- Requires store-qualified memory references and explicit write routing.
- Added persistent store registry and startup manifest loading.
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
