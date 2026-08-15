"""Hardware-free tests for placement observation and pose fine alignment."""

import math
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nodes.decision.placement_alignment_core import (
    COLOR_IMAGE_FILE,
    FRAME_DATA_FILE,
    FRAME_METADATA_FILE,
    CameraIntrinsics,
    PlaceConfig,
    PlaceObservationFrame,
    PlaceOneExecutor,
    PlaceState,
    PlacementObservationBuilder,
    PlacementObservationConfig,
    RigidTransform,
    camera_pitch_rad_from_forward_axis,
    estimate_bbox_3d_from_projected_depth,
    extract_letters_from_detections,
    fit_face_yaw,
    nominal_d455_intrinsics,
    project_raw_depth_to_color,
    read_depth_frame_snapshot,
)
from nodes.navigation.depth_contract import (
    DepthMode,
    build_frame_metadata,
    write_atomic_bytes,
    write_atomic_json,
)

W, H, FX, FY, CX, CY = 64, 64, 100.0, 100.0, 31.5, 31.5
IDENTITY = RigidTransform.from_quaternion_translation((0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0))


def camera_intrinsics():
    return CameraIntrinsics(FX, FY, CX, CY)


def build_face_depth(
    distance_m,
    slope_m=0.0,
    pitch_rad=0.0,
    half_width_m=0.25,
    half_height_m=0.10,
    scale=0.001,
):
    """逐像素精确构造箱面前脸深度：水平深度 z_h = distance - slope_m * x。

    相机以 pitch_rad 俯仰安装时，竖直前脸在原始 z 上随行号变化；公式
    z = (z_h + y*sin(pitch))/cos(pitch) 已按相机投影精确求解，保证投影
    回像素后的点严格落在目标平面上。
    """
    us, vs = np.meshgrid(
        np.arange(W, dtype=np.float64), np.arange(H, dtype=np.float64)
    )
    sinp, cosp = math.sin(pitch_rad), math.cos(pitch_rad)
    denom = cosp + slope_m * (us - CX) / FX - (vs - CY) * sinp / FY
    z = distance_m / denom
    x = (us - CX) * z / FX
    y = (vs - CY) * z / FY
    mask = (
        (np.abs(x) <= half_width_m)
        & (np.abs(y) <= half_height_m)
        & (z >= 0.2)
        & (z <= 4.0)
    )
    depth = np.zeros((H, W), dtype=np.uint16)
    depth[mask] = np.clip(z[mask] / scale, 0.0, 65535.0).astype(np.uint16)
    return depth


def build_face_depth_nominal(width, height, distance_m, pitch_rad=0.0):
    """用 D455 名义内参（按分辨率缩放）构造前脸，供 None 内参推导路径使用。"""
    fx = 387.18 * width / 640.0
    fy = 387.18 * height / 480.0
    cx = 320.5 * width / 640.0
    cy = 240.5 * height / 480.0
    us, vs = np.meshgrid(
        np.arange(width, dtype=np.float64), np.arange(height, dtype=np.float64)
    )
    sinp, cosp = math.sin(pitch_rad), math.cos(pitch_rad)
    denom = cosp - (vs - cy) * sinp / fy
    z = distance_m / denom
    x = (us - cx) * z / fx
    y = (vs - cy) * z / fy
    mask = (
        (np.abs(x) <= 0.25) & (np.abs(y) <= 0.10) & (z >= 0.2) & (z <= 4.0)
    )
    depth = np.zeros((height, width), dtype=np.uint16)
    depth[mask] = np.clip(z[mask] / 0.001, 0.0, 65535.0).astype(np.uint16)
    return depth


def project(depth):
    return project_raw_depth_to_color(
        depth,
        0.001,
        (H, W),
        camera_intrinsics(),
        camera_intrinsics(),
        IDENTITY,
    )


