#!/usr/bin/env python3
"""Teach the shared Tag-relative I2 pose from /apriltag/detections_base."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

import rclpy
import yaml
from rclpy.node import Node
from std_msgs.msg import String


def yaw_from_quaternion(values):
    x, y, z, w = (float(value) for value in values)
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


class I2Collector(Node):
    def __init__(self, tag_id: int, sample_count: int, topic: str) -> None:
        super().__init__("teach_pick_i2_apriltag")
        self.tag_id = tag_id
        self.sample_count = sample_count
        self.samples = []
        self.create_subscription(String, topic, self._on_frame, 10)

    def _on_frame(self, message: String) -> None:
        try:
            frame = json.loads(message.data)
            if frame.get("frame_id") != "base_link":
                return
            detection = next(
                item for item in frame["detections"] if int(item["tag_id"]) == self.tag_id
            )
            x, y, _z = (float(value) for value in detection["position_m"])
            yaw = yaw_from_quaternion(detection["orientation_xyzw"])
        except (json.JSONDecodeError, KeyError, StopIteration, TypeError, ValueError):
            return
        self.samples.append((x, y, yaw))
        self.get_logger().info("tag {} sample {}/{}".format(
            self.tag_id, len(self.samples), self.sample_count
        ))

    @property
    def complete(self) -> bool:
        return len(self.samples) >= self.sample_count

    def robust_target(self):
        samples = self.samples[:self.sample_count]
        x = statistics.median(item[0] for item in samples)
        y = statistics.median(item[1] for item in samples)
        # IPPE may produce an occasional reflected yaw. Select the largest
        # 15-degree yaw cluster so the first received frame cannot bias I2.
        inliers = max(
            (
                [
                    item for item in samples
                    if abs(math.atan2(math.sin(item[2] - seed[2]), math.cos(item[2] - seed[2])))
                    <= math.radians(15.0)
                ]
                for seed in samples
            ),
            key=len,
        )
        yaw = math.atan2(
            sum(math.sin(item[2]) for item in inliers),
            sum(math.cos(item[2]) for item in inliers),
        )
        return x, y, yaw, len(samples)


def update_config(path: Path, tag_ids, target) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    params = data["competition_manager_node"]["ros__parameters"]
    values = [round(value, 9) for value in target]
    for tag_id in tag_ids:
        params["pick_i2_tag_{}_taught".format(tag_id)] = True
        params["pick_i2_tag_{}_xyyaw".format(tag_id)] = list(values)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tag_id", type=int, choices=range(4),
        help="Visible Tag used to teach the common relative I2 pose.",
    )
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument(
        "--copy-to-all-tags", action="store_true",
        help="Write this shared Tag-relative I2 pose to IDs 0, 1, 2, and 3.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the robust I2 estimate without modifying the YAML file.",
    )
    parser.add_argument("--topic", default="/apriltag/detections_base")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/calibration/pick_i2_apriltag.yaml"),
    )
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")

    rclpy.init()
    node = I2Collector(args.tag_id, args.samples, args.topic)
    try:
        while rclpy.ok() and not node.complete:
            rclpy.spin_once(node, timeout_sec=1.0)
        if not node.complete:
            raise RuntimeError("collection stopped before enough samples arrived")
        x, y, yaw, inlier_count = node.robust_target()
        target = (x, y, yaw)
        target_ids = range(4) if args.copy_to_all_tags else (args.tag_id,)
        print(
            "tag {} I2 x={:.6f} y={:.6f} yaw={:.6f} rad ({} yaw inliers)".format(
                args.tag_id, *target, inlier_count
            )
        )
        if args.dry_run:
            print("dry run; configuration unchanged")
        else:
            update_config(args.config, target_ids, target)
            print("wrote IDs {}".format(list(target_ids)))
            print("updated {}".format(args.config))
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
