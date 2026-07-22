# Memory Importance Consolidation

This patch completes the planned memory-importance lifecycle for the current branch.

## Implemented

- Persistent integer-backed importance audit reasons.
- Migration-safe importance bookkeeping:
  - `importance_access_count`
  - `importance_reason`
  - `importance_updated_at`
- Configurable access reinforcement.
- Configurable inactivity decay with a grace period, floor, ceiling, and pinned-memory protection.
- Incremental decay that does not double-apply when maintenance runs repeatedly.
- Optimistic concurrency checks for stale importance decisions.
- A repository-backed `ImportanceService` with dry-run support.
- A combined maintenance pass that applies importance changes before lifecycle promotion/archive decisions.
- Chroma importance metadata synchronization.
- Recency as an explainable ranking component.
- Environment configuration for importance and recency policy.
- MCP `run_memory_maintenance` tool.
- Tests covering reinforcement, decay, pin protection, persistence, and dry runs.

## Validation

- `28 passed`
- Python bytecode compilation passed.
- Ruff was not installed in the supplied environment.