def write_frame(directory, depth, sequence, *, monotonic_stamp_ns=None):
    """Write the canonical versioned depth relay contract."""
    height, width = depth.shape
    raw = depth.tobytes()
    intrinsics = nominal_d455_intrinsics(width, height)
    camera_info = {
        "width": width,
        "height": height,
        "distortion_model": "plumb_bob",
        "d": [],
        "k": [intrinsics.fx, 0.0, intrinsics.cx, 0.0, intrinsics.fy, intrinsics.cy, 0.0, 0.0, 1.0],
        "r": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        "p": [intrinsics.fx, 0.0, intrinsics.cx, 0.0, 0.0, intrinsics.fy, intrinsics.cy, 0.0, 0.0, 0.0, 1.0, 0.0],
        "binning_x": 0,
        "binning_y": 0,
        "roi": {},
    }
    metadata = build_frame_metadata(
        raw=raw,
        stream_id="placement-test-stream",
        sequence=max(1, int(sequence)),
        source_stamp_ns=max(1, int(sequence)),
        width=width,
        height=height,
        step=width * 2,
        frame_id="camera_depth_optical_frame",
        depth_scale=0.001,
        camera_info=camera_info,
        mode=DepthMode.MANIPULATION,
        monotonic_stamp_ns=monotonic_stamp_ns,
    )
    write_atomic_bytes(directory / FRAME_DATA_FILE, raw)
    write_atomic_json(directory / FRAME_METADATA_FILE, metadata.to_dict())
    cv2.imwrite(
        str(directory / COLOR_IMAGE_FILE),
        np.zeros((height, width, 3), dtype=np.uint8),
    )


def obs(sequence, lateral_m=0.0, distance_m=0.35, yaw_rad=0.0, letter="A"):
    return PlaceObservationFrame(letter, lateral_m, distance_m, yaw_rad, sequence, sequence / 1e9)


class SnapshotTests(unittest.TestCase):
    def test_reads_relay_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_frame(directory, build_face_depth(1.0), sequence=123456789)
            snapshot = read_depth_frame_snapshot(directory)
        self.assertIsNotNone(snapshot)
        self.assertEqual((snapshot.width, snapshot.height), (W, H))
        self.assertEqual(snapshot.sequence, 123456789)
        self.assertEqual(len(snapshot.raw), W * H * 2)

    def test_partial_write_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / FRAME_METADATA_FILE).write_text("{}", encoding="utf-8")
        self.assertIsNone(read_depth_frame_snapshot(directory))


class ProjectionTests(unittest.TestCase):
    def test_projects_raw_depth_into_color_pixels(self):
        depth = np.zeros((3, 3), dtype=np.uint16)
        depth[0, 0] = 1000
        depth[1, 1] = 1000
        projection = project_raw_depth_to_color(
            depth,
            0.001,
            (3, 3),
            CameraIntrinsics(100.0, 100.0, 1.0, 1.0),
            CameraIntrinsics(100.0, 100.0, 1.0, 1.0),
            IDENTITY,
        )
        self.assertEqual(projection.points_color.shape, (2, 3))
        np.testing.assert_allclose(
            projection.points_color[0], [-0.01, -0.01, 1.0], atol=1e-9
        )
        np.testing.assert_allclose(
            projection.points_color[1], [0.0, 0.0, 1.0], atol=1e-9
        )
        np.testing.assert_array_equal(projection.projected_u, [0, 1])
        np.testing.assert_array_equal(projection.projected_v, [0, 1])

    def test_filters_zero_and_range_depth(self):
        depth = np.zeros((2, 2), dtype=np.uint16)
        depth[0, 0] = 0          # 无效深度
        depth[1, 1] = 5000       # 5 m，超出 max_depth
        projection = project_raw_depth_to_color(
            depth,
            0.001,
            (2, 2),
            CameraIntrinsics(100.0, 100.0, 0.5, 0.5),
            CameraIntrinsics(100.0, 100.0, 0.5, 0.5),
            IDENTITY,
            max_depth_m=3.0,
        )
        self.assertEqual(projection.points_color.shape[0], 0)


