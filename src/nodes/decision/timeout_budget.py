"""Monotonic timeout budget for one asynchronous operation."""

from __future__ import annotations

import time
from typing import Callable, Optional


class ElapsedTimeoutBudget:
    """Track one deadline without depending on wall-clock adjustments."""

    def __init__(
        self,
        timeout_sec: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.timeout_sec = max(0.1, float(timeout_sec))
        self._clock = clock
        self._started_at: Optional[float] = None

    @property
    def active(self) -> bool:
        return self._started_at is not None

    def start(self) -> None:
        self._started_at = self._clock()

    def reset(self) -> None:
        self._started_at = None

    def elapsed(self) -> Optional[float]:
        if self._started_at is None:
            return None
        return max(0.0, self._clock() - self._started_at)

    def expired(self) -> bool:
        elapsed = self.elapsed()
        return elapsed is not None and elapsed > self.timeout_sec
