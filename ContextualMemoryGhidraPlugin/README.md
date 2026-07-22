# Contextual Memory Ghidra Scanner

A Ghidra Java extension whose sole responsibility is maintaining a project-scoped immutable SQLite database for later consumption by a Contextual Memory server.

## Commands

The plugin adds four actions under **Tools → Contextual Memory**:

- **Scan Project** — creates a database only when none exists.
- **Update Project Database** — synchronizes the existing database with the current project.
- **Rescan Project** — rebuilds the database in a temporary file and atomically replaces it.
- **Clear Project Database** — deletes the project database.

Each scan walks every domain file in the current Ghidra project, opens program files read-only, records program metadata, and decompiles every non-external function. The completed SQLite file is made read-only.

## Database naming

The database filename is derived from the Ghidra project name. For example:

```text
Ghidra project: Ragnarok Online 2
Database:       ragnarok-online-2.sqlite
```

The default output directory is:

```text
~/.contextual-memory/ghidra/
```

Override it when launching Ghidra:

```text
-Dcontextual.memory.ghidra.databaseDir=/path/to/databases
```

## Build

Ghidra 12.1.x uses JDK 21. Build against the installed Ghidra distribution:

```bash
gradle -PGHIDRA_INSTALL_DIR=/path/to/ghidra buildExtension
```

The build downloads and bundles the Xerial SQLite JDBC driver into `lib/`.

## Database contract

Schema version 1 contains:

- `metadata`
- `programs`
- `functions`

Function identity is stable across renames and decompiler output changes because it is based on the program identity and function entry address. `content_hash` changes when extracted function content changes.

The database is a scanner-owned interchange artifact. It intentionally does not depend on, import, or embed the Python MCP server.
