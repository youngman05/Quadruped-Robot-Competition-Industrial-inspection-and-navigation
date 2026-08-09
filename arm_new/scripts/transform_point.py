#!/usr/bin/env python3
# coding: utf-8

"""坐标转换命令行测试脚本。"""

from __future__ import print_function

import argparse
import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from arm_api import FrameTransformer, TransformError  # noqa: E402


DEFAULT_CONFIG = os.path.join(ROOT, "config", "frame_transforms.yaml")


def parse_args():
    parser = argparse.ArgumentParser(description="把一个 3D 点从一个坐标系转到另一个坐标系")
    parser.add_argument("x", type=float, help="点 x，单位 m")
    parser.add_argument("y", type=float, help="点 y，单位 m")
    parser.add_argument("z", type=float, help="点 z，单位 m")
    parser.add_argument("--from-frame", default="camera", help="源坐标系：camera/arm/dog")
    parser.add_argument("--to-frame", default="arm", help="目标坐标系：camera/arm/dog")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="外参配置 YAML")
    return parser.parse_args()


def main():
    args = parse_args()
    point = (args.x, args.y, args.z)

    try:
        transformer = FrameTransformer.from_yaml(args.config)
        out = transformer.transform_point(args.from_frame, args.to_frame, point)
    except TransformError as exc:
        print("转换失败: {}".format(exc))
        raise SystemExit(2)

    print("配置: {}".format(args.config))
    print("输入: {} ({:.6f}, {:.6f}, {:.6f}) m".format(args.from_frame, *point))
    print("输出: {} ({:.6f}, {:.6f}, {:.6f}) m".format(args.to_frame, *out))


if __name__ == "__main__":
    main()
