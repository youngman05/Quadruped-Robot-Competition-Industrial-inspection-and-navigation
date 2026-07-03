"""
Dog Motion Controller — unified API for Navigator.

Handles:
  - Dog UDP communication (heartbeat, auto mode, MotionComplexCMD)
  - cuVSLAM odometry reading (from /tmp/odom_latest.json)
  - Yaw calibration (cuVSLAM raw yaw → physical yaw)
  - Odom freeze watchdog
  - Low-level: set_velocity(vx, az) — for pure pursuit
  - High-level: move_forward(d), turn_to(deg) — PID closed-loop
  - Position query: pose property (x, y, yaw_deg)

Usage:
  mc = MotionController()
  mc.initialize()                        # auto mode + heartbeat + yaw calib

  # Low-level (Navigator pure pursuit):
  mc.set_velocity(0.3, 0.0)             # walk forward at 0.3 m/s

  # High-level (task_manager):
  mc.turn_to(180)                        # turn to face 180 deg
  mc.move_forward(3.0)                   # walk 3m forward (PID)
  mc.is_done                             # True when reached

  # Position:
  x, y, yaw = mc.pose                   # updated every ~20Hz

  # Cleanup:
  mc.stop()
  mc.shutdown()
"""

from __future__ import annotations
import socket
import struct
import time
import math
import json
import threading
import os

# ── Constants ─────────────────────────────────────
DOG_IP = "192.168.1.120"
DOG_CMD_PORT = 43893
ODOM_FILE = "/tmp/odom_latest.json"

CMD_HEARTBEAT = 0x21040001
CMD_AUTO_MODE = 0x21010C03
CMD_MOTION    = 0x21010D06
CMD_LIE_DOWN  = 0x21010C0E

CODE_FWD = 320   # forward velocity (m/s)
CODE_LAT = 325   # lateral velocity (m/s)
CODE_YAW = 321   # angular velocity (rad/s, negated)


class OdomFreezeError(RuntimeError):
    """Raised when odom is frozen > 5s and dog lies down."""


