#!/usr/bin/env python3
# coding: utf-8

"""纯计算坐标转换工具。

不依赖 ROS/NumPy/RealSense，只用 4x4 外参矩阵转换点坐标。
"""

from __future__ import print_function

import ast
import os


class TransformError(ValueError):
    """外参配置错误或缺少坐标系转换。"""


class FrameTransformer(object):
    """相机、机器狗、机械臂坐标互转。

    配置名格式为 target_from_source，例如 arm_from_camera 表示：
    p_arm = T_arm_camera * p_camera。反向转换自动求逆。
    """

    def __init__(self, transforms=None, units="m"):
        self.units = str(units)
        self.transforms = {}
        for name, matrix in (transforms or {}).items():
            self.transforms[str(name)] = validate_matrix4(matrix, name=str(name))

    @classmethod
    def from_yaml(cls, path):
        data = load_transform_config(path)
        return cls(data.get("transforms", {}), units=data.get("units", "m"))

    def transform_point(self, from_frame, to_frame, point):
        matrix = self.matrix(from_frame, to_frame)
        return transform_point(point, matrix)

    def transform_points(self, from_frame, to_frame, points):
        matrix = self.matrix(from_frame, to_frame)
        return [transform_point(point, matrix) for point in points]

    def matrix(self, from_frame, to_frame):
        from_frame = normalize_frame_name(from_frame)
        to_frame = normalize_frame_name(to_frame)
        if from_frame == to_frame:
            return identity_matrix4()

        direct_name = "{}_from_{}".format(to_frame, from_frame)
        if direct_name in self.transforms:
            return self.transforms[direct_name]

        reverse_name = "{}_from_{}".format(from_frame, to_frame)
        if reverse_name in self.transforms:
            return invert_rigid_matrix4(self.transforms[reverse_name])

        raise TransformError(
            "missing transform: need {} or {}".format(direct_name, reverse_name)
        )

    def camera_to_arm(self, point_camera):
        return self.transform_point("camera", "arm", point_camera)

    def arm_to_camera(self, point_arm):
        return self.transform_point("arm", "camera", point_arm)

    def dog_to_arm(self, point_dog):
        return self.transform_point("dog", "arm", point_dog)

    def arm_to_dog(self, point_arm):
        return self.transform_point("arm", "dog", point_arm)


def normalize_frame_name(name):
    name = str(name).strip()
    aliases = {
        "arm_base": "arm",
        "armpi": "arm",
        "camera_optical": "camera",
        "camera_link": "camera",
        "depth_camera": "camera",
        "d455": "camera",
        "dog_base": "dog",
        "base_link": "dog",
        "body": "dog",
    }
    return aliases.get(name, name)


def load_transform_config(path):
    """读取 config/frame_transforms.yaml 使用的简单 YAML 子集。"""

    if not os.path.exists(path):
        raise TransformError("config file not found: {}".format(path))

    units = "m"
    transforms = {}
    current_transform = None
    waiting_for_matrix = False
    rows = []

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].rstrip()
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("units:"):
                units = stripped.split(":", 1)[1].strip().strip("\"'")
                continue

            if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
                if current_transform is not None:
                    _store_matrix(transforms, current_transform, rows)
                current_transform = stripped[:-1].strip()
                waiting_for_matrix = False
                rows = []
                continue

            if current_transform is None:
                continue

            if stripped.startswith("matrix:"):
                waiting_for_matrix = True
                rows = []
                continue

            if waiting_for_matrix and stripped.startswith("-"):
                rows.append(ast.literal_eval(stripped[1:].strip()))

    if current_transform is not None:
        _store_matrix(transforms, current_transform, rows)

    if not transforms:
        raise TransformError("no transforms found in {}".format(path))

    return {
        "units": units,
        "transforms": transforms,
    }


def _store_matrix(transforms, name, rows):
    if rows:
        transforms[name] = validate_matrix4(rows, name=name)


def transform_point(point, matrix):
    matrix = validate_matrix4(matrix)
    values = tuple(float(x) for x in point)
    if len(values) != 3:
        raise TransformError("point must have 3 values, got {}".format(point))

    x, y, z = values
    homo = (x, y, z, 1.0)
    out = []
    for row in matrix:
        out.append(sum(row[i] * homo[i] for i in range(4)))
    w = out[3]
    if abs(w) <= 1e-12:
        raise TransformError("homogeneous transform produced w=0")
    return (out[0] / w, out[1] / w, out[2] / w)


def validate_matrix4(matrix, name="matrix"):
    try:
        rows = [tuple(float(x) for x in row) for row in matrix]
    except TypeError:
        raise TransformError("{} must be a 4x4 numeric matrix".format(name))

    if len(rows) != 4 or any(len(row) != 4 for row in rows):
        raise TransformError("{} must be a 4x4 matrix".format(name))
    return tuple(rows)


def identity_matrix4():
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def invert_rigid_matrix4(matrix):
    """刚体变换 [R t; 0 1] 求逆。"""

    matrix = validate_matrix4(matrix)
    r = [row[:3] for row in matrix[:3]]
    t = [matrix[i][3] for i in range(3)]

    rt = tuple(tuple(r[j][i] for j in range(3)) for i in range(3))
    tinv = tuple(-sum(rt[i][j] * t[j] for j in range(3)) for i in range(3))

    return (
        rt[0] + (tinv[0],),
        rt[1] + (tinv[1],),
        rt[2] + (tinv[2],),
        (0.0, 0.0, 0.0, 1.0),
    )
