"""``orchctl`` entry point. Subcommands (``prepare``, ...) land in later tasks."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Returns the process exit code."""
    args = sys.argv[1:] if argv is None else argv
    print("orchctl: no commands yet" if not args else f"orchctl: unknown command {args[0]!r}")
    return 0 if not args else 2