class BBoxEstimateTests(unittest.TestCase):
    def test_centered_bbox_estimates_origin(self):
        projection = project(build_face_depth(1.0))
        estimate = estimate_bbox_3d_from_projected_depth(projection, (26, 26, 38, 38))
        self.assertTrue(estimate.valid)
        np.testing.assert_allclose(estimate.position_m, [0.0, 0.0, 1.0], atol=1e-9)
        self.assertEqual(estimate.depth_m, 1.0)
        self.assertGreater(estimate.valid_ratio, 0.9)

    def test_shifted_bbox_estimates_lateral_offset(self):
        projection = project(build_face_depth(1.0))
        estimate = estimate_bbox_3d_from_projected_depth(projection, (33, 26, 40, 38))
        self.assertTrue(estimate.valid)
        # bbox 内 u 中位数 36 -> x = (36 - 31.5) * 1.0 / 100
        np.testing.assert_allclose(estimate.position_m[0], 0.045, atol=1e-9)
        self.assertEqual(estimate.depth_m, 1.0)

    def test_bbox_without_depth_points_is_invalid(self):
        projection = project(build_face_depth(1.0))
        estimate = estimate_bbox_3d_from_projected_depth(projection, (2, 2, 8, 8))
        self.assertFalse(estimate.valid)
        self.assertIsNone(estimate.position_m)


class FaceYawFitTests(unittest.TestCase):
    def test_tilted_face_yaw(self):
        projection = project(build_face_depth(1.0, slope_m=0.05))
        yaw, distance = fit_face_yaw(
            projection,
            (20, 20, 44, 44),
            (0.0, 0.0, 1.0),
            camera_intrinsics(),
            camera_pitch_rad=0.0,
            box_width_m=0.5,
            depth_window_m=0.12,
            row_pad_px=20,
            min_face_points=50,
        )
        self.assertIsNotNone(yaw)
        # uint16 深度有 ±0.5mm 量化噪声（真机同样存在），容差按噪声水平放宽；
        # 控制器距离容差 ±2cm，mm 级偏差不构成风险。
        self.assertAlmostEqual(yaw, -math.atan(0.05), delta=5e-4)
        self.assertAlmostEqual(distance, 1.0, delta=2e-3)

    def test_pitch_compensation_keeps_yaw_exact(self):
        pitch = math.radians(30.0)
        projection = project(build_face_depth(1.0, slope_m=0.05, pitch_rad=pitch))
        estimate = estimate_bbox_3d_from_projected_depth(projection, (20, 20, 44, 44))
        yaw, distance = fit_face_yaw(
            projection,
            (20, 20, 44, 44),
            estimate.position_m,
            camera_intrinsics(),
            camera_pitch_rad=pitch,
            box_width_m=0.5,
            depth_window_m=0.12,
            row_pad_px=20,
            min_face_points=50,
        )
        self.assertIsNotNone(yaw)
        self.assertAlmostEqual(yaw, -math.atan(0.05), delta=5e-4)
        self.assertAlmostEqual(distance, 1.0, delta=2e-3)

    def test_insufficient_face_points_returns_none(self):
        projection = project(build_face_depth(1.0))
        result = fit_face_yaw(
            projection,
            (20, 0, 44, 2),     # bbox 行带落在箱面前脸之外
            (0.0, 0.0, 1.0),
            camera_intrinsics(),
            camera_pitch_rad=0.0,
            box_width_m=0.5,
            depth_window_m=0.12,
            row_pad_px=0,
            min_face_points=50,
        )
        self.assertIsNone(result)


