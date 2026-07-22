from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from core.memory_matrix import PromptMemoryMatrix


def main() -> None:
    parser = argparse.ArgumentParser(description="Prompt Memory MCP index utility")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--force", action="store_true")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=8)
    context = sub.add_parser("context")
    context.add_argument("task")
    context.add_argument("--top-k", type=int, default=8)
    sub.add_parser("stats")
    args = parser.parse_args()
    memory = PromptMemoryMatrix()
    if args.command == "scan":
        result = memory.ingestion.scan(args.force)
    elif args.command == "search":
        result = [asdict(hit) for hit in memory.retrieval.search(args.query, args.top_k)]
    elif args.command == "context":
        print(memory.context.build(args.task, args.top_k))
        return
    else:
        result = memory.stats()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
