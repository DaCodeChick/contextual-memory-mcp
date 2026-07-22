# Patch Notes

## Lifecycle audit and application service

This patch adds the storage-backed half of automatic lifecycle management while
keeping policy evaluation separate from database mutation.

- Added integer-backed `LifecycleReason` audit codes.
- Added migration 0004 for lifecycle reason and transition timestamps.
- Added `LifecycleService` for single-memory evaluation and batch passes.
- Added dry-run support so lifecycle decisions can be inspected safely.
- Added optimistic state guards to reject stale decisions.
- Manual state changes are marked with the `MANUAL` reason code.
- Promotion and archival timestamps survive future document reconciliation.

Automatic scheduling and MCP exposure are intentionally deferred to a later
small commit.
