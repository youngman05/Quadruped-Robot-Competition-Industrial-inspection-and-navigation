"""
Competition test logger — records all key topics during dog testing.

Saves to ~/competition_logs/<timestamp>/
  - cmd_vel.csv       velocity commands
  - odom.csv          robot pose
  - task_phase.csv    state machine transitions
  - task_status.csv   full task JSON status
  - all_topics.bag    ros2 bag (if ros2 bag installed)

Usage:
  python3 scripts/test_logger.py              # record to timestamped dir
  python3 scripts/test_logger.py --bag        # also record ros2 bag
"""
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist


_LOG_DIR = Path.home() / "competition_logs" / datetime.now().strftime("%Y%m%d_%H%M%S")


class TestLogger(Node):

    def __init__(self, use_bag=False):
        super().__init__("test_logger")
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.get_logger().info(f"Logging to {_LOG_DIR}")

        # ── Open CSV writers ────────────────────
        self._cmd_vel_f = open(_LOG_DIR / "cmd_vel.csv", "w")
        self._cmd_writer = csv.writer(self._cmd_vel_f)
        self._cmd_writer.writerow(["stamp_s", "vx", "vz"])

        self._odom_f = open(_LOG_DIR / "odom.csv", "w")
        self._odom_writer = csv.writer(self._odom_f)
        self._odom_writer.writerow(["stamp_s", "x", "y", "yaw"])

        self._phase_f = open(_LOG_DIR / "task_phase.csv", "w")
        self._phase_writer = csv.writer(self._phase_f)
        self._phase_writer.writerow(["stamp_s", "phase"])

        self._status_f = open(_LOG_DIR / "task_status.csv", "w")
        self._status_writer = csv.writer(self._status_f)
        self._status_writer.writerow(["stamp_s", "status_json"])

        # ── Subscriptions (BEST_EFFORT to match system publishers) ──
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        be = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.create_subscription(Twist, "/cmd_vel", self._cmd_cb, 10)  # RELIABLE — match publisher
        self.create_subscription(Odometry, "/odom", self._odom_cb, be)
        self.create_subscription(String, "/task/phase", self._phase_cb, 10)
        self.create_subscription(String, "/task/status", self._status_cb, 10)

        # ── Periodic summary ────────────────────
        self._start_time = time.time()
        self._counts = {"cmd_vel": 0, "odom": 0, "phase": 0, "status": 0}
        self.create_timer(5.0, self._summary)

        self.get_logger().info("Logger ready. Press Ctrl+C to stop.")

        if use_bag:
            self.get_logger().info("ros2 bag recording: run in separate terminal:")
            self.get_logger().info(
                f"  cd {_LOG_DIR} && ros2 bag record -a -o all_topics"
            )

    def _cmd_cb(self, msg):
        self._cmd_writer.writerow([
            self.get_clock().now().nanoseconds / 1e9,
            msg.linear.x, msg.angular.z,
        ])
        self._counts["cmd_vel"] += 1

    def _odom_cb(self, msg):
        p = msg.pose.pose
        q = p.orientation
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = __import__('math').atan2(siny, cosy)
        self._odom_writer.writerow([
            self.get_clock().now().nanoseconds / 1e9,
            p.position.x, p.position.y, yaw,
        ])
        self._counts["odom"] += 1

    def _phase_cb(self, msg):
        self._phase_writer.writerow([
            self.get_clock().now().nanoseconds / 1e9, msg.data,
        ])
        self._counts["phase"] += 1
        self.get_logger().info(f"PHASE → {msg.data}")

    def _status_cb(self, msg):
        self._status_writer.writerow([
            self.get_clock().now().nanoseconds / 1e9, msg.data,
        ])
        self._counts["status"] += 1

    def _summary(self):
        elapsed = time.time() - self._start_time
        self.get_logger().info(
            f"[{elapsed:.0f}s] cmd_vel={self._counts['cmd_vel']} "
            f"odom={self._counts['odom']} "
            f"phase={self._counts['phase']} status={self._counts['status']}"
        )

    def destroy_node(self):
        self._cmd_vel_f.close()
        self._odom_f.close()
        self._phase_f.close()
        self._status_f.close()
        self.get_logger().info(f"Logs saved to {_LOG_DIR}")
        return super().destroy_node()


def main():
    rclpy.init()
    use_bag = "--bag" in sys.argv
    node = TestLogger(use_bag)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