class NominalIntrinsicsTests(unittest.TestCase):
    def test_scales_d455_nominal_by_resolution(self):
        full = nominal_d455_intrinsics(640, 480)
        self.assertAlmostEqual(full.fx, 387.18)
        self.assertAlmostEqual(full.fy, 387.18)
        self.assertAlmostEqual(full.cx, 320.5)
        self.assertAlmostEqual(full.cy, 240.5)

        half = nominal_d455_intrinsics(320, 240)
        self.assertAlmostEqual(half.fx, 193.59)
        self.assertAlmostEqual(half.cx, 160.25)
        self.assertAlmostEqual(half.cy, 120.25)

    def test_aspect_ratio_independent_scaling(self):
        wide = nominal_d455_intrinsics(1280, 720)
        self.assertAlmostEqual(wide.fx, 387.18 * 2.0)
        self.assertAlmostEqual(wide.fy, 387.18 * 1.5)
        self.assertAlmostEqual(wide.cx, 641.0)
        self.assertAlmostEqual(wide.cy, 360.75)


class CameraPitchTests(unittest.TestCase):
    def test_forward_axis_pitch(self):
        # 2026-08-04 标定 quaternion xyzw [0.000900958, 0.240529563, -0.013474058, 0.970547870]
        # 的第一列 ≈ (0.8839, -0.0257, -0.4669) -> 27.9° 向下。
        pitch = camera_pitch_rad_from_forward_axis((0.8839, -0.0257, -0.4669))
        self.assertAlmostEqual(pitch, math.radians(27.9), delta=0.01)

    def test_pure_down_looking_is_pi_over_two(self):
        self.assertAlmostEqual(
            camera_pitch_rad_from_forward_axis((0.0, 0.0, -1.0)), math.pi / 2.0
        )

    def test_flat_mount_is_zero(self):
        self.assertEqual(camera_pitch_rad_from_forward_axis((1.0, 0.0, 0.0)), 0.0)

    def test_forward_axis_pitch_positive_means_looking_down(self):
        self.assertGreater(
            camera_pitch_rad_from_forward_axis((0.0, 0.0, -1.0)),
            camera_pitch_rad_from_forward_axis((1.0, 0.0, 0.0)),
        )


class LetterExtractionTests(unittest.TestCase):
    def test_class_name_letters_are_extracted(self):
        letters = extract_letters_from_detections({
            "detections": [
                {"class_id": 0, "class_name": "A", "confidence": 0.9, "bbox": [1, 2, 3, 4]},
                {"class_id": 0, "class_name": "D", "confidence": 0.8, "bbox": [5, 6, 7, 8]},
                {"class_id": 0, "class_name": "gauge", "confidence": 0.9, "bbox": [9, 10, 11, 12]},
            ],
        })
        self.assertEqual([item.letter for item in letters], ["A", "D"])

    def test_class_id_does_not_override_class_name(self):
        letters = extract_letters_from_detections({
            "detections": [
                {"class_id": 1, "class_name": "gauge", "confidence": 0.9, "bbox": [1, 2, 3, 4]},
                {"class_id": 4, "class_name": "", "confidence": 0.7, "bbox": [5, 6, 7, 8]},
            ],
        })
        self.assertEqual(letters, [])

    def test_model_identity_is_enforced_when_requested(self):
        payload = {
            "model_id": "wrong",
            "class_schema": "competition-ad-red-green-v1",
            "detections": [
                {"class_id": 0, "class_name": "A", "confidence": 0.9, "bbox": [1, 2, 3, 4]},
            ],
        }
        self.assertEqual(
            extract_letters_from_detections(
                payload,
                expected_model_id="gauge-ad-3ed76de7-v1",
                expected_class_schema="competition-ad-red-green-v1",
            ),
            [],
        )

    def test_confidence_below_threshold_is_dropped(self):
        letters = extract_letters_from_detections(
            {
                "detections": [
                    {"class_id": 2, "class_name": "B", "confidence": 0.4, "bbox": [1, 2, 3, 4]},
                    {"class_id": 2, "class_name": "B", "confidence": 0.9, "bbox": [5, 6, 7, 8]},
                ],
            },
            min_confidence=0.5,
        )
        self.assertEqual(len(letters), 1)
        self.assertEqual(letters[0].bbox, (5.0, 6.0, 7.0, 8.0))

    def test_malformed_bbox_and_unknown_classes_are_skipped(self):
        letters = extract_letters_from_detections({
            "detections": [
                {"class_id": 1, "class_name": "A", "confidence": 0.9, "bbox": [1, 2]},
                {"class_id": 1, "class_name": "A", "confidence": 0.9, "bbox": "nope"},
                {"class_id": 9, "class_name": "Q", "confidence": 0.9, "bbox": [1, 2, 3, 4]},
            ],
        })
        self.assertEqual(letters, [])


