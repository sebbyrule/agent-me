"""Entrypoint: `agent-kernel` (or `python -m agent_kernel`).

Starts the long-running kernel process — a normal local server bound to
localhost (DESIGN.md §3). Frontends connect over HTTP/WS.
"""

from __future__ import annotations

import uvicorn

from .api.app import create_app
from .config import get_config


def main() -> None:
    config = get_config()
    app = create_app(config)
    print(f"agent-me kernel listening on http://{config.host}:{config.port}")
    if not config.anthropic_api_key:
        print("  warning: ANTHROPIC_API_KEY is not set — conversations will fail.")
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
