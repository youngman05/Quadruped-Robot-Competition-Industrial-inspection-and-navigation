#!/usr/bin/env python3
"""
PID Closed-Loop Test — Absolute Waypoints (cuVSLAM odometry)

Unlike the relative-route test, this uses ABSOLUTE coordinate waypoints.
The dog stops at each waypoint for 2s before continuing.

Usage:
  python3 navi/test/test_pid_abs.py --waypoints "0,0; 3,0; 3,-2; 1,-2; 1,2; -2,2"

The first waypoint MUST be the start position (usually 0,0).
"""

from __future__ import annotations
import socket, struct, time, math, sys, argparse, json, os, threading, signal

DOG_IP = "192.168.1.120"
DOG_CMD_PORT = 43893
CMD_HEARTBEAT = 0x21040001
CMD_AUTO_MODE = 0x21010C03
CMD_MOTION    = 0x21010D06
CODE_FWD = 320
CODE_YAW = 321

PAUSE_BETWEEN = 2.0   # seconds to pause at each waypoint
COAST_DIST   = 0.15   # start decelerating this far from target


class RobotPose:
    def __init__(self, x=0.0, y=0.0, yaw_deg=0.0):
        self.x = x; self.y = y; self.yaw_deg = yaw_deg


class OdomReader:
    ODOM_FILE = "/tmp/odom_latest.json"

    def __init__(self):
        self._pose = RobotPose()
        self._lock = threading.Lock()
        self._running = False
        self._init = None
        self._yaw_offset = 0.0      # calibrates cuVSLAM yaw → user frame
        self._calibrated = False
        self._last_update = time.time()  # watchdog: detect odom freeze

    @property
    def pose(self) -> RobotPose:
        with self._lock:
            return RobotPose(self._pose.x, self._pose.y,
                             self._pose.yaw_deg + self._yaw_offset)

    @property
    def relative(self) -> RobotPose:
        p = self.pose
        if self._init is None:
            return RobotPose(0, 0, 0)
        return RobotPose(p.x - self._init.x, p.y - self._init.y,
                         p.yaw_deg - self._init.yaw_deg)

    def stale_sec(self) -> float:
        """Seconds since last odom update."""
        with self._lock:
            return time.time() - self._last_update

    def calibrate_yaw(self, desired_deg: float):
        """Set yaw offset so current raw yaw maps to desired_deg."""
        with self._lock:
            raw = self._pose.yaw_deg
        self._yaw_offset = desired_deg - raw
        self._calibrated = True
        print(f"Yaw calibrated: raw={raw:.0f}° desired={desired_deg:.0f}° "
              f"offset={self._yaw_offset:.0f}°")

    def start(self):
        self._running = True
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self):
        self._running = False

    def _run(self):
        while self._running:
            try:
                with open(self.ODOM_FILE) as f:
                    d = json.load(f)
                x = float(d['x']); y = float(d['y'])
                qx=float(d['qx']); qy=float(d['qy'])
                qz=float(d['qz']); qw=float(d['qw'])
                siny = 2*(qw*qz + qx*qy)
                cosy = 1 - 2*(qy*qy + qz*qz)
                yaw = math.degrees(math.atan2(siny, cosy))
                with self._lock:
                    self._pose = RobotPose(x, y, yaw)
                    self._last_update = time.time()
                    if self._init is None:
                        self._init = RobotPose(x, y, yaw)
            except Exception:
                pass
            time.sleep(0.05)


class Dog:
    def __init__(self):
        self._s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._a = (DOG_IP, DOG_CMD_PORT)

    def hb(self):
        self._s.sendto(struct.pack('<3i', CMD_HEARTBEAT, 0, 0), self._a)

    def fwd(self, v):
        self._s.sendto(struct.pack('<3id', CODE_FWD, 8, 1, float(v)), self._a)

    def rot(self, v):
        self._s.sendto(struct.pack('<3id', CODE_YAW, 8, 1, float(-v)), self._a)

    def stop(self):
        self.fwd(0.0)

    def auto(self):
        self._s.sendto(struct.pack('<3i', CMD_AUTO_MODE, 0, 0), self._a)
        time.sleep(0.5)
        self._s.sendto(struct.pack('<3i', CMD_MOTION, 0, 0), self._a)
        time.sleep(0.3)


