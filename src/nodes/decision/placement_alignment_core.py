"""ROS-independent placement pose fine alignment via letter and box-face observation.

单文件实现（尽可能少的文件）：
  * 观测构建：读 camera_frames 目录下 depth_relay_docker 的版本化深度帧契约
    （latest_depth.raw + latest_depth.json），配合
    cv.gauge_detector 的字母检测与 D455 稀疏深度投影，合成放置观测帧；
  * 控制：与 pick_alignment_core 相同的离散脉冲状态机，把机器人精确对准目标
    放置箱，然后（可选）触发机械臂放置。

本模块没有 ROS 导入。运行层通过 PlaceRuntime 注入时间、停车、运动命令与观测；
测试使用同一契约（与 test_pick_alignment_core 相同的 FakeRuntime 风格）。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Protocol, Tuple

import cv2
import numpy as np

from nodes.decision.manipulation_contracts import SegmentResult
from nodes.navigation.depth_contract import (
    FRAME_DATA_FILE,
    FRAME_METADATA_FILE,
    DepthContractError,
    DepthFrameMetadata,
    monotonic_age_sec,
    read_frame_snapshot,
)

# ── 观测帧 ──

COLOR_IMAGE_FILE = "latest_color.jpg"


@dataclass(frozen=True)
class PlaceObservationFrame:
    letter: str
    lateral_m: float
    distance_m: float
    yaw_rad: float
    sequence: int
    stamp_s: float


@dataclass(frozen=True)
class DepthFrameSnapshot:
    """Consistent raw depth plus fully validated versioned metadata."""

    metadata: DepthFrameMetadata
    raw: bytes

    @property
    def width(self) -> int:
        return self.metadata.width

    @property
    def height(self) -> int:
        return self.metadata.height

    @property
    def sequence(self) -> int:
        return self.metadata.sequence

    @property
    def stamp_s(self) -> float:
        return self.metadata.source_stamp_ns / 1_000_000_000.0


def read_depth_frame_snapshot(frames_dir: Path) -> Optional[DepthFrameSnapshot]:
    """Read a snapshot through the canonical sequence/CRC/CameraInfo checks."""
    try:
        metadata, raw = read_frame_snapshot(frames_dir)
    except (OSError, DepthContractError):
        return None
    return DepthFrameSnapshot(metadata=metadata, raw=raw)


def depth_array_from_raw(
    raw: bytes,
    width: int,
    height: int,
    *,
    step: Optional[int] = None,
    is_bigendian: bool = False,
) -> np.ndarray:
    """Convert a padded ROS uint16 frame into a compact ``(H, W)`` array."""
    row_step = width * 2 if step is None else int(step)
    if row_step < width * 2 or row_step % 2:
        raise ValueError("depth row step is invalid for uint16 data")
    if len(raw) != height * row_step:
        raise ValueError("raw depth size does not match metadata")
    dtype = ">u2" if is_bigendian else "<u2"
    padded = np.frombuffer(raw, dtype=dtype, count=height * (row_step // 2))
    return padded.reshape(height, row_step // 2)[:, :width]


# ── 投影几何 ──

@dataclass(frozen=True)
class CameraIntrinsics:
    fx: float
    fy: float
    cx: float
    cy: float


def nominal_d455_intrinsics(width: int, height: int) -> CameraIntrinsics:
    """D455 名义内参按分辨率缩放（640x480 基准 fx=fy=387.18, cx=320.5, cy=240.5）。

    camera_frames 契约不携带内参，且深度/彩色分辨率随 Docker 内驱动配置变化；
    config 未显式给内参时按帧分辨率取名义值，真机标定后可直接在 config 覆盖。
    """
    return CameraIntrinsics(
        387.18 * width / 640.0,
        387.18 * height / 480.0,
        320.5 * width / 640.0,
        240.5 * height / 480.0,
    )


def camera_intrinsics_from_metadata(camera_info: Dict[str, Any]) -> CameraIntrinsics:
    k = camera_info["k"]
    return CameraIntrinsics(
        fx=float(k[0]),
        fy=float(k[4]),
        cx=float(k[2]),
        cy=float(k[5]),
    )


def camera_pitch_rad_from_forward_axis(forward_axis: Tuple[float, float, float]) -> float:
    """相机前向轴在 base_link 下的俯仰角（fit_face_yaw 约定：>0 表示向下看）。

    从已标定的 base_link->camera_link 旋转矩阵第一列（link +X，即 D455 光轴
    +Z 方向）推导，避免手动量角。
    """
    x, y, z = (float(value) for value in forward_axis)
    return math.atan2(-z, math.hypot(x, y))


def extract_letters_from_detections(
    payload: dict,
    min_confidence: float = 0.5,
    *,
    expected_model_id: Optional[str] = None,
    expected_class_schema: Optional[str] = None,
) -> List[SimpleNamespace]:
    """从 /yolo/detections JSON 提取放置箱字母（A/B/C/D）。

    ``class_name`` 是唯一类别权威；数字 ID 不参与字母推断。低于
    min_confidence 的检测丢弃；bbox 取模型输入空间（640x480）的
    [x1, y1, x2, y2]，与 place_align 缩放后的彩色帧同一像素空间。
    """
    if expected_model_id is not None and payload.get("model_id") != expected_model_id:
        return []
    if (
        expected_class_schema is not None
        and payload.get("class_schema") != expected_class_schema
    ):
        return []
    letters = []
    for detection in payload.get("detections", []):
        letter = ""
        class_name = str(detection.get("class_name", ""))
        if class_name in {"A", "B", "C", "D"}:
            letter = class_name
        if not letter:
            continue
        if float(detection.get("confidence", 0.0)) < min_confidence:
            continue
        bbox = detection.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        letters.append(SimpleNamespace(
            letter=letter,
            confidence=float(detection.get("confidence", 0.0)),
            bbox=tuple(float(value) for value in bbox),
        ))
    return letters


@dataclass(frozen=True)
class RigidTransform:
    """刚体变换，``p_target = R @ p_source + t``。"""

    rotation: np.ndarray
    translation: np.ndarray

    @classmethod
    def from_quaternion_translation(
        cls,
        quaternion_xyzw: Tuple[float, float, float, float],
        translation_m: Tuple[float, float, float],
    ) -> "RigidTransform":
        x, y, z, w = (float(value) for value in quaternion_xyzw)
        rotation = np.array(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ],
            dtype=np.float64,
        )
        return cls(rotation, np.array([float(v) for v in translation_m], dtype=np.float64))

    def apply(self, points: np.ndarray) -> np.ndarray:
        return points @ self.rotation.T + self.translation


@dataclass(frozen=True)
class ProjectedDepthPoints:
    """raw 深度点一次性投影到彩色图像素的稀疏结果。"""

    image_shape: Tuple[int, int]
    projected_u: np.ndarray
    projected_v: np.ndarray
    points_color: np.ndarray


def project_raw_depth_to_color(
    depth_units: np.ndarray,
    depth_scale: float,
    color_shape: Tuple[int, int],
    depth_intrinsics: CameraIntrinsics,
    color_intrinsics: CameraIntrinsics,
    depth_to_color: RigidTransform,
    *,
    min_depth_m: float = 0.2,
    max_depth_m: float = 4.0,
) -> ProjectedDepthPoints:
    """将有效 raw 深度像素投影进彩色图像素（每帧一次，检测间复用）。

    Docker 内的 D455 发布原始（未对齐）深度帧，不在 Jetson 上做整帧硬件
    depth->color 对齐（耗 CPU），而是借鉴 d455_perception 的稀疏投影方案：
    每个有效深度像素在 camera_depth_optical_frame 系去投影，经静态
    depth_to_color 刚体变换进入 camera_color_optical_frame，再按彩色内参
    投影回像素。零深度与范围外的点被丢弃。
    """
    if depth_units.ndim != 2:
        raise ValueError("depth must be two-dimensional")
    if depth_scale <= 0.0:
        raise ValueError("depth_scale must be positive")
    if min_depth_m <= 0.0 or max_depth_m <= min_depth_m:
        raise ValueError("invalid depth projection range")
    height, width = int(color_shape[0]), int(color_shape[1])

    empty = lambda: ProjectedDepthPoints(
        (height, width),
        np.empty(0, dtype=np.int32),
        np.empty(0, dtype=np.int32),
        np.empty((0, 3), dtype=np.float64),
    )

    depth_m = depth_units.astype(np.float64) * depth_scale
    valid = (depth_m >= min_depth_m) & (depth_m <= max_depth_m)
    rows, cols = np.nonzero(valid)
    if rows.size == 0:
        return empty()

    z = depth_m[rows, cols]
    points_depth = np.column_stack(
        (
            (cols - depth_intrinsics.cx) * z / depth_intrinsics.fx,
            (rows - depth_intrinsics.cy) * z / depth_intrinsics.fy,
            z,
        )
    )
    points_color = depth_to_color.apply(points_depth)
    points_color = points_color[points_color[:, 2] > 0.0]
    if points_color.size == 0:
        return empty()

    projected_u = np.rint(
        points_color[:, 0] * color_intrinsics.fx / points_color[:, 2]
        + color_intrinsics.cx
    ).astype(np.int32)
    projected_v = np.rint(
        points_color[:, 1] * color_intrinsics.fy / points_color[:, 2]
        + color_intrinsics.cy
    ).astype(np.int32)
    in_bounds = (
        (projected_u >= 0)
        & (projected_u < width)
        & (projected_v >= 0)
        & (projected_v < height)
    )
    return ProjectedDepthPoints(
        (height, width),
        projected_u[in_bounds],
        projected_v[in_bounds],
        points_color[in_bounds],
    )


@dataclass(frozen=True)
class BBox3DEstimate:
    """字母 bbox 内稀疏深度点的稳健 3D 估计（camera_color_optical_frame）。"""

    position_m: Optional[Tuple[float, float, float]]
    depth_m: Optional[float]
    center_px: Tuple[int, int]
    valid_pixels: int
    valid_ratio: float

    @property
    def valid(self) -> bool:
        return self.position_m is not None


def estimate_bbox_3d_from_projected_depth(
    projection: ProjectedDepthPoints,
    bbox: Tuple[int, int, int, int],
    *,
    trim_fraction: float = 0.1,
    min_valid_pixels: int = 20,
) -> BBox3DEstimate:
    """从预投影深度点中估计字母 bbox 的 3D 位置。

    取落入 bbox 的点，按深度（彩色系 z）裁剪首尾 trim_fraction 排除边界背景
    污染，剩余点的中位数作为位置。valid_ratio 是唯一像素覆盖面积比，用于判定
    该 bbox 的深度覆盖率是否可信。
    """
    if not 0.0 <= trim_fraction < 0.5:
        raise ValueError("trim_fraction must be in [0, 0.5)")
    if min_valid_pixels < 1:
        raise ValueError("min_valid_pixels must be positive")

    x1, y1, x2, y2 = bbox
    height, width = projection.image_shape
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(width, x2), min(height, y2)
    bbox_area = max(1, (x2 - x1) * (y2 - y1))
    if projection.points_color.size == 0 or x2 <= x1 or y2 <= y1:
        return BBox3DEstimate(None, None, (0, 0), 0, 0.0)

    inside = (
        (projection.projected_u >= x1)
        & (projection.projected_u < x2)
        & (projection.projected_v >= y1)
        & (projection.projected_v < y2)
    )
    points = projection.points_color[inside]
    u = projection.projected_u[inside]
    v = projection.projected_v[inside]
    valid_pixels = int(points.shape[0])
    covered = np.unique(np.column_stack((u, v)), axis=0).shape[0]
    valid_ratio = covered / float(bbox_area)
    if valid_pixels < min_valid_pixels:
        center = (0, 0) if valid_pixels == 0 else (int(np.median(u)), int(np.median(v)))
        return BBox3DEstimate(None, None, center, valid_pixels, float(valid_ratio))

    # 稳定排序：合成数据/平面深度会出现大量 z 并列，numpy 1.x 默认不稳定
    # argsort 会打乱并列点顺序，trim 后中位数产生半像素级抖动（±0.005）。
    points = points[np.argsort(points[:, 2], kind="stable")]
    trim_count = int(valid_pixels * trim_fraction)
    if trim_count and valid_pixels - 2 * trim_count >= min_valid_pixels:
        points = points[trim_count:-trim_count]
    position = tuple(float(value) for value in np.median(points, axis=0))
    return BBox3DEstimate(
        position,
        position[2],
        (int(np.median(u)), int(np.median(v))),
        valid_pixels,
        float(valid_ratio),
    )


def fit_face_yaw(
    projection: ProjectedDepthPoints,
    bbox: Tuple[int, int, int, int],
    letter_position_m: Tuple[float, float, float],
    color_intrinsics: CameraIntrinsics,
    *,
    camera_pitch_rad: float,
    box_width_m: float,
    depth_window_m: float,
    row_pad_px: int,
    min_face_points: int,
) -> Optional[Tuple[float, float]]:
    """对箱面前脸的稀疏投影点做 TLS 直线拟合，返回 (yaw_rad, distance_m)。

    采样范围：水平深度在字母 ±depth_window_m 内、横向在字母列中心 ±半个箱宽
    （按深度换算像素）、纵向在字母 bbox 行 ±row_pad_px 内。

    相机以 pitch 安装时，前脸竖直平面在不同行的 raw z 不同：先把全部点转到
    水平深度 z_h = z*cos(pitch) - y*sin(pitch)，再在 z_h 域做对称采样与
    (x, z_h) 正交拟合，否则斜率被 pitch 放大 1/cos(pitch)，raw z 窗截断还会
    给距离估计带来系统偏差。

    yaw_rad 约定：>0 表示箱面法线在机器人左侧（需左转），运行层命令与误差同号
    即可收敛（符号按真机标定确认）。distance_m 为箱面水平距离中位数。
    """
    if letter_position_m is None or letter_position_m[2] <= 0.0:
        return None
    if projection.points_color.size == 0:
        return None
    cos_pitch, sin_pitch = math.cos(camera_pitch_rad), math.sin(camera_pitch_rad)
    _, letter_y, letter_z = letter_position_m
    x1, y1, x2, y2 = bbox
    u_center = (x1 + x2) / 2.0
    half_box_px = color_intrinsics.fx * (box_width_m / 2.0) / letter_z
    z_h = (
        projection.points_color[:, 2] * cos_pitch
        - projection.points_color[:, 1] * sin_pitch
    )
    letter_z_h = letter_z * cos_pitch - letter_y * sin_pitch
    mask = (
        (z_h >= letter_z_h - depth_window_m)
        & (z_h <= letter_z_h + depth_window_m)
        & (projection.projected_u >= u_center - half_box_px)
        & (projection.projected_u <= u_center + half_box_px)
        & (projection.projected_v >= y1 - row_pad_px)
        & (projection.projected_v <= y2 + row_pad_px)
    )
    points = projection.points_color[mask]
    if points.shape[0] < min_face_points:
        return None

    data = np.column_stack((points[:, 0], z_h[mask]))
    centered = data - data.mean(axis=0)
    covariance = centered.T @ centered
    _, eigenvectors = np.linalg.eigh(covariance)
    normal = eigenvectors[:, 0]  # 最小特征值方向 = (x, z_h) 直线法向
    if normal[1] < 0.0:
        normal = -normal
    yaw_rad = math.atan2(-normal[0], normal[1])
    return yaw_rad, float(np.median(z_h[mask]))


# ── 观测构建 ──

class LetterDetector(Protocol):
    """字母检测器（如 cv.gauge_detector.GaugeDetector）。

    ``detect(image)`` 返回带 ``letters`` 属性的结果，其元素暴露
    ``letter``/``confidence``/``bbox``。只做鸭子类型，本模块不依赖具体检测器。
    """

    def detect(self, image: np.ndarray) -> Any: ...


@dataclass(frozen=True)
class PlacementObservationConfig:
    frames_dir: Path = field(
        default_factory=lambda: Path.home() / "workspaces/isaac_ros-dev/camera_frames"
    )
    # 目标放置箱字母，由巡检异常区域决定。
    target_letter: str = "A"
    # D455 内参。文件契约不携带内参，默认 None 时按帧分辨率取名义值
    # （nominal_d455_intrinsics）；真机标定后可用标定值覆盖。
    depth_intrinsics: Optional[CameraIntrinsics] = None
    color_intrinsics: Optional[CameraIntrinsics] = None
    # 彩色帧缩放目标分辨率。relay 的 jpg 分辨率由 Docker 内驱动决定，
    # 而 /yolo/detections 的 bbox 在模型输入分辨率（640x480）下，故
    # 缩放彩色帧与其内参，使 bbox 与投影/拟合在同一像素空间。
    color_width: Optional[int] = None
    color_height: Optional[int] = None
    # 静态 depth->color 变换（TF: camera_depth_optical_frame -> camera_color_optical_frame），
    # 真机标定一次；默认单位阵。
    depth_to_color: RigidTransform = field(
        default_factory=lambda: RigidTransform.from_quaternion_translation(
            (0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0)
        )
    )
    min_depth_m: float = 0.2
    max_depth_m: float = 3.0
    trim_fraction: float = 0.1
    min_valid_pixels: int = 20
    min_valid_ratio: float = 0.6
    max_frame_age_s: float = 0.5
    # D455 安装俯仰角（rad），用于把深度点转到水平深度做 yaw 拟合。
    camera_pitch_rad: float = math.radians(30.0)
    # 放置箱前脸宽度（m），用于换算 yaw 拟合的横向采样范围。
    box_width_m: float = 0.50
    face_depth_window_m: float = 0.12
    row_pad_px: int = 20
    min_face_points: int = 50


class PlacementObservationBuilder:
    """把字母检测 + Docker raw 深度合成为 PlaceObservationFrame。

    输入：camera_frames 目录下的 latest_depth.raw/.meta.txt 与 latest_color.jpg；
    输出：PlaceObservationFrame（lateral/distance/yaw 已在彩色光学系下换算，
    横向正方向为机器人左侧，即 base_link +y）。
    """

    def __init__(
        self,
        config: PlacementObservationConfig,
        detector: LetterDetector,
    ) -> None:
        if config.max_frame_age_s <= 0.0:
            raise ValueError("max_frame_age_s must be positive")
        self._config = config
        self._detector = detector

    def observe(self) -> Optional[PlaceObservationFrame]:
        try:
            snapshot = read_depth_frame_snapshot(self._config.frames_dir)
        except (OSError, ValueError):
            return None
        if snapshot is None:
            return None
        try:
            frame_age_s = monotonic_age_sec(
                snapshot.metadata.monotonic_stamp_ns,
                now_ns=time.monotonic_ns(),
                label="placement depth frame timestamp",
            )
        except DepthContractError:
            return None
        if frame_age_s > self._config.max_frame_age_s:
            return None
        color = cv2.imread(str(self._config.frames_dir / COLOR_IMAGE_FILE))
        if color is None:
            return None
        color_shape = color.shape[:2]
        if self._config.color_width is not None and self._config.color_height is not None:
            if color_shape != (self._config.color_height, self._config.color_width):
                color = cv2.resize(
                    color, (self._config.color_width, self._config.color_height)
                )
                color_shape = color.shape[:2]
        # 内参未显式给出时按帧分辨率取 D455 名义值；缩放后亦随分辨率缩放。
        depth_intrinsics = self._config.depth_intrinsics or camera_intrinsics_from_metadata(
            snapshot.metadata.camera_info
        )
        color_intrinsics = self._config.color_intrinsics or nominal_d455_intrinsics(
            color_shape[1], color_shape[0]
        )
        letter = self._find_target_letter(self._detector.detect(color))
        if letter is None:
            return None

        depth_units = depth_array_from_raw(
            snapshot.raw,
            snapshot.width,
            snapshot.height,
            step=snapshot.metadata.step,
            is_bigendian=snapshot.metadata.is_bigendian,
        )
        projection = project_raw_depth_to_color(
            depth_units,
            snapshot.metadata.depth_scale,
            color_shape,
            depth_intrinsics,
            color_intrinsics,
            self._config.depth_to_color,
            min_depth_m=self._config.min_depth_m,
            max_depth_m=self._config.max_depth_m,
        )
        estimate = estimate_bbox_3d_from_projected_depth(
            projection,
            letter.bbox,
            trim_fraction=self._config.trim_fraction,
            min_valid_pixels=self._config.min_valid_pixels,
        )
        if (
            not estimate.valid
            or estimate.valid_ratio < self._config.min_valid_ratio
        ):
            return None
        if estimate.position_m is None:
            return None

        face = fit_face_yaw(
            projection,
            letter.bbox,
            estimate.position_m,
            color_intrinsics,
            camera_pitch_rad=self._config.camera_pitch_rad,
            box_width_m=self._config.box_width_m,
            depth_window_m=self._config.face_depth_window_m,
            row_pad_px=self._config.row_pad_px,
            min_face_points=self._config.min_face_points,
        )
        if face is None:
            return None
        yaw_rad, distance_m = face

        # 彩色光学系 x 向右，base_link +y 向左，故横向误差取反。
        lateral_m = -estimate.position_m[0]
        return PlaceObservationFrame(
            letter=letter.letter,
            lateral_m=lateral_m,
            distance_m=distance_m,
            yaw_rad=yaw_rad,
            sequence=snapshot.sequence,
            stamp_s=snapshot.stamp_s,
        )

    def _find_target_letter(self, result) -> Optional[Any]:
        best = None
        for detection in getattr(result, "letters", ()) or ():
            if getattr(detection, "letter", "") != self._config.target_letter:
                continue
            confidence = getattr(detection, "confidence", 0.0)
            if best is None or confidence > getattr(best, "confidence", 0.0):
                best = detection
        return best


# ── 放置执行器 ──

LETTER_IDS = frozenset("ABCD")


class PlaceState(str, Enum):
    IDLE = "idle"
    SETTLE = "settle"
    SELECT_TARGET = "select_target"
    ALIGN_YAW = "align_yaw"
    ALIGN_LAT = "align_lat"
    ALIGN_DIST = "align_dist"
    APPROACH = "approach"
    PLACE_PULSE = "place_pulse"
    PLACE_PULSE_SETTLE = "place_pulse_settle"
    CONFIRM_PLACE = "confirm_place"
    WAIT_PLACE = "wait_place"
    HOLD = "hold"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True)
class PlaceConfig:
    # 目标放置箱字母，由巡检任务判定为异常的区域决定，不自动选择。
    target_letter: str = "A"
    initial_settle_s: float = 0.5
    yaw_tolerance_rad: float = math.radians(3.0)
    lateral_tolerance_m: float = 0.03
    distance_tolerance_m: float = 0.02
    # 期望的箱面前脸距离（base_link），按机械臂落点标定。
    target_distance_m: float = 0.35
    # 远距先行进（实机 2026-08-15 新增）：观测距离超过 threshold 时不评估
    # yaw/横向——远处横向位移在 640px 图像里仅约 10px（淹没在 bbox 噪声），
    # 且距离观测存在姿态相关假漂移。先以 approach_target 为目标直走前进，
    # 脉冲结束后统一从 yaw 恢复校准。
    approach_threshold_m: float = 1.0
    approach_target_m: float = 0.4
    yaw_speed_rps: float = 0.10
    lateral_speed_mps: float = 0.025
    distance_speed_mps: float = 0.02
    yaw_gain: float = 0.6
    lateral_gain: float = 0.5
    distance_gain: float = 0.5
    min_yaw_speed_rps: float = 0.05
    min_lateral_speed_mps: float = 0.0125
    min_distance_speed_mps: float = 0.01
    pulse_min_s: float = 0.50
    pulse_max_s: float = 0.50
    pulse_settle_s: float = 0.0
    stable_frames: int = 3
    timeout_s: float = 80.0
    # 连续多帧看到非目标字母即判定停错箱体提前失败；0 表示禁用。
    abort_on_wrong_letter_frames: int = 10
    # "aligned"=对准确认后结束，不触发机械臂；"placed"=等待放置反馈并保持。
    stop_after_stage: str = "aligned"
    placed_hold_s: float = 3.2


class PlaceRuntime(Protocol):
    def now(self) -> float: ...
    def stop(self) -> None: ...
    def command(self, axis: str, speed: float) -> None: ...
    def current_observation(self) -> Optional[PlaceObservationFrame]: ...
    def start_place(self) -> bool: ...
    def place_result(self) -> Optional[bool]: ...


def wrap_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


class PlaceOneExecutor:
    """将机器人位姿精确对准目标放置箱，然后（可选）触发机械臂放置。

    观测由运行层合成（PlacementObservationBuilder + 真机运行层），本模块只消费
    抽象误差：字母检测给出目标箱 ID 与横向偏移（bbox 中心按深度换算为 base_link
    横向米），D455 深度与箱面前脸点云直线拟合给出距离与偏航。对齐采用与抓取
    对准相同的离散脉冲控制：

      检查 yaw -> 检查横向 -> 检查距离 -> 最终确认
          |            |            |
          +-------- 单轴脉冲、停车、静置，然后从 yaw 重新检查

    每次脉冲只允许一个轴非零。yaw 必须最先修正，因为旋转会改变横向与距离观测；
    距离最后修正，因为前进/后退会放大横向与 yaw 误差。
    """

    def __init__(self, runtime: PlaceRuntime, config: PlaceConfig = PlaceConfig()) -> None:
        if config.target_letter not in LETTER_IDS:
            raise ValueError("target_letter must be one of A/B/C/D, got {}".format(config.target_letter))
        self.runtime = runtime
        self.config = config
        self.state = PlaceState.IDLE
        self._entered_s = runtime.now()
        self._started_s = runtime.now()
        self._result: Optional[SegmentResult] = None
        self._confirm_count = 0
        self._last_confirm_sequence = -1
        self._wrong_letter_frames = 0
        self._pulse_axis = ""
        self._pulse_speed = 0.0
        self._pulse_until_s = 0.0
        self._post_pulse_sequence = -1
        self._pulse_start_obs: Optional[PlaceObservationFrame] = None
        self._resume_state = PlaceState.IDLE

    def start(self) -> None:
        if self.state != PlaceState.IDLE:
            raise RuntimeError("placement executor can only start from idle")
        self._started_s = self.runtime.now()
        self._set_state(PlaceState.SETTLE)

    def cancel(self, reason: str) -> SegmentResult:
        return self._finish(False, reason)

    def tick(self) -> Optional[SegmentResult]:
        if self._result is not None:
            return self._result
        if self.runtime.now() - self._started_s > self.config.timeout_s:
            return self._finish(False, "placement alignment timed out")
        if self.state == PlaceState.SETTLE:
            self.runtime.stop()
            if self._elapsed() >= self.config.initial_settle_s:
                self._set_state(PlaceState.SELECT_TARGET)
            return None
        if self.state == PlaceState.SELECT_TARGET:
            return self._select_target()
        if self.state in {
            PlaceState.ALIGN_YAW,
            PlaceState.ALIGN_LAT,
            PlaceState.ALIGN_DIST,
            PlaceState.CONFIRM_PLACE,
        }:
            return self._tick_alignment()
        if self.state == PlaceState.APPROACH:
            return self._tick_approach()
        if self.state == PlaceState.PLACE_PULSE:
            self._tick_pulse()
            return None
        if self.state == PlaceState.PLACE_PULSE_SETTLE:
            self._tick_pulse_settle()
            return None
        if self.state == PlaceState.WAIT_PLACE:
            result = self.runtime.place_result()
            if result is False:
                return self._finish(False, "place service failed")
            if result is True:
                self._set_state(PlaceState.HOLD)
            return None
        if self.state == PlaceState.HOLD and self._elapsed() >= self.config.placed_hold_s:
            return self._finish(
                True,
                "placement completed",
                alignment_success=True,
                place_success=True,
                outputs={"target_letter": self.config.target_letter},
            )
        return None

    def _select_target(self) -> Optional[SegmentResult]:
        self.runtime.stop()
        obs = self.runtime.current_observation()
        if obs is None:
            return None
        if obs.letter not in LETTER_IDS:
            # 未检测到字母（可能是仪表或无效检测）：保持停车等待。
            return None
        if obs.letter != self.config.target_letter:
            # 目标字母由巡检结果预先指定，执行器不自动改选。连续多帧出现错误
            # 字母说明导航可能停在了错误的箱体前，尽早失败让上层重新导航。
            self._wrong_letter_frames += 1
            if (
                self.config.abort_on_wrong_letter_frames > 0
                and self._wrong_letter_frames >= self.config.abort_on_wrong_letter_frames
            ):
                return self._finish(False, "WRONG_BOX: saw {} expected {}".format(
                    obs.letter, self.config.target_letter))
            return None
        self._wrong_letter_frames = 0
        self._set_state(PlaceState.ALIGN_YAW)
        return None

    def _current_target_observation(self) -> Optional[PlaceObservationFrame]:
        obs = self.runtime.current_observation()
        if obs is None or obs.letter != self.config.target_letter:
            return None
        return obs

    def _tick_approach(self) -> Optional[SegmentResult]:
        """远距先行进：距离仍远于 approach_target 时只发前进脉冲，不评估
        yaw/横向（远处观测分辨率不足 + 距离假漂移）。走到 approach_target
        附近后回到正常校准的 yaw 起点。"""
        obs = self._current_target_observation()
        if obs is None:
            self.runtime.stop()
            return None
        if obs.distance_m <= self.config.approach_target_m + self.config.distance_tolerance_m:
            self.runtime.stop()
            self._set_state(PlaceState.ALIGN_YAW)
            return None
        approach_error = obs.distance_m - self.config.approach_target_m
        self._start_pulse(
            "dist", approach_error,
            self.config.distance_gain,
            self.config.distance_speed_mps,
            self.config.min_distance_speed_mps,
            obs,
        )
        return None

    def _tick_alignment(self) -> Optional[SegmentResult]:
        obs = self._current_target_observation()
        if obs is None:
            # 目标字母丢失或数据过期时，绝不沿用上一条速度。等待期间总对齐超时
            # 仍然继续计时。
            self.runtime.stop()
            return None

        # 远距先行进（2026-08-15 实机新增）：观测距离超过阈值时，远处横向位移在
        # 640px 图像里仅约 10px（淹没在 bbox 噪声中），且距离观测存在姿态相关
        # 假漂移——此时校准 yaw/横向只会越纠越偏。切到 APPROACH 状态直走前进
        # 到 approach_target 附近，再回归 yaw -> 横向 -> 距离 的正常校准。
        if obs.distance_m > self.config.approach_threshold_m:
            self._set_state(PlaceState.APPROACH)
            return None

        # 所有误差定义为“当前观测值 - 期望值”。运动方向已经过真机标定，因此发送
        # 与误差同号的命令会使观测误差趋近于零。wrap_angle 将 yaw 误差限制在
        # [-pi, pi]，避免观测跨过 +/-pi 边界时错误地旋转接近一整圈。
        yaw_error = wrap_angle(obs.yaw_rad)
        lateral_error = obs.lateral_m
        distance_error = obs.distance_m - self.config.target_distance_m

        # 阶段 1：先修正朝向。旋转会改变观测到的横向/距离误差，因此 yaw 进入容差
        # 前不评估平移轴。
        if self.state == PlaceState.ALIGN_YAW:
            if abs(yaw_error) <= self.config.yaw_tolerance_rad:
                self.runtime.stop()
                self._set_state(PlaceState.ALIGN_LAT)
            else:
                self._start_pulse(
                    "yaw", yaw_error,
                    self.config.yaw_gain,
                    self.config.yaw_speed_rps,
                    self.config.min_yaw_speed_rps,
                    obs,
                )
            return None

        # 阶段 2：修正横向。字母 bbox 中心相对机器人前进轴的偏移由运行层换算为
        # base_link 米，正误差代表字母偏左。
        if self.state == PlaceState.ALIGN_LAT:
            if abs(lateral_error) <= self.config.lateral_tolerance_m:
                self.runtime.stop()
                self._set_state(PlaceState.ALIGN_DIST)
            else:
                self._start_pulse(
                    "lat", lateral_error,
                    self.config.lateral_gain,
                    self.config.lateral_speed_mps,
                    self.config.min_lateral_speed_mps,
                    obs,
                )
            return None

        # 阶段 3：修正距离。前进/后退会改变横向与偏航观测，因此放在最后。
        if self.state == PlaceState.ALIGN_DIST:
            if abs(distance_error) <= self.config.distance_tolerance_m:
                self.runtime.stop()
                self._set_state(PlaceState.CONFIRM_PLACE)
            else:
                self._start_pulse(
                    "dist", distance_error,
                    self.config.distance_gain,
                    self.config.distance_speed_mps,
                    self.config.min_distance_speed_mps,
                    obs,
                )
            return None

        # 最终确认必须在停车状态下完成。复检仍使用 yaw -> 横向 -> 距离的优先级；
        # 任一轴再次越界都会清零连续帧计数，并从第一个不合格的轴恢复对齐。
        self.runtime.stop()
        if abs(yaw_error) > self.config.yaw_tolerance_rad:
            self._restart_alignment(PlaceState.ALIGN_YAW)
        elif abs(lateral_error) > self.config.lateral_tolerance_m:
            self._restart_alignment(PlaceState.ALIGN_LAT)
        elif abs(distance_error) > self.config.distance_tolerance_m:
            self._restart_alignment(PlaceState.ALIGN_DIST)
        elif obs.sequence != self._last_confirm_sequence:
            # 只统计序列号不同的观测新帧。管理器 tick 频率高于感知消费频率，如果
            # 按 tick 计数，同一帧重复观测会被误判为多个稳定帧。
            self._last_confirm_sequence = obs.sequence
            self._confirm_count += 1
            if self._confirm_count >= self.config.stable_frames:
                if self.config.stop_after_stage == "aligned":
                    return self._finish(
                        True,
                        "placement pose aligned",
                        alignment_success=True,
                        outputs={
                            "test_stage": "aligned",
                            "target_letter": self.config.target_letter,
                            "final_lateral_m": obs.lateral_m,
                            "final_distance_m": obs.distance_m,
                            "final_yaw_rad": obs.yaw_rad,
                        },
                    )
                if not self.runtime.start_place():
                    return self._finish(False, "place service rejected")
                self._set_state(PlaceState.WAIT_PLACE)
        return None

    def _restart_alignment(self, state: PlaceState) -> None:
        self._confirm_count = 0
        self._set_state(state)

    def _start_pulse(
        self,
        axis: str,
        error: float,
        gain: float,
        maximum: float,
        minimum: float,
        obs: PlaceObservationFrame,
    ) -> None:
        # 比例控制输出同时包含硬件死区下限和安全上限：
        #
        #   |command| = clamp(|error| * Kp, minimum, maximum)
        #
        # 平移和 yaw 的 gain 单位都是 1/s。minimum 必须小于 maximum，Kp 才能在
        # 中间误差区间真正参与调速。小误差区使用下限以克服 Lite3 运动死区；大误差
        # 区使用上限限制步态速度并减小过冲。
        speed = min(max(abs(error) * gain, minimum), maximum)
        self._pulse_axis = axis
        self._pulse_speed = math.copysign(speed, error)

        # 根据当前误差和选定速度计算名义脉冲时长，然后进行上下限约束。平移轴使用
        # m/(m/s)，yaw 使用 rad/(rad/s)。Kp 较小时，该商可能超过 pulse_max_s，
        # 此时实际脉冲时长等于配置上限；只要速度没有被 minimum/maximum 钳制，
        # Kp 仍然能够调节速度。
        duration = min(max(abs(error) / speed, self.config.pulse_min_s), self.config.pulse_max_s)
        self._pulse_until_s = self.runtime.now() + duration
        # 脉冲前观测仅用于记录真机响应。脉冲后的控制必须使用新观测帧，不做外推。
        self._pulse_start_obs = obs
        print(
            "placement alignment pulse axis={} error={:.4f} speed={:.4f} duration_s={:.2f} "
            "letter={} lateral={:.3f} distance={:.3f} yaw={:.3f}".format(
                axis,
                error,
                self._pulse_speed,
                duration,
                obs.letter,
                obs.lateral_m,
                obs.distance_m,
                obs.yaw_rad,
            ),
            flush=True,
        )
        # 记录脉冲发起的来源状态：approach 脉冲结束后回到 APPROACH 继续走到
        # approach_target，其余轴脉冲结束后回到 ALIGN_YAW 从 yaw 重新检查。
        self._resume_state = self.state
        self._set_state(PlaceState.PLACE_PULSE)

    def _tick_pulse(self) -> None:
        if self.runtime.now() < self._pulse_until_s:
            # 按管理器 tick 频率重复发送唯一一个非零轴。ROS 运行层生成只包含该
            # 分量的 Twist，Lite3 bridge 再将其转换为对应轴的运动数据包。
            self.runtime.command(self._pulse_axis, self._pulse_speed)
            return
        # 每次脉冲都先显式停车，再观测运动结果。stop() 发布零 Twist，已验收的
        # bridge 将其转换为最后一个实际运动轴的同轴零速数据包。
        self.runtime.stop()
        obs = self.runtime.current_observation()
        # 停车瞬间已有的帧可能仍处于运动过程。保存其序列号，要求静置状态必须等待
        # 序列号严格更新的帧。
        self._post_pulse_sequence = -1 if obs is None else obs.sequence
        self._set_state(PlaceState.PLACE_PULSE_SETTLE)

    def _tick_pulse_settle(self) -> None:
        # 机械运动静置期间持续发送停车命令。此阶段不使用观测反馈，因为其中可能
        # 包含步态振动；若立即闭环，会触发正反方向交替修正并造成震荡。
        self.runtime.stop()
        if self._elapsed() < self.config.pulse_settle_s:
            return
        obs = self.runtime.current_observation()
        # 只有收到停车后的新帧才恢复对齐。感知数据过期时保持停车，直到出现新帧或
        # 执行器达到总超时。
        if obs is not None and obs.sequence > self._post_pulse_sequence:
            if obs.letter == self.config.target_letter and self._pulse_start_obs is not None:
                start = self._pulse_start_obs
                print(
                    "placement alignment observed axis={} lateral_delta={:.3f} "
                    "dist_delta={:.3f} yaw_delta={:.3f} sequence={} -> {}".format(
                        self._pulse_axis,
                        obs.lateral_m - start.lateral_m,
                        obs.distance_m - start.distance_m,
                        wrap_angle(obs.yaw_rad - start.yaw_rad),
                        start.sequence,
                        obs.sequence,
                    ),
                    flush=True,
                )
            self._pulse_start_obs = None
            # 脉冲结束后基于新帧恢复：approach 脉冲回 APPROACH 继续前行，
            # 其余脉冲回 ALIGN_YAW，确保三个轴都按 yaw -> 横向 -> 距离的
            # 既定优先级重新检查。
            self._set_state(self._resume_state)

    def _set_state(self, state: PlaceState) -> None:
        self.state = state
        self._entered_s = self.runtime.now()

    def _elapsed(self) -> float:
        return self.runtime.now() - self._entered_s

    def _finish(self, success: bool, reason: str, **kwargs) -> SegmentResult:
        self.runtime.stop()
        self.state = PlaceState.SUCCESS if success else PlaceState.FAILED
        self._result = SegmentResult(success=success, reason=reason, **kwargs)
        return self._result
