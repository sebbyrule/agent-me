"""Entrypoint: `agent` (or `python -m agent_cli`)."""

from __future__ import annotations

import sys

from dotenv import load_dotenv

from .repl import run

# Windows consoles default to a legacy codepage (cp1252); the REPL renders a few
# non-ASCII glyphs (tool/permission markers), so force UTF-8 to avoid crashes.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

load_dotenv()


def main() -> None:
    try:
        run()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
