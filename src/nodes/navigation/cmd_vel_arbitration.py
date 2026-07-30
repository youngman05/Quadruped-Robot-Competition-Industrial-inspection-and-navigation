"""ROS-independent command arbitration state machine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


Command3 = Tuple[float, float, float]
ZERO_COMMAND: Command3 = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class ArbitrationDecision:
    mode: str
    command: Command3


class CmdVelArbitration:
    """Precision commands own a lease; stale leases release through a stop gap."""

    def __init__(
        self,
        nav_timeout: float,
        precision_timeout: float,
        release_stop: float,
    ) -> None:
        self.nav_timeout = float(nav_timeout)
        self.precision_timeout = float(precision_timeout)
        self.release_stop = float(release_stop)
        self.mode = "idle"
        self.nav_cmd = ZERO_COMMAND
        self.precision_cmd = ZERO_COMMAND
        self.nav_time = float("-inf")
        self.precision_time = float("-inf")
        self.release_until = float("-inf")

    def accept_nav(self, command: Command3, now: float) -> bool:
        if self.mode in ("precision", "precision_release"):
            return False
        self.nav_cmd = command
        self.nav_time = float(now)
        return True

    def accept_precision(self, command: Command3, now: float) -> bool:
        acquired = self.mode != "precision"
        self.precision_cmd = command
        self.precision_time = float(now)
        self.mode = "precision"
        return acquired

    def select(self, now: float) -> ArbitrationDecision:
        now = float(now)
        command = ZERO_COMMAND
        if self.mode == "precision":
            if now - self.precision_time <= self.precision_timeout:
                command = self.precision_cmd
            else:
                self.mode = "precision_release"
                self.release_until = now + self.release_stop
                self.nav_time = float("-inf")
        elif self.mode == "precision_release":
            if now >= self.release_until:
                self.mode = "idle"
        elif now - self.nav_time <= self.nav_timeout:
            self.mode = "nav2"
            command = self.nav_cmd
        else:
            self.mode = "idle"
        return ArbitrationDecision(self.mode, command)
