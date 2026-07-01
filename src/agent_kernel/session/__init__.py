"""Session store. File-based JSON for M0–M2 (DESIGN.md §8); SQLite later once
concurrent sessions make it worth it.
"""

from .store import Session, SessionStore

__all__ = ["Session", "SessionStore"]
