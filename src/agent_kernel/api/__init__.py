"""The kernel's local API — the single contract every frontend speaks (DESIGN.md
§3, §4.1). If a frontend needs something, it is added here, never reached in
around.
"""

from .app import create_app

__all__ = ["create_app"]
