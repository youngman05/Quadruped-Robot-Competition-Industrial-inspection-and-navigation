#!/usr/bin/env python3
"""Pure rotation accuracy test using cuVSLAM yaw."""
from __future__ import annotations
import socket, struct, time, math, sys, json, os, threading

DOG_IP = "192.168.1.120"; DOG_PORT = 43893
CMD_HB = 0x21040001; CMD_AUTO = 0x21010C03; CMD_MOTION = 0x21010D06
CODE_FWD = 320; CODE_YAW = 321
ODOM_FILE = "/tmp/odom_latest.json"

class Odom:
    def __init__(self):
        self._lock = threading.Lock()
        self._raw = [0.0, 0.0, 0.0]  # x, y, yaw_deg
        self._init_yaw = None
        self._running = False

    @property
    def yaw_deg(self):
        with self._lock:
            yaw = self._raw[2]
            if self._init_yaw is not None:
                yaw -= self._init_yaw
            while yaw < -180: yaw += 360
            while yaw >= 180: yaw -= 360
            return yaw

    def start(self):
        self._running = True
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self): self._running = False

    def _run(self):
        while self._running:
            try:
                with open(ODOM_FILE) as f:
                    d = json.load(f)
                qx, qy, qz, qw = float(d['qx']), float(d['qy']), float(d['qz']), float(d['qw'])
                siny = 2*(qw*qz + qx*qy)
                cosy = 1 - 2*(qy*qy + qz*qz)
                yaw = math.degrees(math.atan2(siny, cosy))
                with self._lock:
                    self._raw = [float(d['x']), float(d['y']), yaw]
                    if self._init_yaw is None:
                        self._init_yaw = yaw
            except: pass
            time.sleep(0.05)

class Dog:
    def __init__(self):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.a = (DOG_IP, DOG_PORT)
    def hb(self): self.s.sendto(struct.pack('<3i', CMD_HB, 0, 0), self.a)
    def fwd(self, v): self.s.sendto(struct.pack('<3id', CODE_FWD, 8, 1, float(v)), self.a)
    def rot(self, v): self.s.sendto(struct.pack('<3id', CODE_YAW, 8, 1, float(-v)), self.a)
    def stop(self): self.fwd(0.0)
    def auto(self):
        self.s.sendto(struct.pack('<3i', CMD_AUTO, 0, 0), self.a); time.sleep(0.5)
        self.s.sendto(struct.pack('<3i', CMD_MOTION, 0, 0), self.a); time.sleep(0.3)

def turn_to(dog, odom, target_deg, timeout=15):
    """Turn in place to target relative yaw."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        err = target_deg - odom.yaw_deg
        while err < -180: err += 360
        while err >= 180: err -= 360

        if abs(err) < 5:  # within 5 degrees
            dog.stop()
            return True, odom.yaw_deg

        az = max(-0.6, min(0.6, 0.03 * err))
        dog.hb(); dog.rot(az)
        time.sleep(0.1)

    dog.stop()
    return False, odom.yaw_deg

def main():
    print("Turn test: FWD 1m → LEFT90 → RIGHT90 → RIGHT90")
    odom = Odom(); odom.start(); time.sleep(2)
    print(f"Initial yaw (relative): {odom.yaw_deg:.1f}°")

    dog = Dog()
    for _ in range(5): dog.hb(); time.sleep(0.1)
    dog.auto()

    results = []
    t0 = time.time()

    # Step 1: Forward 1m
    print("\n[1] Forward 1m...")
    while time.time() - t0 < 15:
        # Simple open-loop: walk forward at low speed for ~3s
        elapsed = time.time() - t0
        if elapsed < 3.5:
            dog.hb(); dog.fwd(0.3)
        else:
            dog.stop()
            break
        time.sleep(0.1)
    results.append(("FWD 1m", odom.yaw_deg))
    print(f"  yaw after: {odom.yaw_deg:.1f}°")

    # Step 2: Left 90°
    print("\n[2] Left turn 90°...")
    target = odom.yaw_deg + 90
    ok, final = turn_to(dog, odom, target)
    results.append(("LEFT 90", final))
    print(f"  {'OK' if ok else 'TIMEOUT'} — yaw: {final:.1f}°")
    time.sleep(1)  # pause 1s

    # Step 3: Right 90°
    print("\n[3] Right turn 90°...")
    target = odom.yaw_deg - 90
    ok, final = turn_to(dog, odom, target)
    results.append(("RIGHT 90", final))
    print(f"  {'OK' if ok else 'TIMEOUT'} — yaw: {final:.1f}°")
    time.sleep(1)

    # Step 4: Right 90° again
    print("\n[4] Right turn 90°...")
    target = odom.yaw_deg - 90
    ok, final = turn_to(dog, odom, target)
    results.append(("RIGHT 90", final))
    print(f"  {'OK' if ok else 'TIMEOUT'} — yaw: {final:.1f}°")

    dog.stop()
    odom.stop()

    print("\n=== Summary ===")
    for name, yaw in results:
        print(f"  {name:12s} → yaw={yaw:.1f}°")
    print(f"  Final yaw: {odom.yaw_deg:.1f}°")
    print(f"  Net rotation: +90 -90 -90 = -90°, cuVSLAM says: {odom.yaw_deg:.1f}°")

if __name__ == '__main__':
    main()
