#!/usr/bin/env python3
"""AprilTag 36h11 识别脚本（独立运行，无需 ROS）。

检测核心移植自 ROSSUM 工作空间的 pointcloud/localization/apriltag.py，
只保留简单路径（plumb_bob 零畸变、无深度、无 ROS 依赖）。

四种输入模式：
    python apriltag_detect.py <图片路径>            # 静态图离线识别
    python apriltag_detect.py --selftest            # 合成 tag 图自测全链路
    python apriltag_detect.py --relay <目录>         # 轮询 Docker relay 落盘的 latest_color.jpg
        （与 whz_standalone_inspect.py 相同的取图方式）
    python apriltag_detect.py --live                # pyrealsense2 直连相机，实时窗口标注
        （D435i/D455 均可用；Q 退出，S 保存标注图 + JSON）

内参：--live 模式从相机实时读取；其他模式默认取 D455 硬编码值
（与 nodes/perception/color_image_publisher.py 一致），可用 --fx/--fy/--cx/--cy 覆盖。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

# D455 RGB 内参（640x480），与 color_image_publisher.py 中 CameraInfo 同源
_D455_FX = 617.0
_D455_FY = 617.0
_D455_CX = 320.0
_D455_CY = 240.0

RELAY_FILE_NAME = "latest_color.jpg"


@dataclass(frozen=True)
class AprilTagDetection:
    """一个检测到的 tag 及其在相机坐标系下的位姿。"""

    tag_id: int
    corners_px: np.ndarray
    center_px: Tuple[float, float]
    translation_m: np.ndarray
    rotation_vector: np.ndarray
    rotation_matrix: np.ndarray
    reprojection_error_px: float

    @property
    def distance_m(self) -> float:
        """相机到 tag 中心的直线距离（米）。"""

        return float(np.linalg.norm(self.translation_m))

    def to_dict(self) -> Dict[str, object]:
        """返回 JSON 可序列化的字典。"""

        return {
            "tag_id": self.tag_id,
            "center_px": list(self.center_px),
            "corners_px": self.corners_px.tolist(),
            "translation_m": self.translation_m.tolist(),
            "distance_m": self.distance_m,
            "rotation_vector": self.rotation_vector.tolist(),
            "rotation_matrix": self.rotation_matrix.tolist(),
            "reprojection_error_px": self.reprojection_error_px,
        }


class AprilTag36h11Detector:
    """检测 tag36h11 标记并估计 6-DoF 位姿。

    Args:
        tag_size_m: 黑色检测方块的边长（不含白色安静区）。当前打印的 tag 用 0.100 m。
        expected_ids: 可选允许列表。None 或空序列接受所有 ID。
        max_reprojection_error_px: 重投影 RMS 误差超过该值的位姿被拒绝。
    """

    def __init__(
        self,
        tag_size_m: float = 0.100,
        *,
        expected_ids: Optional[Iterable[int]] = None,
        max_reprojection_error_px: float = 5.0,
    ) -> None:
        if tag_size_m <= 0:
            raise ValueError("tag_size_m must be positive")
        if max_reprojection_error_px <= 0:
            raise ValueError("max_reprojection_error_px must be positive")
        if not hasattr(cv2, "aruco"):
            raise RuntimeError(
                "OpenCV was installed without the aruco module. Install "
                "opencv-python>=5.0, or use opencv-contrib-python on OpenCV 4.x."
            )

        self.tag_size_m = float(tag_size_m)
        self.expected_ids = (
            None if not expected_ids else frozenset(int(value) for value in expected_ids)
        )
        self.max_reprojection_error_px = float(max_reprojection_error_px)

        self._dictionary = cv2.aruco.getPredefinedDictionary(
            cv2.aruco.DICT_APRILTAG_36h11
        )
        parameters = cv2.aruco.DetectorParameters()
        # 某些 OpenCV 5.x 构建移除了 CORNER_REFINE_SUBPIX 枚举，取不到时退回 CONTOUR
        refine = getattr(cv2.aruco, "CORNER_REFINE_SUBPIX", None)
        parameters.cornerRefinementMethod = (
            refine if refine is not None else cv2.aruco.CORNER_REFINE_CONTOUR
        )
        parameters.cornerRefinementWinSize = 5
        parameters.cornerRefinementMaxIterations = 30
        parameters.cornerRefinementMinAccuracy = 0.01
        self._parameters = parameters
        # OpenCV 4.7+ 才有 ArucoDetector；4.6 及更早走旧版 detectMarkers 接口
        self._detector = (
            cv2.aruco.ArucoDetector(self._dictionary, parameters)
            if hasattr(cv2.aruco, "ArucoDetector")
            else None
        )

        half = self.tag_size_m / 2.0
        # SOLVEPNP_IPPE_SQUARE 要求的角点顺序：左上、右上、右下、左下，+Y 向上
        self._object_corners = np.asarray(
            [
                [-half, half, 0.0],
                [half, half, 0.0],
                [half, -half, 0.0],
                [-half, -half, 0.0],
            ],
            dtype=np.float64,
        )

    def _detect_marker_corners(self, gray: np.ndarray) -> Tuple[Sequence[np.ndarray], Optional[np.ndarray]]:
        if self._detector is not None:
            corners, ids, _rejected = self._detector.detectMarkers(gray)
        else:  # OpenCV 4.6 及更早兼容
            corners, ids, _rejected = cv2.aruco.detectMarkers(
                gray,
                self._dictionary,
                parameters=self._parameters,
            )
        return corners, ids

    def _estimate_pose(
        self,
        corners_px: np.ndarray,
        camera_matrix: np.ndarray,
    ) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, float]]:
        distortion = np.zeros((5, 1), dtype=np.float64)  # plumb_bob 零畸变
        success, rotation_vector, translation = cv2.solvePnP(
            self._object_corners,
            corners_px,
            camera_matrix,
            distortion,
            flags=cv2.SOLVEPNP_IPPE_SQUARE,
        )
        if not success:
            return None
        rotation_vector = np.asarray(rotation_vector, dtype=np.float64).reshape(3)
        translation = np.asarray(translation, dtype=np.float64).reshape(3)
        if not np.all(np.isfinite(translation)) or translation[2] <= 0:
            return None

        projected, _ = cv2.projectPoints(
            self._object_corners,
            rotation_vector,
            translation,
            camera_matrix,
            distortion,
        )
        projected = projected.reshape(4, 2)
        residual = projected - corners_px
        reprojection_error = float(np.sqrt(np.mean(np.sum(residual**2, axis=1))))
        if reprojection_error > self.max_reprojection_error_px:
            return None

        rotation_matrix, _ = cv2.Rodrigues(rotation_vector)
        return rotation_vector, translation, rotation_matrix, reprojection_error

    def detect(
        self,
        color_bgr: np.ndarray,
        camera_matrix: np.ndarray,
    ) -> List[AprilTagDetection]:
        """在单帧 BGR 图像中检测 tag，返回通过位姿门限的结果。"""

        if color_bgr.ndim == 2:
            gray = color_bgr
        elif color_bgr.ndim == 3 and color_bgr.shape[2] == 3:
            gray = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2GRAY)
        else:
            raise ValueError("color_bgr must have shape (H, W) or (H, W, 3)")

        marker_corners, marker_ids = self._detect_marker_corners(gray)
        if marker_ids is None:
            return []

        detections: List[AprilTagDetection] = []
        for raw_corners, raw_id in zip(marker_corners, marker_ids.reshape(-1)):
            tag_id = int(raw_id)
            if self.expected_ids is not None and tag_id not in self.expected_ids:
                continue
            corners_px = np.asarray(raw_corners, dtype=np.float64).reshape(4, 2)
            pose = self._estimate_pose(corners_px, camera_matrix)
            if pose is None:
                continue
            rotation_vector, translation, rotation_matrix, reprojection_error = pose
            center = tuple(float(value) for value in corners_px.mean(axis=0))
            detections.append(
                AprilTagDetection(
                    tag_id=tag_id,
                    corners_px=corners_px,
                    center_px=center,
                    translation_m=translation,
                    rotation_vector=rotation_vector,
                    rotation_matrix=rotation_matrix,
                    reprojection_error_px=reprojection_error,
                )
            )

        detections.sort(key=lambda item: item.tag_id)
        return detections

    def annotate(
        self,
        color_bgr: np.ndarray,
        detections: Sequence[AprilTagDetection],
        camera_matrix: np.ndarray,
    ) -> np.ndarray:
        """返回标注了边框、坐标轴和位姿文字的图像副本。"""

        output = color_bgr.copy()
        distortion = np.zeros((5, 1), dtype=np.float64)

        for detection in detections:
            corners = np.rint(detection.corners_px).astype(np.int32)
            cv2.polylines(output, [corners], True, (0, 255, 0), 2, cv2.LINE_AA)
            cx, cy = (int(round(value)) for value in detection.center_px)
            cv2.circle(output, (cx, cy), 4, (0, 255, 255), -1, cv2.LINE_AA)

            axis_length = self.tag_size_m * 0.5
            axis_points = np.asarray(
                [
                    [0.0, 0.0, 0.0],
                    [axis_length, 0.0, 0.0],
                    [0.0, axis_length, 0.0],
                    [0.0, 0.0, axis_length],
                ],
                dtype=np.float64,
            )
            projected, _ = cv2.projectPoints(
                axis_points,
                detection.rotation_vector,
                detection.translation_m,
                camera_matrix,
                distortion,
            )
            projected = projected.reshape(-1, 2)

            origin = tuple(int(round(value)) for value in projected[0])
            axis_colors = ((0, 0, 255), (0, 255, 0), (255, 0, 0))  # BGR: X红 Y绿 Z蓝
            for idx, color in enumerate(axis_colors, start=1):
                endpoint = tuple(int(round(value)) for value in projected[idx])
                cv2.line(output, origin, endpoint, color, 2, cv2.LINE_AA)

            x, y, z = detection.translation_m
            label = (
                f"ID:{detection.tag_id} X:{x:+.3f} Y:{y:+.3f} "
                f"Z:{z:.3f}m dist:{detection.distance_m:.2f}m "
                f"err:{detection.reprojection_error_px:.2f}px"
            )
            label_origin = (int(corners[0, 0]), max(24, int(corners[0, 1]) - 10))
            # 先画黑描边再画绿字，保证任何背景下可读
            cv2.putText(
                output,
                label,
                label_origin,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (0, 0, 0),
                3,
                cv2.LINE_AA,
            )
            cv2.putText(
                output,
                label,
                label_origin,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (0, 255, 0),
                1,
                cv2.LINE_AA,
            )

        return output


def build_camera_matrix(fx: float, fy: float, cx: float, cy: float) -> np.ndarray:
    return np.asarray(
        [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def _print_detections(detections: Sequence[AprilTagDetection]) -> None:
    if not detections:
        print("no tag detected")
        return
    for item in detections:
        t = item.translation_m
        print(
            "  tag_id={}  dist={:.3f}m  err={:.2f}px  center=({:.1f}, {:.1f})  "
            "tvec=[{:.3f}, {:.3f}, {:.3f}]".format(
                item.tag_id,
                item.distance_m,
                item.reprojection_error_px,
                item.center_px[0],
                item.center_px[1],
                t[0],
                t[1],
                t[2],
            )
        )


def _process_image(
    detector: AprilTag36h11Detector,
    image_bgr: np.ndarray,
    camera_matrix: np.ndarray,
    save_out: Optional[str],
) -> None:
    detections = detector.detect(image_bgr, camera_matrix)
    print("found {} tag(s):".format(len(detections)))
    _print_detections(detections)
    if save_out is not None:
        annotated = detector.annotate(image_bgr, detections, camera_matrix)
        out_path = Path(save_out)
        cv2.imwrite(str(out_path), annotated)
        print("annotated image saved to {}".format(out_path))


def run_static(detector: AprilTag36h11Detector, camera_matrix: np.ndarray, args: argparse.Namespace) -> int:
    image = cv2.imread(args.image, cv2.IMREAD_COLOR)
    if image is None:
        print("failed to read image: {}".format(args.image), file=sys.stderr)
        return 1
    print("image: {} ({}x{})".format(args.image, image.shape[1], image.shape[0]))
    _process_image(detector, image, camera_matrix, args.save_out)
    return 0


def run_selftest(detector: AprilTag36h11Detector, camera_matrix: np.ndarray, args: argparse.Namespace) -> int:
    """合成一张 tag 图像，跑完整识别链路，证明环境可用。"""

    tag_id = 7
    marker = cv2.aruco.generateImageMarker(detector._dictionary, tag_id, 240)
    canvas = np.full((600, 800), 255, dtype=np.uint8)
    canvas[180:420, 280:520] = marker
    image_bgr = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
    print("selftest: synthetic tag_id={} on 800x600 canvas".format(tag_id))
    _process_image(detector, image_bgr, camera_matrix, args.save_out)
    return 0


def run_relay(detector: AprilTag36h11Detector, camera_matrix: np.ndarray, args: argparse.Namespace) -> int:
    """轮询 relay 目录下的 latest_color.jpg（Docker relay 落盘模式）。"""

    relay_file = Path(args.relay) / RELAY_FILE_NAME
    if not relay_file.parent.exists():
        print("relay directory does not exist: {}".format(relay_file.parent), file=sys.stderr)
        return 1
    print("watching {} every {:.2f}s (Ctrl+C to stop)".format(relay_file, args.interval))
    last_mtime = None
    try:
        while True:
            if relay_file.exists():
                mtime = relay_file.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    image = cv2.imread(str(relay_file), cv2.IMREAD_COLOR)
                    if image is not None:
                        _process_image(detector, image, camera_matrix, args.save_out)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


def _save_capture(
    directory: Path,
    image: np.ndarray,
    detections: Sequence[AprilTagDetection],
) -> None:
    """按当前时间戳保存标注图和检测 JSON（S 键触发）。"""

    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    image_path = directory / "apriltag_{}.png".format(stamp)
    json_path = directory / "apriltag_{}.json".format(stamp)
    if not cv2.imwrite(str(image_path), image):
        print("failed to save image: {}".format(image_path), file=sys.stderr)
        return
    payload = {"detections": [item.to_dict() for item in detections]}
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("saved: {}".format(image_path))
    print("saved: {}".format(json_path))


def run_live(detector: AprilTag36h11Detector, args: argparse.Namespace) -> int:
    """pyrealsense2 直连相机，实时窗口显示标注结果。

    内参从相机流实时读取，不依赖硬编码。Q 退出，S 保存当前帧。
    """

    try:
        import pyrealsense2 as rs
    except ImportError:
        print(
            "pyrealsense2 is required for --live mode. Install it with:\n"
            "  pip install pyrealsense2",
            file=sys.stderr,
        )
        return 2

    pipeline = rs.pipeline()
    config = rs.config()
    if args.serial:
        config.enable_device(args.serial)
    config.enable_stream(rs.stream.color, args.width, args.height, rs.format.bgr8, args.fps)
    try:
        profile = pipeline.start(config)
    except RuntimeError as exc:
        print("failed to start camera: {}".format(exc), file=sys.stderr)
        return 1

    color_profile = profile.get_stream(rs.stream.color)
    intrinsics = color_profile.as_video_stream_profile().get_intrinsics()
    camera_matrix = build_camera_matrix(
        float(intrinsics.fx), float(intrinsics.fy), float(intrinsics.ppx), float(intrinsics.ppy)
    )
    device_name = profile.get_device().get_info(rs.camera_info.name)

    print("connected: {} (serial {})".format(device_name, args.serial or profile.get_device().get_info(rs.camera_info.serial_number)))
    print("color: {}x{} @{}fps  intrinsics fx={:.1f} fy={:.1f} cx={:.1f} cy={:.1f}".format(
        intrinsics.width, intrinsics.height, args.fps, intrinsics.fx, intrinsics.fy, intrinsics.ppx, intrinsics.ppy))
    print("press Q to quit, S to save the annotated frame + JSON")

    last_tick = time.perf_counter()
    smoothed_fps = 0.0
    try:
        while True:
            frames = pipeline.wait_for_frames()
            color = frames.get_color_frame()
            if color is None:
                continue
            image_bgr = np.asanyarray(color.get_data())
            detections = detector.detect(image_bgr, camera_matrix)
            display = detector.annotate(image_bgr, detections, camera_matrix)

            now = time.perf_counter()
            instant_fps = 1.0 / max(now - last_tick, 1e-6)
            last_tick = now
            smoothed_fps = (
                instant_fps if smoothed_fps == 0.0 else 0.9 * smoothed_fps + 0.1 * instant_fps
            )
            status = "tags:{} fps:{:.1f}".format(len(detections), smoothed_fps)
            status_color = (0, 255, 0) if detections else (0, 0, 255)
            cv2.putText(display, status, (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(display, status, (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.65, status_color, 1, cv2.LINE_AA)
            if detections:
                _print_detections(detections)

            cv2.imshow("AprilTag 36h11 - {}".format(device_name), display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s"):
                _save_capture(args.capture_dir, display, detections)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        pipeline.stop()
        cv2.destroyAllWindows()
    return 0


def _parse_ids(text: Optional[str]) -> Optional[List[int]]:
    if not text:
        return None
    return [int(part.strip()) for part in text.split(",") if part.strip()]


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AprilTag 36h11 识别（独立脚本）：python apriltag_detect.py <图片> | --selftest | --relay <目录>"
    )
    parser.add_argument("image", nargs="?", help="静态图片路径（模式一）")
    parser.add_argument("--selftest", action="store_true", help="合成 tag 图自测全链路（模式二）")
    parser.add_argument("--relay", metavar="DIR", help="轮询该目录下的 latest_color.jpg（模式三）")
    parser.add_argument("--interval", type=float, default=0.2, help="relay 模式轮询间隔秒数（默认 0.2）")
    parser.add_argument("--live", action="store_true", help="pyrealsense2 直连相机实时标注（模式四）")
    parser.add_argument("--width", type=int, default=640, help="live 模式颜色流宽（默认 640）")
    parser.add_argument("--height", type=int, default=480, help="live 模式颜色流高（默认 480）")
    parser.add_argument("--fps", type=int, default=30, help="live 模式帧率（默认 30）")
    parser.add_argument("--serial", help="live 模式指定相机序列号（多相机时用）")
    parser.add_argument("--capture-dir", type=Path, default=Path("captures/apriltag"), help="S 键保存目录（默认 ./captures/apriltag）")

    parser.add_argument("--tag-size", type=float, default=0.100, help="tag 黑色方块边长，米（默认 0.10）")
    parser.add_argument("--expected-ids", metavar="IDS", help="只接受这些 ID，逗号分隔，如 0,1,2,3（默认全接受）")
    parser.add_argument("--max-reproj-error", type=float, default=5.0, help="重投影误差门限，像素（默认 5.0）")
    parser.add_argument("--save-out", metavar="PATH", help="保存标注图（默认不保存）")

    parser.add_argument("--fx", type=float, default=_D455_FX, help="内参 fx（默认 D455: 617）")
    parser.add_argument("--fy", type=float, default=_D455_FY, help="内参 fy（默认 D455: 617）")
    parser.add_argument("--cx", type=float, default=_D455_CX, help="内参 cx（默认 D455: 320）")
    parser.add_argument("--cy", type=float, default=_D455_CY, help="内参 cy（默认 D455: 240）")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    modes = [name for name in ("image", "selftest", "relay", "live") if getattr(args, name)]
    if len(modes) > 1:
        print("cannot combine input modes: {}".format(" + ".join(modes)), file=sys.stderr)
        return 2

    try:
        detector = AprilTag36h11Detector(
            tag_size_m=args.tag_size,
            expected_ids=_parse_ids(args.expected_ids),
            max_reprojection_error_px=args.max_reproj_error,
        )
    except ValueError as exc:
        print("invalid detector argument: {}".format(exc), file=sys.stderr)
        return 2

    if args.live:
        return run_live(detector, args)
    if args.selftest:
        camera_matrix = build_camera_matrix(args.fx, args.fy, args.cx, args.cy)
        return run_selftest(detector, camera_matrix, args)
    if args.relay:
        camera_matrix = build_camera_matrix(args.fx, args.fy, args.cx, args.cy)
        return run_relay(detector, camera_matrix, args)
    if args.image:
        camera_matrix = build_camera_matrix(args.fx, args.fy, args.cx, args.cy)
        return run_static(detector, camera_matrix, args)

    print(
        "no input mode given. Use: python apriltag_detect.py <图片> | --selftest | --relay <目录> | --live",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
