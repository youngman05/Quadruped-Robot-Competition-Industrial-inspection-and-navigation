#!/usr/bin/env python3
"""
Leg Odometry PID Closed-Loop Test

Uses the dog's own cuVSLAM odometry (RobotState UDP) for position feedback.
Runs PID control to follow a user-specified route, then plots the trajectory.

Usage:
  python3 scripts/test_leg_odom_pid.py --route "5,0; 0,-1; -3,0"
      → forward 5m, right 1m, backward 3m

  python3 scripts/test_leg_odom_pid.py --route "3,0; 3,0"
      → forward 3m, then forward another 3m

The dog MUST be standing and in auto mode before running.
(lite3_init.py handles this — make sure it's running)
"""

from __future__ import annotations
import socket
import struct
import time
import math
import sys
import argparse
import json
import os
import threading
import signal
from dataclasses import dataclass, field

# ── Constants ──────────────────────────────────────
DOG_IP = "192.168.1.120"
DOG_CMD_PORT = 43893          # send commands here
DOG_STATE_PORT = 43897        # receive RobotState here

CMD_HEARTBEAT = 0x21040001
CMD_AUTO_MODE = 0x21010C03
CMD_MOTION    = 0x21010D06

# MotionComplexCMD codes (SDK protocol)
CODE_FWD   = 320   # 0x0140 forward velocity
CODE_LAT   = 325   # 0x0145 lateral velocity
CODE_YAW   = 321   # 0x0141 angular velocity (negated)


@dataclass
class RobotPose:
    """Current robot pose from cuVSLAM odometry."""
    x: float = 0.0
    y: float = 0.0
    yaw_deg: float = 0.0   # degrees
    timestamp: float = 0.0
    seq: int = 0

    @property
    def yaw_rad(self) -> float:
        return math.radians(self.yaw_deg)


class CuvslamOdomReader:
    """Reads cuVSLAM odometry from /tmp/odom_latest.json (written by final_bridge)."""

    ODOM_FILE = "/tmp/odom_latest.json"

    def __init__(self):
        self._pose = RobotPose()
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._count = 0
        self._initial_pose = None

    @property
    def pose(self) -> RobotPose:
        with self._lock:
            return RobotPose(
                x=self._pose.x, y=self._pose.y,
                yaw_deg=self._pose.yaw_deg,
                timestamp=self._pose.timestamp, seq=self._pose.seq,
            )

    @property
    def relative_pose(self) -> RobotPose:
        p = self.pose
        if self._initial_pose is None:
            return RobotPose(0, 0, 0, p.timestamp, p.seq)
        return RobotPose(
            x=p.x - self._initial_pose.x,
            y=p.y - self._initial_pose.y,
            yaw_deg=p.yaw_deg - self._initial_pose.yaw_deg,
            timestamp=p.timestamp, seq=p.seq,
        )

    @property
    def count(self) -> int:
        return self._count

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)

    def _run(self):
        while self._running:
            try:
                with open(self.ODOM_FILE, 'r') as f:
                    d = json.load(f)
                x = float(d['x'])
                y = float(d['y'])
                qx = float(d['qx']); qy = float(d['qy'])
                qz = float(d['qz']); qw = float(d['qw'])
                siny = 2.0 * (qw * qz + qx * qy)
                cosy = 1.0 - 2.0 * (qy * qy + qz * qz)
                yaw_rad = math.atan2(siny, cosy)
                yaw_deg = math.degrees(yaw_rad)

                with self._lock:
                    self._pose = RobotPose(x=x, y=y, yaw_deg=yaw_deg,
                                           timestamp=time.time())
                    self._count += 1
                    if self._initial_pose is None:
                        self._initial_pose = RobotPose(
                            x=x, y=y, yaw_deg=yaw_deg,
                            timestamp=time.time(), seq=0)
            except Exception:
                pass
            time.sleep(0.05)  # 20Hz read rate


