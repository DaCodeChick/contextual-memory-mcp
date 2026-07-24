from pathlib import Path

import pytest

from main import build_parser


def test_scan_cli_defaults_to_main_store() -> None:
    args = build_parser().parse_args(["scan", "/tmp/project"])
    assert args.target == "/tmp/project"
    assert args.name is None
    assert args.mutable is False
    assert args.immutable is False
    assert args.replace is False


def test_scan_cli_accepts_file_name_and_mutability() -> None:
    args = build_parser().parse_args(
        ["scan", "/tmp/character.md", "--name", "roleplay", "--mutable", "--replace"]
    )
    assert args.target == "/tmp/character.md"
    assert args.name == "roleplay"
    assert args.mutable is True
    assert args.replace is True


def test_scan_cli_rejects_conflicting_mutability_flags() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["scan", "/tmp/project", "--mutable", "--immutable"]
        )


def test_scan_cli_accepts_url() -> None:
    args = build_parser().parse_args(["scan", "https://example.com/wiki/Foo"])
    assert args.target.startswith("https://")
    assert args.search is None


def test_scan_cli_accepts_web_search() -> None:
    args = build_parser().parse_args(["scan", "--search", "L'Arachel Fire Emblem"])
    assert args.target is None
    assert args.search == "L'Arachel Fire Emblem"
