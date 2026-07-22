# Patch Notes — Lifecycle Policy Abstraction

## Implemented

- Added `LifecycleAction` as an integer-backed `IntEnum`.
- Added a side-effect-free `LifecyclePolicy` abstraction.
- Added immutable lifecycle snapshots and explainable decisions.
- Candidate memories may be promoted by importance or repeated access.
- Confidence and source-quality minimums prevent weak candidates from promoting.
- Pinned memories are always eligible for active recall.
- Active memories are archived only when both low-importance and inactive beyond
  the configured window.
- Rejected memories require manual review and archived memories are not
  automatically reactivated.
- Added threshold validation so promotion and archival bands cannot overlap.

## Architectural boundary

The policy does not access SQLite and does not mutate memories. A later
lifecycle service can load repository rows, evaluate this policy, and apply
accepted decisions transactionally with audit metadata.

## Validation

- `pytest -q`: 17 passed.
- Python bytecode compilation passed.
- Ruff was not installed in the supplied environment, so linting was not run.

## Next milestone

Add migration-safe lifecycle audit metadata (`promotion_reason`,
`promoted_at`, and `archived_at`) and a repository-backed lifecycle evaluator
that applies policy decisions explicitly rather than during retrieval.