class DogController:
    """Sends MotionComplexCMD to the dog via UDP."""

    def __init__(self, ip: str = DOG_IP, port: int = DOG_CMD_PORT):
        self._addr = (ip, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def heartbeat(self):
        self._sock.sendto(
            struct.pack('<3i', CMD_HEARTBEAT, 0, 0), self._addr
        )

    def forward(self, speed_ms: float):
        """Send forward velocity command (m/s)."""
        self._sock.sendto(
            struct.pack('<3id', CODE_FWD, 8, 1, float(speed_ms)), self._addr
        )

    def rotate(self, speed_rads: float):
        """Send angular velocity command (rad/s). Negates per SDK convention."""
        self._sock.sendto(
            struct.pack('<3id', CODE_YAW, 8, 1, float(-speed_rads)), self._addr
        )

    def auto_mode(self):
        """Send auto mode + motion mode commands."""
        self._sock.sendto(
            struct.pack('<3i', CMD_AUTO_MODE, 0, 0), self._addr
        )
        time.sleep(0.5)
        self._sock.sendto(
            struct.pack('<3i', CMD_MOTION, 0, 0), self._addr
        )
        time.sleep(0.3)

    def stop(self):
        self._sock.sendto(
            struct.pack('<3id', CODE_FWD, 8, 1, 0.0), self._addr
        )

    def close(self):
        self.stop()
        self._sock.close()


def normalize_angle(deg: float) -> float:
    """Normalize angle to [-180, 180)."""
    while deg >= 180:
        deg -= 360
    while deg < -180:
        deg += 360
    return deg


class PIDController:
    """Simple PID for distance and heading."""

    def __init__(self, kp: float, ki: float = 0.0, kd: float = 0.0,
                 max_output: float = 1.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.max_output = max_output
        self._integral = 0.0
        self._prev_error = 0.0

    def reset(self):
        self._integral = 0.0
        self._prev_error = 0.0

    def compute(self, error: float, dt: float) -> float:
        self._integral += error * dt
        derivative = (error - self._prev_error) / max(dt, 0.001)
        self._prev_error = error
        output = self.kp * error + self.ki * self._integral + self.kd * derivative
        return max(-self.max_output, min(self.max_output, output))


@dataclass
class WaypointSegment:
    """A relative movement segment: walk dx meters forward, dy meters lateral."""
    dx: float   # forward distance (m)
    dy: float   # lateral distance (m), positive = left


def parse_route(route_str: str) -> list[WaypointSegment]:
    """Parse 'dx1,dy1; dx2,dy2; ...' into segments."""
    segments = []
    for part in route_str.split(';'):
        part = part.strip()
        if not part:
            continue
        parts = part.split(',')
        if len(parts) != 2:
            raise ValueError(f"Invalid segment '{part}': expected 'dx,dy'")
        segments.append(WaypointSegment(dx=float(parts[0]), dy=float(parts[1])))
    return segments


class RouteExecutor:
    """Executes a sequence of waypoint segments using PID closed-loop control."""

    def __init__(self, controller: DogController, odom: CuvslamOdomReader):
        self._ctrl = controller
        self._odom = odom

        # PID gains
        self._heading_pid = PIDController(kp=0.8, ki=0.0, kd=0.1, max_output=1.0)
        self._dist_pid = PIDController(kp=0.3, ki=0.01, kd=0.0, max_output=0.5)

        # Thresholds
        self._dist_tolerance = 0.05   # 5cm
        self._yaw_tolerance = 3.0     # 3 degrees

        # Max speeds
        self._max_fwd = 0.4    # m/s
        self._max_rot = 0.8    # rad/s

        # Log
        self.trajectory: list[dict] = []

    def execute(self, segments: list[WaypointSegment]) -> bool:
        """Execute route segments. Returns True on success."""
        print(f"\n{'='*50}")
        print(f"Route: {len(segments)} segment(s)")
        for i, seg in enumerate(segments):
            print(f"  [{i}] dx={seg.dx:+.1f}m  dy={seg.dy:+.1f}m")
        print(f"{'='*50}\n")

        for seg_idx, seg in enumerate(segments):
            # Compute target heading and distance for this segment
            target_distance = math.hypot(seg.dx, seg.dy)
            target_heading_rel = math.degrees(math.atan2(seg.dy, seg.dx))

            if target_distance < 0.01:
                print(f"[{seg_idx}] Skip: too short ({target_distance:.2f}m)")
                continue

            print(f"[{seg_idx}] Target: {target_distance:.2f}m "
                  f"at heading {target_heading_rel:+.0f}° (relative)")

            # Get starting pose
            start = self._odom.relative_pose
            target_heading_abs = normalize_angle(start.yaw_deg + target_heading_rel)

            # Phase 1: turn to face target heading
            print(f"  Phase 1: turning to {target_heading_abs:.0f}°...")
            if not self._turn_to_heading(target_heading_abs):
                print(f"  ❌ Turn failed")
                return False

            # Phase 2: walk forward
            start_pos = self._odom.relative_pose
            print(f"  Phase 2: walking {target_distance:.2f}m...")
            if not self._walk_distance(target_distance, start_pos):
                print(f"  ❌ Walk failed")
                return False

            print(f"  ✅ Segment complete\n")

        # Stop
        self._ctrl.stop()
        print("✅ Route complete!")
        return True

    def _turn_to_heading(self, target_deg: float) -> bool:
        """Turn in place to face target_deg (absolute, in odom frame)."""
        self._heading_pid.reset()
        t0 = time.time()
        timeout = 15.0  # max 15s to turn

        while time.time() - t0 < timeout:
            pose = self._odom.relative_pose
            heading_error = normalize_angle(target_deg - pose.yaw_deg)

            if abs(heading_error) < self._yaw_tolerance:
                self._ctrl.stop()
                print(f"    → heading reached ({pose.yaw_deg:.0f}°)")
                return True

            # PID control
            dt = 0.1
            az = self._heading_pid.compute(heading_error, dt)
            az = max(-self._max_rot, min(self._max_rot, az))

            self._ctrl.heartbeat()
            self._ctrl.rotate(az)

            # Log
            self.trajectory.append({
                'time': time.time(),
                'x': pose.x, 'y': pose.y, 'yaw': pose.yaw_deg,
                'phase': 'turn',
                'target': target_deg,
                'cmd_vx': 0, 'cmd_az': az,
            })

            time.sleep(0.1)

        self._ctrl.stop()
        print(f"    ❌ Turn timeout ({timeout}s)")
        return False

    def _walk_distance(self, distance: float, start_pose: RobotPose) -> bool:
        """Walk forward for `distance` meters."""
        self._dist_pid.reset()
        t0 = time.time()
        timeout = max(30, distance / 0.1)  # at least 30s

        while time.time() - t0 < timeout:
            pose = self._odom.relative_pose
            dx = pose.x - start_pose.x
            dy = pose.y - start_pose.y
            traveled = math.hypot(dx, dy)
            remaining = distance - traveled

            if remaining < self._dist_tolerance:
                self._ctrl.stop()
                print(f"    → distance reached ({traveled:.2f}m traveled)")
                return True

            # PID for forward speed
            dt = 0.1
            vx = self._dist_pid.compute(remaining, dt)
            vx = max(0.05, min(self._max_fwd, vx))  # min 0.05 m/s

            # Small heading correction
            pose_abs = self._odom.pose
            # (we use relative pose, so no heading correction during walk)
            # Just go straight — heading was set in previous phase

            self._ctrl.heartbeat()
            self._ctrl.forward(vx)

            # Log
            self.trajectory.append({
                'time': time.time(),
                'x': pose.x, 'y': pose.y, 'yaw': pose.yaw_deg,
                'phase': 'walk',
                'target_dist': distance,
                'traveled': traveled,
                'cmd_vx': vx, 'cmd_az': 0,
            })

            # Print progress every 1s
            if int(time.time() * 2) % 20 == 0:
                print(f"    traveled={traveled:.2f}m remaining={remaining:.2f}m vx={vx:.2f}")

            time.sleep(0.1)

        self._ctrl.stop()
        print(f"    ❌ Walk timeout ({timeout}s), traveled {traveled:.2f}m")
        return False


def plot_trajectory(traj: list[dict], route: list[WaypointSegment], filename: str):
    """Plot the actual trajectory vs planned route."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("⚠ matplotlib not available — skipping plot")
        return

    if not traj:
        print("⚠ No trajectory data to plot")
        return

    xs = [p['x'] for p in traj]
    ys = [p['y'] for p in traj]

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.plot(ys, xs, 'b-', linewidth=0.8, alpha=0.7, label='Actual (leg odom)')
    ax.scatter(ys[0], xs[0], c='green', s=100, marker='o', label='Start')
    ax.scatter(ys[-1], xs[-1], c='red', s=100, marker='x', label='End')

    # Planned route
    plan_x, plan_y = [0], [0]
    cx, cy = 0, 0
    for seg in route:
        heading = math.atan2(seg.dy, seg.dx)
        cx += seg.dx
        cy += seg.dy
        plan_x.append(cx)
        plan_y.append(cy)
    ax.plot(plan_y, plan_x, 'r--', linewidth=1.5, alpha=0.6, label='Planned')

    # Waypoint markers
    for i, (px, py) in enumerate(zip(plan_x[1:], plan_y[1:])):
        ax.scatter(py, px, c='orange', s=60, marker='s')
        ax.annotate(f'WP{i}', (py, px), textcoords="offset points", xytext=(5, 5))

    ax.set_xlabel('Y (m) — lateral')
    ax.set_ylabel('X (m) — forward')
    ax.set_title('Leg Odometry Trajectory vs Planned Route')
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.axis('equal')

    fig.tight_layout()
    fig.savefig(filename, dpi=150)
    print(f"Plot saved: {filename}")


def main():
    parser = argparse.ArgumentParser(
        description="Leg Odometry PID Closed-Loop Test"
    )
    parser.add_argument(
        '--route', type=str, required=True,
        help='Route segments: "dx1,dy1; dx2,dy2; ..." (e.g. "5,0; 0,-1")'
    )
    parser.add_argument(
        '--plot', type=str, default='tmp/navi_test_output/leg_odom_trajectory.png',
        help='Output plot file path'
    )
    parser.add_argument(
        '--log', type=str, default='tmp/navi_test_output/leg_odom_log.json',
        help='Trajectory log file path'
    )
    parser.add_argument(
        '--no-plot', action='store_true',
        help='Skip plotting'
    )
    args = parser.parse_args()

    # Parse route
    try:
        route = parse_route(args.route)
    except ValueError as e:
        print(f"❌ Invalid route: {e}")
        sys.exit(1)

    if not route:
        print("❌ Empty route")
        sys.exit(1)

    # Verify dog network
    print("Checking dog connection...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2)
        sock.sendto(b'ping', (DOG_IP, DOG_CMD_PORT))
        sock.close()
    except Exception:
        pass  # UDP ping doesn't need response

    # Start odom listener
    print("Starting cuVSLAM odometry listener...")
    odom = CuvslamOdomReader()
    odom.start()

    # Wait for first odom frame
    print("Waiting for cuVSLAM odometry data...")
    t0 = time.time()
    while odom.count < 5:
        time.sleep(0.2)
        if time.time() - t0 > 10:
            print("❌ No cuVSLAM odometry received after 10s.")
            print("   Is lite3_init running? Is the dog standing?")
            odom.stop()
            sys.exit(1)
    pose = odom.relative_pose
    print(f"  Received {odom.count} frames. Start pose: "
          f"x={pose.x:.2f} y={pose.y:.2f} yaw={pose.yaw_deg:.0f}°")

    # Initialize controller
    ctrl = DogController()

    # Ensure auto mode
    print("Setting auto mode...")
    for _ in range(5):
        ctrl.heartbeat()
        time.sleep(0.1)
    ctrl.auto_mode()

    # Execute route
    executor = RouteExecutor(ctrl, odom)
    signal.signal(signal.SIGINT, lambda s, f: (ctrl.stop(), odom.stop(), sys.exit(0)))

    success = executor.execute(route)

    # Stop
    ctrl.stop()
    odom.stop()

    # Save trajectory log
    log_path = os.path.expanduser(args.log)
    with open(log_path, 'w') as f:
        json.dump({
            'route': [(s.dx, s.dy) for s in route],
            'trajectory': executor.trajectory,
            'success': success,
        }, f, indent=2)
    print(f"Trajectory log: {log_path} ({len(executor.trajectory)} points)")

    # Plot
    if not args.no_plot and executor.trajectory:
        plot_path = os.path.expanduser(args.plot)
        plot_trajectory(executor.trajectory, route, plot_path)

    if success:
        print("\n✅ PID test passed!")
    else:
        print("\n⚠ PID test failed (timeout or error)")


if __name__ == '__main__':
    main()