class MotionController:
    """Unified motion control + odometry for the Lite3 dog."""

    def __init__(self, dog_ip: str = DOG_IP, dog_port: int = DOG_CMD_PORT,
                 odom_file: str = ODOM_FILE):
        self._dog_addr = (dog_ip, dog_port)
        self._odom_file = odom_file

        # Socket (created in initialize)
        self._sock: socket.socket | None = None

        # Odom state (lock-protected)
        self._lock = threading.Lock()
        self._x = 0.0
        self._y = 0.0
        self._yaw_raw = 0.0       # cuVSLAM raw yaw (deg)
        self._yaw_offset = 0.0    # calibration offset
        self._init_pose = None    # (x, y, yaw_raw) at start
        self._odom_ts = 0.0       # last update timestamp
        self._odom_count = 0
        self._running = False

        # High-level action state
        self._action_done = threading.Event()
        self._action_ok = False
        self._action_thread: threading.Thread | None = None

    # ── Lifecycle ──────────────────────────────────

    def initialize(self, desired_start_yaw_deg: float = 0.0,
                   calibrate_yaw: bool = True):
        """Start odom reader, create UDP socket, set auto mode.

        Args:
            desired_start_yaw_deg: Physical yaw that cuVSLAM's current
                orientation maps to. Default 0 = forward is +X.
            calibrate_yaw: If True, auto-calibrate on first reading.
        """
        # Create UDP socket
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Start odom reader thread
        self._running = True
        t = threading.Thread(target=self._odom_loop, daemon=True)
        t.start()

        # Wait for first odom
        for _ in range(50):
            with self._lock:
                if self._odom_count > 3:
                    break
            time.sleep(0.1)
        else:
            raise RuntimeError("No odometry received after 5s — is cuVSLAM running?")

        # Heartbeat + auto mode
        for _ in range(10):
            self._send_simple(CMD_HEARTBEAT)
            time.sleep(0.1)
        self._send_simple(CMD_AUTO_MODE)
        time.sleep(0.5)
        self._send_simple(CMD_MOTION)
        time.sleep(0.3)

        # Yaw calibration
        if calibrate_yaw:
            with self._lock:
                raw = self._yaw_raw
            self._yaw_offset = desired_start_yaw_deg - raw
            print(f"[MotionCtrl] Yaw calibrated: raw={raw:.0f} deg "
                  f"desired={desired_start_yaw_deg:.0f} deg "
                  f"offset={self._yaw_offset:.0f} deg")

        print(f"[MotionCtrl] Initialized. Pose: {self.pose}")

    def shutdown(self):
        """Stop all threads, close socket, stop dog."""
        self._running = False
        if self._action_thread and self._action_thread.is_alive():
            self._action_done.set()
        self.stop()
        if self._sock:
            self._sock.close()
            self._sock = None

    # ── Pose query ─────────────────────────────────

    @property
    def pose(self) -> tuple[float, float, float]:
        """Current (x_m, y_m, yaw_deg) in calibrated frame.

        Yaw is calibrated: 0 deg = physical forward (as set in initialize).
        Position is relative to first odom reading.
        """
        with self._lock:
            if self._init_pose is None:
                return 0.0, 0.0, 0.0
            x = self._x - self._init_pose[0]
            y = self._y - self._init_pose[1]
            yaw = self._yaw_raw + self._yaw_offset - self._init_pose[2]
            while yaw < -180:
                yaw += 360
            while yaw >= 180:
                yaw -= 360
            return x, y, yaw

    @property
    def odom_stale_sec(self) -> float:
        """Seconds since last odom update."""
        with self._lock:
            return time.time() - self._odom_ts

    @property
    def has_odom(self) -> bool:
        """True if odometry has been received."""
        with self._lock:
            return self._odom_count > 0

    # ── Low-level velocity control ─────────────────

    def set_velocity(self, vx: float, az: float):
        """Send velocity command to dog. Non-blocking.

        For use by Navigator pure_pursuit control loop (10Hz).

        Args:
            vx: Forward velocity (m/s), positive = forward.
            az: Angular velocity (rad/s), positive = left turn (ROS convention).
                Automatically negated per dog SDK convention.
        """
        if not self._sock:
            return

        # Heartbeat (dog requires same source)
        self._send_simple(CMD_HEARTBEAT)

        # Only send ONE motion type — dog firmware:
        # last MotionComplexCMD overrides previous.
        if abs(az) > 0.08:
            # Rotate
            self._send_complex(CODE_YAW, float(-az))
        elif abs(vx) > 0.01:
            # Forward
            self._send_complex(CODE_FWD, float(vx))
        else:
            # Stop
            self._send_complex(CODE_FWD, 0.0)

    def stop(self):
        """Send stop command (zero velocity)."""
        if self._sock:
            self._send_complex(CODE_FWD, 0.0)

    def lie_down(self):
        """Make the dog lie down (soft emergency stop)."""
        if self._sock:
            self._send_simple(CMD_LIE_DOWN)

    # ── High-level PID actions (blocking) ──────────

    def turn_to(self, target_yaw_deg: float, timeout: float = 20.0,
                tolerance: float = 5.0) -> bool:
        """Turn in place to absolute yaw. Blocks until done or timeout.

        Returns True if reached within tolerance deg.
        """
        t0 = time.time()
        while time.time() - t0 < timeout:
            self._check_watchdog()
            _, _, yaw = self.pose
            err = target_yaw_deg - yaw
            while err < -180: err += 360
            while err >= 180: err -= 360

            if abs(err) < 5.0:
                self.stop()
                return True

            az = max(-0.8, min(0.8, 0.03 * err))
            if abs(az) < 0.08:
                az = 0.08 * (1 if az > 0 else -1)
            self._send_simple(CMD_HEARTBEAT)
            self._send_complex(CODE_YAW, float(-az))
            time.sleep(0.1)

        self.stop()
        return False

    def move_forward(self, distance_m: float, timeout: float = 60.0) -> bool:
        """Walk forward `distance_m` using simple P control. Blocks.

        Returns True if reached within 6 cm tolerance.
        """
        x0, y0, _ = self.pose
        t0 = time.time()

        while time.time() - t0 < timeout:
            self._check_watchdog()
            x, y, _ = self.pose
            traveled = math.hypot(x - x0, y - y0)
            remaining = distance_m - traveled

            if remaining < 0.06:
                self.stop()
                return True

            vx = 0.35
            if remaining < 0.3:
                vx = max(0.08, 0.35 * remaining / 0.3)

            self._send_simple(CMD_HEARTBEAT)
            self._send_complex(CODE_FWD, float(vx))
            time.sleep(0.1)

        self.stop()
        return False

    # ── Watchdog ───────────────────────────────────

    def _check_watchdog(self):
        """Check odom freshness. Raises OdomFreezeError if frozen > 5s."""
        s = self.odom_stale_sec
        if s > 0.4:
            self.stop()
            t0 = time.time()
            while time.time() - t0 < 5.0:
                time.sleep(0.2)
                if self.odom_stale_sec < 0.2:
                    return  # recovered
            # Not recovered — lie down
            self.lie_down()
            raise OdomFreezeError(
                f"Odom frozen for {s:.1f}s, not recovered in 5s — dog laid down"
            )

    # ── Internal ───────────────────────────────────

    def _send_simple(self, code: int, p1: int = 0, p2: int = 0):
        """Send SimpleCMD (12 bytes)."""
        if self._sock:
            self._sock.sendto(
                struct.pack('<3i', code, p1, p2), self._dog_addr
            )

    def _send_complex(self, code: int, data: float):
        """Send MotionComplexCMD (20 bytes)."""
        if self._sock:
            self._sock.sendto(
                struct.pack('<3id', code, 8, 1, data), self._dog_addr
            )

    def _odom_loop(self):
        """Background thread: read cuVSLAM odom file at ~25Hz."""
        while self._running:
            try:
                with open(self._odom_file) as f:
                    d = json.load(f)
                x = float(d['x']); y = float(d['y'])
                qx = float(d['qx']); qy = float(d['qy'])
                qz = float(d['qz']); qw = float(d['qw'])
                siny = 2.0 * (qw * qz + qx * qy)
                cosy = 1.0 - 2.0 * (qy * qy + qz * qz)
                yaw = math.degrees(math.atan2(siny, cosy))

                with self._lock:
                    self._x = x; self._y = y
                    self._yaw_raw = yaw
                    self._odom_ts = time.time()
                    self._odom_count += 1
                    if self._init_pose is None:
                        self._init_pose = (x, y, yaw)
            except Exception:
                pass
            time.sleep(0.04)
