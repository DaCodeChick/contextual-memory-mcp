SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    modified_ns INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'file',
    indexed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS segments (
    segment_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    heading TEXT,
    text TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    importance REAL NOT NULL DEFAULT 1.0,
    identity_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE(source_id, ordinal),
    UNIQUE(source_id, identity_key)
);

CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
    segment_id UNINDEXED,
    text,
    heading,
    concepts,
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS concepts (
    concept_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    concept_type TEXT NOT NULL DEFAULT 'concept',
    importance REAL NOT NULL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS segment_concepts (
    segment_id TEXT NOT NULL REFERENCES segments(segment_id) ON DELETE CASCADE,
    concept_id TEXT NOT NULL REFERENCES concepts(concept_id) ON DELETE CASCADE,
    relation TEXT NOT NULL DEFAULT 'mentions',
    weight REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY(segment_id, concept_id, relation)
);

CREATE TABLE IF NOT EXISTS concept_edges (
    source_concept_id TEXT NOT NULL REFERENCES concepts(concept_id) ON DELETE CASCADE,
    target_concept_id TEXT NOT NULL REFERENCES concepts(concept_id) ON DELETE CASCADE,
    relation TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    evidence_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(source_concept_id, target_concept_id, relation)
);
"""
