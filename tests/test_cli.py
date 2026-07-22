from pathlib import Path

import pytest

from main import build_parser


def test_scan_cli_defaults_to_immutable_derived_name() -> None:
    args = build_parser().parse_args(["scan", "/tmp/project"])
    assert args.directory == Path("/tmp/project")
    assert args.name is None
    assert args.mutable is False
    assert args.immutable is False
    assert args.replace is False


def test_scan_cli_accepts_name_and_mutability() -> None:
    args = build_parser().parse_args(
        ["scan", "/tmp/project", "--name", "custom", "--mutable", "--replace"]
    )
    assert args.name == "custom"
    assert args.mutable is True
    assert args.replace is True


def test_scan_cli_rejects_conflicting_mutability_flags() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["scan", "/tmp/project", "--mutable", "--immutable"]
        )
