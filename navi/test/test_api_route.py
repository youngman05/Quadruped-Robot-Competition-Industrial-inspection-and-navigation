#!/usr/bin/env python3
"""Test MotionController API with a complex route."""
import sys, time, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from navi.motion import MotionController, OdomFreezeError

ROUTE = [
    ("FWD",  3),     # 前进 3m
    ("TURN", -90),   # 右转 90°
    ("FWD",  2),     # 前进 2m
    ("TURN", 180),   # 掉头
    ("FWD",  2),     # 前进 2m
    ("TURN", 90),    # 左转 90°
    ("FWD",  2),     # 前进 2m
    ("TURN", 180),   # 掉头
]

mc = MotionController()
mc.initialize()

x, y, yaw = mc.pose
expected_yaw = 0.0
print(f"Start: ({x:.2f}, {y:.2f}, heading={yaw:.0f} deg)")

success = True
for i, (action, value) in enumerate(ROUTE):
    print(f"\n[{i}] {action} {value:+}")

    if action == "TURN":
        expected_yaw += value
        ok = mc.turn_to(expected_yaw)
    else:
        ok = mc.move_forward(value)

    x, y, yaw = mc.pose
    status = "OK" if ok else "FAIL"
    print(f"  {status} -> pose: ({x:.2f}, {y:.2f}), heading={yaw:.0f} deg (expect {expected_yaw:.0f})")

    if not ok:
        success = False
        break

    mc.stop()
    time.sleep(1)

mc.shutdown()

x, y, _ = mc.pose
print(f"\n{'PASS' if success else 'FAIL'} — final: ({x:.2f}, {y:.2f})")