def norm_deg(d):
    while d < -180: d += 360
    while d >= 180: d -= 360
    return d


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--waypoints', required=True,
                   help='Absolute waypoints: "x1,y1; x2,y2; ..." (first=start)')
    p.add_argument('--plot', default='navi/test/output/traj_abs.png')
    p.add_argument('--log', default='navi/test/output/traj_abs.json')
    args = p.parse_args()

    # Parse absolute waypoints
    wps = []
    for s in args.waypoints.split(';'):
        s = s.strip()
        if not s: continue
        parts = s.split(',')
        wps.append((float(parts[0]), float(parts[1])))

    if len(wps) < 2:
        print("Need at least 2 waypoints (start + goal)")
        return

    print(f"Route: {len(wps)-1} segment(s), {len(wps)} waypoints")
    for i, (x, y) in enumerate(wps):
        print(f"  WP{i}: ({x:+.1f}, {y:+.1f})")

    # Connect
    print("\nStarting cuVSLAM odom reader...")
    odom = OdomReader()
    odom.start()
    time.sleep(2)

    # Wait for odom
    for _ in range(30):
        p = odom.relative
        if p.x != 0 or p.y != 0:
            break
        time.sleep(0.2)
    print(f"Odom ready. Raw: ({p.x:.2f}, {p.y:.2f}, yaw={p.yaw_deg:.0f} deg)")

    # Yaw calibration: map cuVSLAM orientation to first segment's direction
    first_heading = math.degrees(math.atan2(wps[1][1] - wps[0][1],
                                            wps[1][0] - wps[0][0]))
    odom.calibrate_yaw(first_heading)
    p = odom.relative
    print(f"Calibrated: ({p.x:.2f}, {p.y:.2f}, yaw={p.yaw_deg:.0f} deg)")

    dog = Dog()
    for _ in range(5): dog.hb(); time.sleep(0.1)
    dog.auto()

    signal.signal(signal.SIGINT, lambda *_: (dog.stop(), odom.stop(), sys.exit(0)))

    trajectory = []
    success = True

    for seg in range(len(wps) - 1):
        target_x, target_y = wps[seg + 1]

        # The target is ABSOLUTE in odom's relative frame.
        # We need to OFFSET by the initial odom reading.
        # Actually, the waypoints are in the USER's coordinate frame.
        # The odom gives relative coordinates starting at (0,0).
        # So we can use the waypoints directly as target relative coordinates.

        print(f"\n---> WP{seg+1}: ({target_x:+.1f}, {target_y:+.1f})")

        t0 = time.time()
        timeout = 60  # max 60s per segment
        reached = False

        while time.time() - t0 < timeout:
            pose = odom.relative
            stale = odom.stale_sec()

            # ── Odom watchdog ──────────────────────
            if stale > 0.3:   # odom frozen > 300ms
                dog.stop()
                print(f"  !! Odom frozen ({stale:.1f}s) — stopping, waiting...")
                t_freeze = time.time()
                recovered = False
                while time.time() - t_freeze < 5.0:
                    time.sleep(0.2)
                    if odom.stale_sec() < 0.2:
                        print(f"  -> Odom recovered after {time.time()-t_freeze:.1f}s")
                        recovered = True
                        break
                if not recovered:
                    print("  !! Odom not recovered in 5s — lying down")
                    dog.hb()
                    dog._s.sendto(struct.pack('<3i', 0x21010C0E, 0, 0), dog._a)
                    dog.stop()
                    odom.stop()
                    # Save partial log
                    os.makedirs(os.path.dirname(args.log), exist_ok=True)
                    with open(args.log, 'w') as f:
                        json.dump({'waypoints': wps, 'trajectory': trajectory,
                                    'success': False, 'odom_lost': True}, f, indent=2)
                    print(f"Partial log saved: {args.log}")
                    return
                # Recovered — reset segment timer
                t0 = time.time()
                continue

            dist = math.hypot(target_x - pose.x, target_y - pose.y)

            traj_pt = {
                't': time.time(), 'x': pose.x, 'y': pose.y,
                'yaw': pose.yaw_deg, 'target_x': target_x,
                'target_y': target_y, 'dist': dist, 'seg': seg,
            }

            if dist < 0.08:  # 8cm tolerance
                dog.stop()
                reached = True
                traj_pt['cmd'] = 'STOP'
                trajectory.append(traj_pt)
                print(f"  -> reached! dist={dist:.3f}m")
                break

            # Compute desired heading toward target
            des_yaw = math.degrees(math.atan2(target_y - pose.y, target_x - pose.x))
            heading_err = norm_deg(des_yaw - pose.yaw_deg)

            if abs(heading_err) > 10:
                # Turn first
                az = max(-0.6, min(0.6, 0.02 * heading_err))
                dog.hb(); dog.rot(az)
                traj_pt['cmd'] = 'rot'
                traj_pt['az'] = az
            else:
                # Walk forward, slow down near target
                vx = 0.35
                if dist < COAST_DIST:
                    vx = max(0.08, 0.35 * dist / COAST_DIST)
                dog.hb(); dog.fwd(vx)
                traj_pt['cmd'] = 'fwd'
                traj_pt['vx'] = vx

            trajectory.append(traj_pt)
            time.sleep(0.1)

            # Progress print
            if len(trajectory) % 20 == 0:
                print(f"  dist={dist:.2f}m hdg_err={heading_err:+.0f}° "
                      f"pose=({pose.x:.2f},{pose.y:.2f})")

        if not reached:
            print(f"  TIMEOUT ({timeout}s)")
            success = False
            break

        # Pause at waypoint
        dog.stop()
        print(f"  Pausing {PAUSE_BETWEEN}s...")
        for _ in range(int(PAUSE_BETWEEN * 10)):
            dog.hb()
            time.sleep(0.1)
            pose = odom.relative
            trajectory.append({
                't': time.time(), 'x': pose.x, 'y': pose.y,
                'yaw': pose.yaw_deg, 'cmd': 'pause', 'seg': seg,
            })

    dog.stop()
    odom.stop()

    # Save log
    os.makedirs(os.path.dirname(args.log), exist_ok=True)
    with open(args.log, 'w') as f:
        json.dump({'waypoints': wps, 'trajectory': trajectory,
                    'success': success}, f, indent=2)
    print(f"\nLog: {args.log} ({len(trajectory)} points)")

    # Plot
    try:
        import matplotlib.pyplot as plt
        xs = [p['x'] for p in trajectory]
        ys = [p['y'] for p in trajectory]
        wpx = [w[0] for w in wps]
        wpy = [w[1] for w in wps]

        fig, ax = plt.subplots(figsize=(9, 9))
        ax.plot(ys, xs, 'b-', lw=0.6, alpha=0.7, label='Actual')
        ax.plot(wpy, wpx, 'r--', lw=1.5, alpha=0.5, label='Planned')
        ax.scatter(wpy[0], wpx[0], c='green', s=120, marker='o', label='Start')
        for i, (px, py) in enumerate(zip(wpx[1:], wpy[1:])):
            ax.scatter(py, px, c='red', s=60, marker='s')
            ax.annotate(f'WP{i+1}', (py, px), textcoords='offset points', xytext=(5,5))
        ax.set_xlabel('Y (m)'); ax.set_ylabel('X (m)')
        ax.set_title('cuVSLAM Absolute Waypoint PID Test')
        ax.legend(); ax.grid(alpha=0.3); ax.axis('equal')
        fig.tight_layout()
        fig.savefig(args.plot, dpi=150)
        print(f"Plot: {args.plot}")
    except Exception as e:
        print(f"Plot error: {e}")

    print(f"\n{'PASS' if success else 'FAIL'} — {len(wps)-1} segments")
    if success:
        final = odom.relative
        print(f"Final pose: ({final.x:.2f}, {final.y:.2f})")


if __name__ == '__main__':
    main()
