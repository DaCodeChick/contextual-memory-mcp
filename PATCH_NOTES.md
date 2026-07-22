# Lifecycle Configuration and Vector Synchronization

## Summary

This patch integrates the repository-backed lifecycle service with the main
memory facade and MCP server.

## Changes

- Adds environment-configurable promotion and archival thresholds.
- Adds `ContextualMemoryMatrix.lifecycle` using the configured policy.
- Adds `ContextualMemoryMatrix.run_lifecycle()`.
- Synchronizes applied lifecycle transitions into Chroma metadata.
- Adds `run_memory_lifecycle` MCP tool with dry-run support.
- Reports changed segment IDs from lifecycle passes.
- Expands lifecycle metadata reads to include memory type and origin.
- Adds tests for changed IDs, configured thresholds, and vector synchronization.

## Validation

- `23 passed`
- Python bytecode compilation passed.

## Suggested commit

`Integrate configurable lifecycle passes`