class NominalObservationTests(unittest.TestCase):
    """内参未显式给出时按帧分辨率取 D455 名义值（ROS 适配器正是这么跑的）。"""

    def _observe(self, depth, width, height, letter_bbox, detector, **overrides):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            config = PlacementObservationConfig(
                frames_dir=directory,
                target_letter="B",
                depth_intrinsics=None,
                color_intrinsics=None,
                # 缩小后的 bbox 内有效点数少于默认 50。
                min_face_points=20,
                **overrides,
            )
            write_frame(directory, depth, sequence=1_000_000_000)
            if detector is None:
                detector = FakeDetector(
                    [SimpleNamespace(letter="B", confidence=0.9, bbox=letter_bbox)]
                )
            return PlacementObservationBuilder(config, detector).observe(), detector

    def test_derives_nominal_intrinsics_without_resize(self):
        frame, _ = self._observe(
            build_face_depth_nominal(64, 64, 1.0, pitch_rad=math.radians(30.0)),
            64, 64,
            (22, 28, 42, 36),
            None,
        )
        self.assertIsNotNone(frame)
        self.assertAlmostEqual(frame.distance_m, 1.0, delta=2e-3)
        # cx=32.05 与整数像素中心有亚像素偏移，容差放 5 mm。
        self.assertAlmostEqual(frame.lateral_m, 0.0, delta=5e-3)

    def test_resizes_color_with_nominal_intrinsics(self):
        # yolo bbox 在 32x32 模型空间；彩色帧从 64x64 缩放后 bbox 与投影对齐。
        frame, detector = self._observe(
            build_face_depth_nominal(64, 64, 1.0, pitch_rad=math.radians(30.0)),
            64, 64,
            (11, 14, 21, 18),
            None,
            color_width=32,
            color_height=32,
        )
        self.assertIsNotNone(frame)
        self.assertEqual(detector.last_image.shape, (32, 32, 3))
        self.assertAlmostEqual(frame.distance_m, 1.0, delta=3e-3)


class FakeDetector:
    def __init__(self, letters):
        self._letters = letters
        self.last_image = None

    def detect(self, image):
        self.last_image = image
        return SimpleNamespace(letters=self._letters)


