#!/usr/bin/env python3
"""
Combined route test: FWD (forward) + TURN (rotate in place)
Uses cuVSLAM odometry with yaw calibration + freeze watchdog.

Usage:
  python3 navi/test/test_route.py --route "FWD:3; TURN:-90; FWD:2; TURN:180; FWD:2"
"""
from __future__ import annotations
import socket, struct, time, math, sys, json, os, threading, argparse, signal

DOG_IP = "192.168.1.120"; DOG_PORT = 43893
CMD_HB = 0x21040001; CMD_AUTO = 0x21010C03; CMD_MOTION = 0x21010D06
CODE_FWD = 320; CODE_YAW = 321
ODOM_FILE = "/tmp/odom_latest.json"

# ── Odom ──────────────────────────────────────────
class Odom:
    def __init__(self):
        self._lk = threading.Lock()
        self._x = 0.0; self._y = 0.0; self._yaw_raw = 0.0
        self._init = None; self._yaw_off = 0.0; self._ts = time.time()
        self._run = False

    def start(self):
        self._run = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self): self._run = False

    @property
    def pose(self):
        with self._lk:
            x = self._x - (self._init[0] if self._init else 0)
            y = self._y - (self._init[1] if self._init else 0)
            yaw = self._yaw_raw + self._yaw_off
            if self._init:
                yaw -= self._init[2]
            while yaw < -180: yaw += 360
            while yaw >= 180: yaw -= 360
            return x, y, yaw

    @property
    def stale(self):
        with self._lk: return time.time() - self._ts

    def calibrate(self, desired_deg):
        with self._lk:
            self._yaw_off = desired_deg - self._yaw_raw
        print(f"Yaw calib: raw={self._yaw_raw:.0f} -> desired={desired_deg:.0f} "
              f"(offset={self._yaw_off:.0f} deg)")

    def _loop(self):
        while self._run:
            try:
                with open(ODOM_FILE) as f: d = json.load(f)
                qx=float(d['qx']); qy=float(d['qy'])
                qz=float(d['qz']); qw=float(d['qw'])
                sy=2*(qw*qz+qx*qy); cy=1-2*(qy*qy+qz*qz)
                yaw = math.degrees(math.atan2(sy, cy))
                with self._lk:
                    self._x=float(d['x']); self._y=float(d['y'])
                    self._yaw_raw=yaw; self._ts=time.time()
                    if self._init is None:
                        self._init = (self._x, self._y, yaw)
            except: pass
            time.sleep(0.04)

# ── Dog ───────────────────────────────────────────
class Dog:
    def __init__(self):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.a = (DOG_IP, DOG_PORT)
    def hb(self): self.s.sendto(struct.pack('<3i', CMD_HB, 0, 0), self.a)
    def fwd(self, v): self.s.sendto(struct.pack('<3id', CODE_FWD, 8, 1, float(v)), self.a)
    def rot(self, v): self.s.sendto(struct.pack('<3id', CODE_YAW, 8, 1, float(-v)), self.a)
    def stop(self): self.fwd(0.0)
    def lie_down(self):
        self.s.sendto(struct.pack('<3i', 0x21010C0E, 0, 0), self.a)
    def auto(self):
        self.s.sendto(struct.pack('<3i', CMD_AUTO, 0, 0), self.a); time.sleep(0.5)
        self.s.sendto(struct.pack('<3i', CMD_MOTION, 0, 0), self.a); time.sleep(0.3)

