"""Entrypoint: `agent` (or `python -m agent_cli`)."""

from __future__ import annotations

from dotenv import load_dotenv

from .repl import run

load_dotenv()


def main() -> None:
    try:
        run()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