class BuilderTests(unittest.TestCase):
    def _builder(self, directory, target_letter, detector):
        # 合成帧按测试内参（FX=100/CX=31.5）生成，config 必须用同一内参。
        return PlacementObservationBuilder(
            PlacementObservationConfig(
                frames_dir=directory,
                target_letter=target_letter,
                depth_intrinsics=camera_intrinsics(),
                color_intrinsics=camera_intrinsics(),
            ),
            detector,
        )

    def test_end_to_end_builds_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            # 与 builder 默认 camera_pitch_rad=30° 一致的箱面。
            write_frame(
                directory,
                build_face_depth(1.0, pitch_rad=math.radians(30.0)),
                sequence=7,
            )
            detector = FakeDetector(
                [SimpleNamespace(letter="B", confidence=0.9, bbox=(26, 26, 38, 38))]
            )
            frame = self._builder(directory, "B", detector).observe()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.letter, "B")
        self.assertEqual(frame.sequence, 7)
        self.assertAlmostEqual(frame.lateral_m, 0.0, places=6)
        self.assertAlmostEqual(frame.distance_m, 1.0, delta=2e-3)
        self.assertAlmostEqual(frame.yaw_rad, 0.0, delta=5e-4)
        self.assertIsNotNone(detector.last_image)

    def test_wrong_letter_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_frame(directory, build_face_depth(1.0), sequence=1)
            detector = FakeDetector(
                [SimpleNamespace(letter="A", confidence=0.9, bbox=(26, 26, 38, 38))]
            )
            frame = self._builder(directory, "B", detector).observe()
        self.assertIsNone(frame)

    def test_stale_depth_frame_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_frame(
                directory,
                build_face_depth(1.0),
                sequence=1,
                monotonic_stamp_ns=time.monotonic_ns() - 2_000_000_000,
            )
            detector = FakeDetector(
                [SimpleNamespace(letter="B", confidence=0.9, bbox=(26, 26, 38, 38))]
            )
            frame = self._builder(directory, "B", detector).observe()
        self.assertIsNone(frame)

    def test_bbox_without_depth_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_frame(directory, build_face_depth(1.0), sequence=1)
            detector = FakeDetector(
                [SimpleNamespace(letter="B", confidence=0.9, bbox=(2, 2, 8, 8))]
            )
            frame = self._builder(directory, "B", detector).observe()
        self.assertIsNone(frame)

    def test_no_letter_detected_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_frame(directory, build_face_depth(1.0), sequence=1)
            frame = self._builder(directory, "B", FakeDetector([])).observe()
        self.assertIsNone(frame)


class FakeRuntime:
    def __init__(self):
        self.time = 0.0
        self.obs = None
        self.commands = []
        self.stop_calls = 0
        self.start_calls = 0
        self.place_results = []

    def now(self):
        return self.time

    def stop(self):
        self.stop_calls += 1
        self.commands.append(("stop", 0.0))

    def command(self, axis, speed):
        self.commands.append((axis, speed))

    def current_observation(self):
        return self.obs

    def start_place(self):
        self.start_calls += 1
        return True

    def place_result(self):
        return self.place_results.pop(0) if self.place_results else None