# ── Actions ───────────────────────────────────────
def do_turn(dog, odom, target_deg, timeout=20):
    """Turn in place to absolute target yaw. Returns (ok, final_yaw)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        _, _, yaw = odom.pose
        err = target_deg - yaw
        while err < -180: err += 360
        while err >= 180: err -= 360

        if abs(err) < 5:
            dog.stop()
            return True, yaw

        az = max(-0.8, min(0.8, 0.03 * err))
        if abs(az) < 0.08: az = 0.08 * (1 if az > 0 else -1)
        dog.hb(); dog.rot(az)
        time.sleep(0.1)

    dog.stop()
    return False, yaw

def do_fwd(dog, odom, distance, timeout=60):
    """Walk forward `distance` meters from current position. Returns (ok, traveled)."""
    x0, y0, _ = odom.pose
    t0 = time.time()

    while time.time() - t0 < timeout:
        x, y, yaw = odom.pose
        traveled = math.hypot(x - x0, y - y0)
        remaining = distance - traveled

        if remaining < 0.06:  # 6cm tolerance
            dog.stop()
            return True, traveled

        # Slow down near target
        vx = 0.35
        if remaining < 0.3:
            vx = max(0.08, 0.35 * remaining / 0.3)
        dog.hb(); dog.fwd(vx)
        time.sleep(0.1)

    dog.stop()
    return False, traveled

def watchdog_check(dog, odom):
    """Check odom freshness. If frozen > 5s, lie down. Returns True if ok."""
    s = odom.stale
    if s > 0.4:
        dog.stop()
        print(f"  !! Odom frozen ({s:.1f}s), waiting...")
        t0 = time.time()
        while time.time() - t0 < 5.0:
            time.sleep(0.2)
            if odom.stale < 0.2:
                print(f"  -> Recovered after {time.time()-t0:.1f}s")
                return True
        print("  !! Not recovered in 5s — lying down")
        dog.lie_down()
        return False
    return True

# ── Route parser ──────────────────────────────────
def parse_route(s):
    """Parse 'FWD:3; TURN:-90; FWD:2; TURN:180' into [(action, value), ...]"""
    steps = []
    for part in s.split(';'):
        part = part.strip()
        if not part: continue
        action, val = part.split(':')
        steps.append((action.strip().upper(), float(val)))
    return steps

# ── Main ──────────────────────────────────────────
def main():
    p = argparse.ArgumentParser()
    p.add_argument('--route', required=True,
                   help='Steps: "FWD:3; TURN:-90; FWD:2; TURN:180"')
    p.add_argument('--plot', default='navi/test/output/route_traj.png')
    p.add_argument('--log', default='navi/test/output/route_traj.json')
    args = p.parse_args()

    steps = parse_route(args.route)
    print(f"Route: {len(steps)} steps")
    for i, (a, v) in enumerate(steps):
        print(f"  [{i}] {a}: {v:+}")

    # Init
    odom = Odom(); odom.start(); time.sleep(2)
    dog = Dog()
    for _ in range(5): dog.hb(); time.sleep(0.1)
    dog.auto()

    # Yaw calibration: first FWD sets "forward" direction
    for a, v in steps:
        if a == 'FWD':
            odom.calibrate(0)  # forward = yaw 0
            break

    signal.signal(signal.SIGINT, lambda *_: (dog.stop(), odom.stop(), sys.exit(0)))
    traj = []; success = True

    for idx, (action, value) in enumerate(steps):
        print(f"\n[{idx}] {action} {value:+}")

        if not watchdog_check(dog, odom):
            success = False; break

        if action == 'TURN':
            _, _, yaw = odom.pose
            target = yaw + value
            ok, final = do_turn(dog, odom, target)
            print(f"  {'OK' if ok else 'TIMEOUT'} -> yaw={final:.0f} deg")
            if not ok: success = False; break

        elif action == 'FWD':
            ok, dist = do_fwd(dog, odom, value)
            print(f"  {'OK' if ok else 'TIMEOUT'} -> traveled={dist:.2f}m")
            if not ok: success = False; break

        else:
            print(f"  Unknown action: {action}")
            success = False; break

        # Pause 1s
        dog.stop()
        for _ in range(10):
            x, y, yaw = odom.pose
            traj.append({'x': x, 'y': y, 'yaw': yaw, 'step': idx,
                         'action': action, 'target': value})
            time.sleep(0.1)

        # Log trajectory during action
        x, y, yaw = odom.pose
        traj.append({'x': x, 'y': y, 'yaw': yaw, 'step': idx,
                     'action': action, 'target': value})

    dog.stop(); odom.stop()
    x, y, _ = odom.pose
    print(f"\n{'PASS' if success else 'FAIL'} — final pose: ({x:.2f}, {y:.2f})")

    # Save
    os.makedirs(os.path.dirname(args.log), exist_ok=True)
    with open(args.log, 'w') as f:
        json.dump({'steps': [(a, v) for a, v in steps],
                   'trajectory': traj, 'success': success}, f, indent=2)

    # Plot
    if traj:
        try:
            import matplotlib.pyplot as plt
            xs=[p['x'] for p in traj]; ys=[p['y'] for p in traj]
            fig, ax = plt.subplots(figsize=(8, 8))
            ax.plot(ys, xs, 'b-', lw=0.6, alpha=0.7, label='Actual')
            ax.scatter(ys[0], xs[0], c='green', s=100, label='Start')
            ax.scatter(ys[-1], xs[-1], c='red', s=100, marker='x', label='End')
            ax.set_xlabel('Y (m)'); ax.set_ylabel('X (m)')
            ax.set_title('Combined Route Test')
            ax.legend(); ax.grid(alpha=0.3); ax.axis('equal')
            fig.tight_layout(); fig.savefig(args.plot, dpi=150)
            print(f"Plot: {args.plot}")
        except Exception as e:
            print(f"Plot error: {e}")

if __name__ == '__main__':
    main()
