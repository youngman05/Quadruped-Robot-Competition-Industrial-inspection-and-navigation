"""Small, ROS-independent SE(2) pose controller for precision maneuvers.

The controller keeps a fixed world-frame position while changing heading.  It
also works for short pose corrections.  Position errors are transformed into
the robot frame and corrected together with yaw so turn-induced translation is
fed back on the next control cycle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


def normalize_angle(value: float) -> float:
    """Wrap an angle to [-pi, pi]."""
    while value > math.pi:
        value -= 2.0 * math.pi
    while value < -math.pi:
        value += 2.0 * math.pi
    return value


def clamp(value: float, limit: float) -> float:
    limit = abs(float(limit))
    return max(-limit, min(limit, float(value)))


def rate_limit(value: float, previous: float, max_rate: float, dt: float) -> float:
    max_delta = abs(float(max_rate)) * max(0.0, float(dt))
    return previous + clamp(value - previous, max_delta)


@dataclass(frozen=True)
class Se2ControllerConfig:
    kx: float = 0.8
    ky: float = 0.8
    ktheta: float = 0.8
    coarse_max_vx: float = 0.06
    coarse_max_vy: float = 0.04
    coarse_max_wz: float = 0.12
    fine_max_vx: float = 0.03
    fine_max_vy: float = 0.02
    fine_max_wz: float = 0.06
    fine_position_radius: float = 0.12
    fine_yaw_error: float = 0.35
    position_tolerance: float = 0.08
    yaw_tolerance: float = 0.12
    max_linear_accel: float = 0.15
    max_angular_accel: float = 0.30


@dataclass(frozen=True)
class Se2ControlOutput:
    vx: float
    vy: float
    wz: float
    error_x_body: float
    error_y_body: float
    error_yaw: float
    position_error: float
    mode: str
    reached: bool


class DirectedYawTracker:
    """Unwrap yaw while preserving an explicitly requested turn direction."""

    def __init__(self, start_yaw: float, target_yaw: float, direction: str) -> None:
        if direction not in ("shortest", "clockwise", "counterclockwise"):
            raise ValueError("direction must be shortest, clockwise, or counterclockwise")

        self.previous_wrapped = normalize_angle(start_yaw)
        self.current_unwrapped = float(self.previous_wrapped)
        delta = normalize_angle(target_yaw - self.previous_wrapped)
        if direction == "clockwise" and delta > 0.0:
            delta -= 2.0 * math.pi
        elif direction == "counterclockwise" and delta < 0.0:
            delta += 2.0 * math.pi
        self.target_unwrapped = self.current_unwrapped + delta

    def update(self, yaw: float) -> float:
        wrapped = normalize_angle(yaw)
        self.current_unwrapped += normalize_angle(wrapped - self.previous_wrapped)
        self.previous_wrapped = wrapped
        return self.current_unwrapped

    @property
    def error(self) -> float:
        return self.target_unwrapped - self.current_unwrapped


class Se2PoseController:
    """Feedback controller for a fixed planar pose target."""

    def __init__(self, config: Optional[Se2ControllerConfig] = None) -> None:
        self.config = config or Se2ControllerConfig()
        self._yaw_tracker: Optional[DirectedYawTracker] = None
        self._target_x = 0.0
        self._target_y = 0.0
        self._previous_vx = 0.0
        self._previous_vy = 0.0
        self._previous_wz = 0.0

    def start(
        self,
        target_x: float,
        target_y: float,
        start_yaw: float,
        target_yaw: float,
        direction: str = "shortest",
    ) -> None:
        self._target_x = float(target_x)
        self._target_y = float(target_y)
        self._yaw_tracker = DirectedYawTracker(start_yaw, target_yaw, direction)
        self._previous_vx = 0.0
        self._previous_vy = 0.0
        self._previous_wz = 0.0

    def compute(self, x: float, y: float, yaw: float, dt: float) -> Se2ControlOutput:
        if self._yaw_tracker is None:
            raise RuntimeError("controller.start() must be called before compute()")
        if not all(math.isfinite(value) for value in (x, y, yaw, dt)):
            raise ValueError("pose and dt must be finite")

        self._yaw_tracker.update(yaw)
        error_yaw = self._yaw_tracker.error
        dx = self._target_x - float(x)
        dy = self._target_y - float(y)
        cos_yaw = math.cos(yaw)
        sin_yaw = math.sin(yaw)
        error_x_body = cos_yaw * dx + sin_yaw * dy
        error_y_body = -sin_yaw * dx + cos_yaw * dy
        position_error = math.hypot(dx, dy)

        reached = (
            position_error <= self.config.position_tolerance
            and abs(error_yaw) <= self.config.yaw_tolerance
        )
        if reached:
            self._previous_vx = 0.0
            self._previous_vy = 0.0
            self._previous_wz = 0.0
            return Se2ControlOutput(
                vx=0.0,
                vy=0.0,
                wz=0.0,
                error_x_body=error_x_body,
                error_y_body=error_y_body,
                error_yaw=error_yaw,
                position_error=position_error,
                mode="settle",
                reached=True,
            )

        fine = (
            position_error <= self.config.fine_position_radius
            and abs(error_yaw) <= self.config.fine_yaw_error
        )
        if fine:
            max_vx = self.config.fine_max_vx
            max_vy = self.config.fine_max_vy
            max_wz = self.config.fine_max_wz
            mode = "fine_track"
        else:
            max_vx = self.config.coarse_max_vx
            max_vy = self.config.coarse_max_vy
            max_wz = self.config.coarse_max_wz
            mode = "coarse_track"

        safe_dt = min(max(float(dt), 0.0), 0.5)
        desired_wz = clamp(self.config.ktheta * error_yaw, max_wz)
        wz = rate_limit(
            desired_wz,
            self._previous_wz,
            self.config.max_angular_accel,
            safe_dt,
        )
        # These coupling terms cancel the body-frame error rotation caused by wz.
        desired_vx = clamp(
            self.config.kx * error_x_body + wz * error_y_body,
            max_vx,
        )
        desired_vy = clamp(
            self.config.ky * error_y_body - wz * error_x_body,
            max_vy,
        )

        vx = rate_limit(
            desired_vx,
            self._previous_vx,
            self.config.max_linear_accel,
            safe_dt,
        )
        vy = rate_limit(
            desired_vy,
            self._previous_vy,
            self.config.max_linear_accel,
            safe_dt,
        )
        self._previous_vx = vx
        self._previous_vy = vy
        self._previous_wz = wz

        return Se2ControlOutput(
            vx=vx,
            vy=vy,
            wz=wz,
            error_x_body=error_x_body,
            error_y_body=error_y_body,
            error_yaw=error_yaw,
            position_error=position_error,
            mode=mode,
            reached=False,
        )
