#!/usr/bin/env python3
# coding: utf-8

"""Convert YOLO node JSON output to a target 3D point in camera frame."""

from __future__ import print_function

import argparse
import json
import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from arm_api import CameraIntrinsics, YoloTargetError, yolo_payload_to_camera_point  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(
        description="YOLO detections JSON -> target point in camera optical frame"
    )
    parser.add_argument(
        "json_file",
        nargs="?",
        help="YOLO JSON file; omit or use '-' to read stdin",
    )
    parser.add_argument(
        "--class-name",
        dest="class_names",
        action="append",
        default=None,
        help="target class name; can repeat. Default: red",
    )
    parser.add_argument(
        "--class-id",
        dest="class_ids",
        action="append",
        type=int,
        default=None,
        help="target class id; can repeat",
    )
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--fx", type=float, default=617.0)
    parser.add_argument("--fy", type=float, default=617.0)
    parser.add_argument("--cx", type=float, default=320.0)
    parser.add_argument("--cy", type=float, default=240.0)
    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON only",
    )
    return parser.parse_args()


def read_payload(path):
    if not path or path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def main():
    args = parse_args()
    intrinsics = CameraIntrinsics(args.fx, args.fy, args.cx, args.cy)
    class_names = args.class_names if args.class_names is not None else ("red",)

    try:
        target = yolo_payload_to_camera_point(
            read_payload(args.json_file),
            intrinsics=intrinsics,
            target_classes=class_names,
            target_class_ids=args.class_ids,
            min_confidence=args.min_confidence,
        )
    except YoloTargetError as exc:
        print("定位失败: {}".format(exc), file=sys.stderr)
        raise SystemExit(2)

    if args.json:
        print(json.dumps(target.to_dict(), ensure_ascii=False, sort_keys=True))
        return

    x, y, z = target.point
    u, v = target.pixel
    print("目标: class_name={} class_id={} confidence={}".format(
        target.class_name,
        target.class_id,
        target.confidence,
    ))
    print("像素: u={:.1f}, v={:.1f}".format(u, v))
    print("深度: z={:.6f} m".format(z))
    print("相机坐标: x={:.6f}, y={:.6f}, z={:.6f} m".format(x, y, z))
    if target.frame_id:
        print("frame_id: {}".format(target.frame_id))


if __name__ == "__main__":
    main()
