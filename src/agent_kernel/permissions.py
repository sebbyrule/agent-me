"""Tool permission layer.

DESIGN.md §8 flags this as a decision to make *before M1 ships*, because a
permission layer is painful to retrofit around shell/file tools. So it is
designed in from the start:

- Every tool declares a `RiskLevel`.
- A `PermissionPolicy` maps (risk, mode) -> `Decision` (allow / ask / deny).
- The agent loop obtains an `ASK` confirmation through a caller-supplied async
  callback, so the *kernel* decides policy while the *frontend* owns the UX of
  confirming (REPL prompt now; a dialog in the Tauri app later). The kernel never
  hard-codes "just run it."

Default policy: reads run automatically; writes and shell execution require
explicit confirmation. Override with `AGENT_TOOL_POLICY` (ask | allow | deny) for
headless/locked-down runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    READ = "read"  # observes state only (read a file, list a dir)
    WRITE = "write"  # mutates local state (write/delete a file)
    EXEC = "exec"  # runs arbitrary commands (shell)


class Decision(str, Enum):
    ALLOW = "allow"  # run without asking
    ASK = "ask"  # ask the user to confirm first
    DENY = "deny"  # refuse outright


@dataclass(frozen=True)
class PermissionPolicy:
    #: "ask" (default), "allow" (auto-approve everything), or "deny" (refuse
    #: all non-read tools). Reads are always allowed regardless of mode.
    mode: str = "ask"

    def decide(self, risk: RiskLevel) -> Decision:
        if risk == RiskLevel.READ:
            return Decision.ALLOW
        if self.mode == "allow":
            return Decision.ALLOW
        if self.mode == "deny":
            return Decision.DENY
        return Decision.ASK