class ExecutorTests(unittest.TestCase):
    def test_aligns_three_axes_then_succeeds(self):
        runtime = FakeRuntime()
        executor = PlaceOneExecutor(runtime, PlaceConfig(target_letter="A"))
        executor.start()
        runtime.time = 1.0
        self.assertEqual(executor.tick(), None)          # settle -> select
        runtime.obs = obs(1)
        self.assertEqual(executor.tick(), None)          # select -> align_yaw
        self.assertEqual(executor.state, PlaceState.ALIGN_YAW)

        # 三个轴全部在容差内：依次进入 lat -> dist -> confirm。
        self.assertEqual(executor.tick(), None)
        self.assertEqual(executor.state, PlaceState.ALIGN_LAT)
        self.assertEqual(executor.tick(), None)
        self.assertEqual(executor.state, PlaceState.ALIGN_DIST)
        self.assertEqual(executor.tick(), None)
        self.assertEqual(executor.state, PlaceState.CONFIRM_PLACE)

        # 只统计序列号不同的新帧。
        self.assertEqual(executor.tick(), None)
        runtime.obs = obs(2)
        self.assertEqual(executor.tick(), None)
        runtime.obs = obs(3)
        result = executor.tick()
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertTrue(result.alignment_success)
        self.assertEqual(result.outputs["test_stage"], "aligned")
        self.assertEqual(result.outputs["target_letter"], "A")

    def test_yaw_pulse_rechecks_from_yaw(self):
        runtime = FakeRuntime()
        executor = PlaceOneExecutor(runtime, PlaceConfig(target_letter="A"))
        executor.start()
        runtime.time = 1.0
        executor.tick()
        runtime.obs = obs(1, yaw_rad=0.1)                # yaw 超差（>3°）
        executor.tick()                                  # 进入 align_yaw
        executor.tick()                                  # 发起 yaw 脉冲（进入 PLACE_PULSE）
        self.assertEqual(executor.state, PlaceState.PLACE_PULSE)
        executor.tick()                                  # 脉冲执行：发送命令
        self.assertTrue(
            any(axis == "yaw" and math.isclose(speed, 0.06, abs_tol=1e-9)
                for axis, speed in runtime.commands),
            "yaw pulse command 0.06 expected, got {}".format(runtime.commands),
        )                                                # 0.1*0.6=0.06

        runtime.time = 1.6                               # 脉冲结束
        executor.tick()                                  # 停车 -> 静置
        self.assertEqual(executor.state, PlaceState.PLACE_PULSE_SETTLE)
        runtime.obs = obs(2)                             # 新帧：yaw 已修好
        executor.tick()                                  # 回 yaw 重查
        self.assertEqual(executor.state, PlaceState.ALIGN_YAW)

        for _ in range(3):
            executor.tick()                              # yaw -> lat -> dist
        self.assertEqual(executor.state, PlaceState.CONFIRM_PLACE)
        result = None
        for seq in (3, 4, 5):                            # 3 帧稳定确认
            runtime.obs = obs(seq)
            result = executor.tick()
            if result is not None:
                break
        self.assertIsNotNone(result)
        self.assertTrue(result.success)

    def test_approach_pulse_when_distance_exceeds_threshold(self):
        runtime = FakeRuntime()
        executor = PlaceOneExecutor(
            runtime,
            PlaceConfig(target_letter="A", distance_speed_mps=0.15,
                        min_distance_speed_mps=0.05, distance_gain=0.6,
                        pulse_min_s=1.5, pulse_max_s=1.5),
        )
        executor.start()
        runtime.time = 1.0
        executor.tick()
        runtime.obs = obs(1, distance_m=1.5)              # 远超 1.0 阈值
        executor.tick()                                  # -> align_yaw
        executor.tick()                                  # 切 APPROACH
        self.assertEqual(executor.state, PlaceState.APPROACH)
        executor.tick()                                  # 发起 dist 前进脉冲
        self.assertEqual(executor.state, PlaceState.PLACE_PULSE)
        executor.tick()                                  # 执行脉冲
        self.assertTrue(
            any(axis == "dist" and math.isclose(speed, 0.15, abs_tol=1e-9)
                for axis, speed in runtime.commands),
            "approach dist pulse at max speed 0.15 expected, got {}".format(
                runtime.commands),
        )

    def test_approach_walks_in_then_resumes_normal_alignment(self):
        runtime = FakeRuntime()
        executor = PlaceOneExecutor(
            runtime,
            PlaceConfig(target_letter="A", distance_speed_mps=0.15,
                        min_distance_speed_mps=0.05, distance_gain=0.6,
                        pulse_min_s=1.5, pulse_max_s=1.5),
        )
        executor.start()
        runtime.time = 1.0
        executor.tick()
        runtime.obs = obs(1, distance_m=2.0)
        executor.tick()                                  # -> align_yaw
        executor.tick()                                  # 切 APPROACH
        self.assertEqual(executor.state, PlaceState.APPROACH)
        distance = 2.0
        seq = 2
        while distance > 0.4 + 0.02:                     # 一路走到 0.4 附近
            executor.tick()                              # 发 approach 脉冲
            self.assertEqual(executor.state, PlaceState.PLACE_PULSE)
            executor.tick()                              # 执行脉冲
            runtime.time += 1.5                          # 脉冲结束
            executor.tick()                              # 停车 -> 静置
            distance -= 0.225                            # 每轮前进 0.15*1.5=0.225m
            runtime.obs = obs(seq, distance_m=max(distance, 0.4))
            seq += 1
            executor.tick()                              # 新帧 -> 回 APPROACH
        executor.tick()                                  # APPROACH 检查已到 0.2 -> 回归 yaw
        self.assertEqual(executor.state, PlaceState.ALIGN_YAW)

        # 回归后走正常 yaw -> lat -> dist -> confirm 并成功。
        runtime.obs = obs(seq, distance_m=0.35)          # 正常校准目标距离
        executor.tick()                                  # yaw 达标 -> lat
        self.assertEqual(executor.state, PlaceState.ALIGN_LAT)
        executor.tick()                                  # lat 达标 -> dist
        self.assertEqual(executor.state, PlaceState.ALIGN_DIST)
        executor.tick()                                  # dist 达标 -> confirm
        self.assertEqual(executor.state, PlaceState.CONFIRM_PLACE)
        result = None
        for s in (seq + 1, seq + 2, seq + 3):
            runtime.obs = obs(s, distance_m=0.35)
            result = executor.tick()
            if result is not None:
                break
        self.assertIsNotNone(result)
        self.assertTrue(result.success)

    def test_wrong_letter_aborts(self):
        runtime = FakeRuntime()
        executor = PlaceOneExecutor(runtime, PlaceConfig(target_letter="A"))
        executor.start()
        runtime.time = 1.0
        executor.tick()
        result = None
        for i in range(11):                              # 默认连续 10 帧错误字母
            runtime.obs = obs(100 + i, letter="B")
            result = executor.tick()
            if result is not None:
                break
        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        self.assertIn("WRONG_BOX", result.reason)

    def test_lost_observation_holds_stop(self):
        runtime = FakeRuntime()
        executor = PlaceOneExecutor(runtime, PlaceConfig(target_letter="A"))
        executor.start()
        runtime.time = 1.0
        executor.tick()
        runtime.obs = obs(1, yaw_rad=0.1)
        executor.tick()
        executor.tick()                                  # 进入脉冲
        runtime.obs = None                               # 目标丢失
        stops_before = runtime.stop_calls
        executor.tick()
        self.assertEqual(executor.state, PlaceState.PLACE_PULSE)
        runtime.time = 10.0
        executor.tick()                                  # 脉冲结束：停车等待新帧
        self.assertEqual(executor.state, PlaceState.PLACE_PULSE_SETTLE)
        self.assertGreater(runtime.stop_calls, stops_before)

    def test_timeout_fails(self):
        runtime = FakeRuntime()
        executor = PlaceOneExecutor(runtime, PlaceConfig(target_letter="A", timeout_s=5.0))
        executor.start()
        runtime.time = 6.0
        result = executor.tick()
        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        self.assertIn("timed out", result.reason)

    def test_place_stage_triggers_arm_and_holds(self):
        runtime = FakeRuntime()
        executor = PlaceOneExecutor(
            runtime, PlaceConfig(target_letter="A", stop_after_stage="placed", placed_hold_s=3.2)
        )
        executor.start()
        runtime.time = 1.0
        executor.tick()
        runtime.obs = obs(1)
        for _ in range(4):
            executor.tick()                              # select -> yaw -> lat -> dist
        self.assertEqual(executor.state, PlaceState.CONFIRM_PLACE)
        for seq in (2, 3, 4):                            # 3 帧稳定确认
            runtime.obs = obs(seq)
            executor.tick()
        self.assertEqual(runtime.start_calls, 1)         # 确认通过后请求机械臂
        self.assertEqual(executor.state, PlaceState.WAIT_PLACE)
        runtime.place_results.append(True)
        executor.tick()
        self.assertEqual(executor.state, PlaceState.HOLD)
        runtime.time = 6.0                               # 越过 placed_hold_s
        result = executor.tick()
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertTrue(result.place_success)


if __name__ == "__main__":
    unittest.main()
