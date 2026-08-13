"""Pure consecutive-health and velocity policy for cone avoidance."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple


Command3 = Tuple[float, float, float]
ZERO_COMMAND: Command3 = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class ConeGateDecision:
    command: Command3
    allowed: bool
    reason: str


class ConeScanHealthTracker:
    def __init__(self, required_consecutive: int = 3, max_age_sec: float = 0.25):
        self.required_consecutive = max(1, int(required_consecutive))
        self.max_age_sec = max(0.05, float(max_age_sec))
        self.stream_id = ""
        self.last_sequence = 0
        self.last_healthy_time: Optional[float] = None
        self.consecutive = 0
        self.last_reason = "waiting for cone scan health"

    def observe(
        self,
        stream_id: str,
        sequence: int,
        healthy: bool,
        now: float,
        reason: str = "",
    ) -> None:
        stream_id = str(stream_id)
        sequence = int(sequence)
        now = float(now)
        new_stream = bool(stream_id and stream_id != self.stream_id)
        regressed = bool(
            stream_id
            and stream_id == self.stream_id
            and sequence <= self.last_sequence
        )
        stale_gap = bool(
            self.last_healthy_time is not None
            and now - self.last_healthy_time > self.max_age_sec
        )
        if new_stream or regressed or stale_gap or not healthy:
            self.consecutive = 0
        if new_stream:
            self.stream_id = stream_id
            self.last_sequence = 0
        if regressed:
            self.last_reason = "health sequence did not advance"
            self.last_healthy_time = None
            return
        if not healthy:
            self.last_reason = reason or "cone scan source is unhealthy"
            self.last_healthy_time = None
            if stream_id:
                self.stream_id = stream_id
                self.last_sequence = max(self.last_sequence, sequence)
            return
        if not stream_id or sequence < 1 or not math.isfinite(now):
            self.last_reason = "invalid cone scan health metadata"
            self.last_healthy_time = None
            self.consecutive = 0
            return
        self.stream_id = stream_id
        self.last_sequence = sequence
        self.last_healthy_time = now
        self.consecutive += 1
        if self.consecutive < self.required_consecutive:
            self.last_reason = "warming up healthy cone scans (%d/%d)" % (
                self.consecutive,
                self.required_consecutive,
            )
        else:
            self.last_reason = "ready"

    def readiness(self, now: float) -> Tuple[bool, str]:
        now = float(now)
        if self.last_healthy_time is None:
            return False, self.last_reason
        age = now - self.last_healthy_time
        if not math.isfinite(age) or age < 0.0 or age > self.max_age_sec:
            self.consecutive = 0
            self.last_healthy_time = None
            self.last_reason = "cone scan health is stale"
            return False, self.last_reason
        if self.consecutive < self.required_consecutive:
            return False, self.last_reason
        return True, "ready"

    def evaluate(
        self,
        command: Command3,
        command_time: Optional[float],
        now: float,
        command_timeout_sec: float,
        require_scan_health: bool = True,
    ) -> ConeGateDecision:
        if not all(math.isfinite(float(value)) for value in command):
            return ConeGateDecision(ZERO_COMMAND, False, "non-finite velocity command")
        if command_time is None:
            return ConeGateDecision(ZERO_COMMAND, False, "waiting for velocity command")
        command_age = float(now) - float(command_time)
        if (
            not math.isfinite(command_age)
            or command_age < 0.0
            or command_age > float(command_timeout_sec)
        ):
            return ConeGateDecision(ZERO_COMMAND, False, "velocity command is stale")
        if require_scan_health:
            ready, reason = self.readiness(now)
            if not ready:
                return ConeGateDecision(ZERO_COMMAND, False, reason)
        return ConeGateDecision(
            tuple(float(value) for value in command),
            True,
            "ready" if require_scan_health else "cone avoidance bypassed",
        )
