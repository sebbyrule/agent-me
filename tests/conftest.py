"""Shared pytest setup.

The MCP client spawns server subprocesses via asyncio. On Windows this needs the
Proactor event loop — which is the default there since Python 3.8, so no policy
override is required (and the policy API is deprecated as of 3.14). This file is
kept as the place to add such setup if the default ever changes.
"""
