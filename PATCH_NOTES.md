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

## Automatic memory capture

- Replaced the permission-oriented `remember_memory` MCP tool with
  `store_memory`, whose server instructions require silent automatic capture of
  durable direct-user information.
- Direct user statements can be stored as either active or candidate memories;
  sensitive or one-off material no longer needs a conversational permission
  prompt merely to be retained conservatively.
- Model-generated hypotheses remain separated through
  `store_memory_candidate` and use model-inference origin metadata.
- Memory type and importance are now required model-supplied fields for both
  direct memories and inferred candidates.
- Importance is normalized to the supported `0.0` to `2.0` range; lifecycle,
  origin, confidence, source quality, and sensitive retention remain
  server-owned.
- Removed the previous server-side type and importance heuristics and their
  configuration settings without a compatibility path.

## Sensitive direct-user memory policy

- Fixed direct user memories always being stored as `ACTIVE`/`UNKNOWN`.
- Sensitive personal history is now retained conservatively as `CANDIDATE`.
- Direct user memories now receive a server-assigned semantic type instead of
  defaulting unconditionally to `UNKNOWN`.
- Model inferences remain `CANDIDATE`/`INFERENCE`.
## Mandatory tool-call prompting

- Strengthened MCP server instructions so durable direct-user information is
  stored before the conversational response is drafted.
- Explicitly forbids skipping `store_memory` because a disclosure is sensitive,
  traumatic, medical, deeply personal, or part of a supportive conversation.
- Clarified that `store_memory_candidate` must not replace `store_memory` for
  sensitive information the user directly stated.

