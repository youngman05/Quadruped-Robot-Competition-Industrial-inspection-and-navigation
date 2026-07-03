#!/usr/bin/env python3
"""
Real-time SLAM status monitor — displays odometry, velocity, task phase.
Usage: python3 scripts/slam_monitor.py
"""
import json, math, time, sys
from pathlib import Path

import cv2
import numpy as np
import rclpy
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist
from std_msgs.msg import String
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy


class SlamMonitor:
    def __init__(self):
        rclpy.init()
        qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT,
                         history=HistoryPolicy.KEEP_LAST, depth=1)
        self._node = rclpy.create_node("slam_monitor")
        self._node.create_subscription(Odometry, "/odom", self._odom_cb, qos)
        self._node.create_subscription(Twist, "/cmd_vel", self._cmd_cb, 10)
        self._node.create_subscription(String, "/task/phase", self._phase_cb, 10)

        self._odom = {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "count": 0,
                      "vx": 0.0, "vz": 0.0, "rate": 0.0, "last_t": time.time()}
        self._cmd = {"vx": 0.0, "vz": 0.0}
        self._phase = "idle"
        self._start_t = time.time()

    def _odom_cb(self, msg):
        p = msg.pose.pose
        q = p.orientation
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        now = time.time()
        dt = now - self._odom["last_t"]
        if self._odom["count"] > 0 and dt > 0:
            self._odom["rate"] = 1.0 / dt
        self._odom["last_t"] = now
        self._odom["x"] = p.position.x
        self._odom["y"] = p.position.y
        self._odom["z"] = p.position.z
        self._odom["yaw"] = math.atan2(siny, cosy)
        self._odom["vx"] = msg.twist.twist.linear.x
        self._odom["vz"] = msg.twist.twist.angular.z
        self._odom["count"] += 1

    def _cmd_cb(self, msg):
        self._cmd["vx"] = msg.linear.x
        self._cmd["vz"] = msg.angular.z

    def _phase_cb(self, msg):
        self._phase = msg.data

    def spin(self):
        cv2.namedWindow("SLAM Monitor", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("SLAM Monitor", 420, 320)

        while rclpy.ok():
            rclpy.spin_once(self._node, timeout_sec=0.05)

            img = np.zeros((320, 420, 3), dtype=np.uint8)
            img[:] = (20, 20, 30)

            # Title
            cv2.putText(img, "SLAM Monitor", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

            # Odom
            o = self._odom
            elapsed = time.time() - self._start_t
            lines = [
                f"Time: {elapsed:.0f}s  Phase: {self._phase}",
                f"",
                f"--- Odom ({o['count']} msgs, {o['rate']:.0f} Hz) ---",
                f"X: {o['x']:7.3f}m   Y: {o['y']:7.3f}m",
                f"Z: {o['z']:7.3f}m   Yaw: {math.degrees(o['yaw']):6.1f}deg",
                f"",
                f"--- /cmd_vel ---",
                f"Linear: {self._cmd['vx']:6.3f} m/s  Angular: {self._cmd['vz']:6.3f} rad/s",
            ]
            y = 55
            for line in lines:
                color = (200, 200, 200)
                if 'Odom' in line: color = (0, 255, 0)
                if 'cmd_vel' in line: color = (255, 200, 0)
                if 'Phase' in line: color = (255, 255, 100)
                cv2.putText(img, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
                y += 22

            # Odom status indicator
            status = "GOOD" if o["rate"] > 15 else ("SLOW" if o["rate"] > 5 else "LOST")
            color = (0, 255, 0) if status == "GOOD" else ((0, 200, 255) if status == "SLOW" else (0, 0, 255))
            cv2.putText(img, f"SLAM: {status}", (300, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

            cv2.imshow("SLAM Monitor", img)
            if cv2.waitKey(100) & 0xFF == ord('q'):
                break

        cv2.destroyAllWindows()
        self._node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    SlamMonitor().spin()
