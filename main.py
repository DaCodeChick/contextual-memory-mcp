from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.memory_matrix import ContextualMemoryMatrix


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Index files into the contextual memory database."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    scan = subcommands.add_parser(
        "scan",
        help="Scan a user-specified directory and update the persistent index.",
    )
    scan.add_argument(
        "directory",
        type=Path,
        help="Directory containing the files to index.",
    )
    scan.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "Exclude a subdirectory name or relative path. "
            "May be supplied more than once."
        ),
    )
    scan.add_argument(
        "--force",
        action="store_true",
        help="Re-index files even when their content hash is unchanged.",
    )

    clear = subcommands.add_parser(
        "clear",
        help="Delete all indexed sources, segments, concepts, graph edges, and vectors.",
    )
    clear.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the destructive operation without an interactive prompt.",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    memory = ContextualMemoryMatrix()

    if args.command == "scan":
        result = memory.ingestion.scan(
            directory=args.directory,
            force=args.force,
            excludes=args.exclude,
        )
    else:
        if not args.yes:
            answer = input(
                "Clear the entire contextual memory database? "
                "This cannot be undone. [y/N] "
            )
            if answer.strip().lower() not in {"y", "yes"}:
                print("Clear cancelled.")
                return
        result = memory.clear()

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
