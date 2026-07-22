# Patch Notes — Stable Segment Identity and Reconciliation

## Implemented

- Added a versioned SQLite migration runner in `database/migrations.py`.
- Added `segments.identity_key` and `segments.content_hash`.
- Migrates existing databases without deleting indexed content.
- Segment IDs now derive from stable source/section/chunk identity instead of content.
- Replaced destructive document replacement with hash-aware reconciliation.
- Existing segment rows are updated in place so future learned state can survive rescans.
- Removed segments are deleted and returned for vector cleanup.
- Chroma now uses upsert/delete instead of deleting an entire source before every update.
- Explicit memories now use a title-stable source ID so editing a memory can reconcile it.
- Concept edges are rebuilt from current segment evidence to avoid stale counts.
- Added regression tests for stable segment IDs across content edits.

## Validation

- `pytest -q`: 3 passed.
- Legacy-schema migration check passed.
- Python bytecode compilation passed.
- Ruff was not installed in the supplied environment, so linting was not run.

## Next milestone

Add learned-memory columns and ranking inputs only after this stable identity foundation is accepted.
