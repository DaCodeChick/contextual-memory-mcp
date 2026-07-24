from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.memory_matrix import ContextualMemoryMatrix


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Index files into the contextual memory database."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    scan = subcommands.add_parser(
        "scan",
        help="Scan a file or directory into a memory database.",
    )
    scan.add_argument(
        "target",
        nargs="?",
        help="File, directory, or URL to index.",
    )
    scan.add_argument(
        "--search",
        metavar="QUERY",
        help="Search the web and index selected results instead of scanning a path.",
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
        "--name",
        metavar="NAME",
        help=(
            "Database name. When omitted, index into the default main store. "
            "A missing named database is created automatically."
        ),
    )
    mutability = scan.add_mutually_exclusive_group()
    mutability.add_argument(
        "--mutable",
        action="store_true",
        help="Keep the scanned database writable after indexing.",
    )
    mutability.add_argument(
        "--immutable",
        action="store_true",
        help="Lock the scanned database after indexing (default).",
    )
    scan.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing database with the resolved name.",
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
        "--store",
        required=True,
        help="Writable store ID to clear.",
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
        if args.search:
            if args.target:
                parser.error("scan accepts either TARGET or --search, not both")
            result = memory.scan_web_query(
                args.search,
                name=args.name,
                mutable=args.mutable,
                replace=args.replace,
                force=args.force,
                progress=lambda message: print(message, file=sys.stderr, flush=True),
            )
        else:
            if not args.target:
                parser.error("scan requires TARGET unless --search is provided")
            if str(args.target).startswith(("http://", "https://")):
                result = memory.scan_url(
                    str(args.target),
                    name=args.name,
                    mutable=args.mutable,
                    replace=args.replace,
                    force=args.force,
                )
            else:
                result = memory.scan(
                    target=Path(args.target),
                    name=args.name,
                    mutable=args.mutable,
                    replace=args.replace,
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
        result = memory.clear(args.store)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
