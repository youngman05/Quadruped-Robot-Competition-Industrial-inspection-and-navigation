"""Fail-closed cuVSLAM global pose correction core and optional ROS node.

The tracking odometry remains the continuous ``odom -> base_link`` source.
The SLAM pose is only used to estimate ``map -> odom``.  The module keeps the
math independent from ROS so it can be tested on a laptop or Jetson host
without starting navigation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence, Tuple


PI = math.pi


def wrap_angle(angle: float) -> float:
    """Return an angle in [-pi, pi)."""
    return (float(angle) + PI) % (2.0 * PI) - PI


def _finite(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("{} must be a finite number".format(name)) from exc
    if not math.isfinite(result):
        raise ValueError("{} must be finite".format(name))
    return result


def normalize_quaternion(quaternion: Sequence[float]) -> Tuple[float, float, float, float]:
    values = tuple(_finite(value, "quaternion") for value in quaternion)
    if len(values) != 4:
        raise ValueError("quaternion must contain four values")
    norm = math.sqrt(sum(value * value for value in values))
    if norm < 1.0e-9:
        raise ValueError("quaternion norm is zero")
    return tuple(value / norm for value in values)  # type: ignore[return-value]


def quaternion_to_yaw(quaternion: Sequence[float]) -> float:
    x, y, z, w = normalize_quaternion(quaternion)
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def quaternion_from_yaw(yaw: float) -> Tuple[float, float, float, float]:
    half = wrap_angle(yaw) * 0.5
    return (0.0, 0.0, math.sin(half), math.cos(half))


@dataclass(frozen=True)
class SE2:
    """A planar transform ``parent -> child`` represented in the parent frame."""

    x: float
    y: float
    yaw: float

    def __post_init__(self) -> None:
        _finite(self.x, "x")
        _finite(self.y, "y")
        _finite(self.yaw, "yaw")

    def compose(self, other: "SE2") -> "SE2":
        cosine = math.cos(self.yaw)
        sine = math.sin(self.yaw)
        return SE2(
            self.x + cosine * other.x - sine * other.y,
            self.y + sine * other.x + cosine * other.y,
            wrap_angle(self.yaw + other.yaw),
        )

    def inverse(self) -> "SE2":
        cosine = math.cos(self.yaw)
        sine = math.sin(self.yaw)
        return SE2(
            -cosine * self.x - sine * self.y,
            sine * self.x - cosine * self.y,
            wrap_angle(-self.yaw),
        )

    def delta(self, other: "SE2") -> "SE2":
        """Return ``self^-1 * other`` for residual/jump gating."""
        return self.inverse().compose(other)

    def distance(self, other: "SE2") -> Tuple[float, float]:
        delta = self.delta(other)
        return math.hypot(delta.x, delta.y), abs(delta.yaw)


@dataclass(frozen=True)
class PoseSample:
    """A validated source-stamped odometry sample."""

    source_stamp: float
    frame_id: str
    child_frame_id: str
    x: float
    y: float
    z: float
    quaternion: Tuple[float, float, float, float]
    receive_time: Optional[float] = None
    sequence: Optional[int] = None
    tracking_ok: bool = True

    def __post_init__(self) -> None:
        _finite(self.source_stamp, "source_stamp")
        for name, value in (("x", self.x), ("y", self.y), ("z", self.z)):
            _finite(value, name)
        if not self.frame_id or not self.child_frame_id:
            raise ValueError("frame_id and child_frame_id are required")
        normalize_quaternion(self.quaternion)

    @property
    def yaw(self) -> float:
        return quaternion_to_yaw(self.quaternion)

    def planar(self) -> SE2:
        return SE2(self.x, self.y, self.yaw)


def _nested(payload: Dict[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise ValueError("missing field: {}".format(".".join(keys)))
        value = value[key]
    return value


def pose_sample_from_payload(
    payload: Dict[str, Any],
    *,
    frame_override: Optional[str] = None,
    child_override: Optional[str] = None,
) -> PoseSample:
    """Parse the transport payload and fail closed on missing/non-finite data."""
    stamp = _nested(payload, "stamp")
    source_stamp = _finite(stamp.get("sec"), "stamp.sec") + _finite(
        stamp.get("nanosec", 0), "stamp.nanosec"
    ) / 1.0e9
    pose = _nested(payload, "pose")
    position = _nested(pose, "position")
    orientation = _nested(pose, "orientation")
    sequence = payload.get("seq")
    return PoseSample(
        source_stamp=source_stamp,
        frame_id=frame_override or str(payload.get("frame_id") or "").strip(),
        child_frame_id=child_override
        or str(payload.get("child_frame_id") or "").strip(),
        x=_finite(position.get("x"), "pose.position.x"),
        y=_finite(position.get("y"), "pose.position.y"),
        z=_finite(position.get("z", 0.0), "pose.position.z"),
        quaternion=normalize_quaternion(
            (
                orientation.get("x"),
                orientation.get("y"),
                orientation.get("z"),
                orientation.get("w"),
            )
        ),
        receive_time=(
            _finite(payload["receive_time"], "receive_time")
            if payload.get("receive_time") is not None
            else None
        ),
        sequence=(
            int(sequence)
            if sequence is not None
            else None
        ),
        tracking_ok=bool(payload.get("tracking_ok", True)),
    )


@dataclass(frozen=True)
class PosePair:
    vo: PoseSample
    slam: PoseSample

    @property
    def stamp_delta(self) -> float:
        return abs(self.vo.source_stamp - self.slam.source_stamp)


def pair_pose_samples(
    vo_samples: Iterable[PoseSample],
    slam_samples: Iterable[PoseSample],
    *,
    max_stamp_delta: float = 0.05,
    now: Optional[float] = None,
    max_age: Optional[float] = None,
    expected_vo_frame: str = "odom",
    expected_slam_frame: str = "vslam_map",
    expected_child_frame: str = "base_link",
) -> List[PosePair]:
    """Pair each sample at most once by source timestamp.

    The function is deliberately conservative: frame, tracking and freshness
    failures are dropped instead of guessing from host arrival time.
    """
    if max_stamp_delta < 0.0:
        raise ValueError("max_stamp_delta must be non-negative")
    vo = [sample for sample in vo_samples if sample.frame_id == expected_vo_frame]
    slam = [sample for sample in slam_samples if sample.frame_id == expected_slam_frame]
    vo = [sample for sample in vo if sample.child_frame_id == expected_child_frame and sample.tracking_ok]
    slam = [sample for sample in slam if sample.child_frame_id == expected_child_frame and sample.tracking_ok]
    vo.sort(key=lambda sample: sample.source_stamp)
    slam.sort(key=lambda sample: sample.source_stamp)
    used = set()
    pairs: List[PosePair] = []
    for vo_sample in vo:
        candidates = [
            (abs(vo_sample.source_stamp - candidate.source_stamp), index, candidate)
            for index, candidate in enumerate(slam)
            if index not in used
        ]
        if not candidates:
            continue
        delta, index, slam_sample = min(candidates, key=lambda value: (value[0], value[1]))
        if delta > max_stamp_delta:
            continue
        if max_age is not None and now is not None:
            for sample in (vo_sample, slam_sample):
                if sample.receive_time is not None and now - sample.receive_time > max_age:
                    break
            else:
                used.add(index)
                pairs.append(PosePair(vo_sample, slam_sample))
            continue
        used.add(index)
        pairs.append(PosePair(vo_sample, slam_sample))
    return pairs


@dataclass(frozen=True)
class AlignmentResult:
    transform: SE2
    residuals: Tuple[float, ...]
    max_residual: float
    point_count: int
    scale_ratio: float = 1.0


def fit_se2_alignment(
    vslam_points: Sequence[Tuple[float, float]],
    nav_points: Sequence[Tuple[float, float]],
    *,
    yaw_hint: Optional[float] = None,
) -> AlignmentResult:
    """Fit ``nav_map <- vslam_map`` from at least two control points.

    A single control point is accepted only with an explicit yaw hint and is
    marked by a non-zero residual sentinel so callers cannot mistake it for a
    completed map calibration.
    """
    if len(vslam_points) != len(nav_points) or len(vslam_points) == 0:
        raise ValueError("alignment requires equally sized, non-empty point sets")
    if len(vslam_points) == 1:
        if yaw_hint is None:
            raise ValueError("one control point requires yaw_hint")
        v = vslam_points[0]
        n = nav_points[0]
        transform = SE2(
            n[0] - (math.cos(yaw_hint) * v[0] - math.sin(yaw_hint) * v[1]),
            n[1] - (math.sin(yaw_hint) * v[0] + math.cos(yaw_hint) * v[1]),
            wrap_angle(yaw_hint),
        )
        return AlignmentResult(transform, (float("inf"),), float("inf"), 1)
    v_mean = (
        sum(point[0] for point in vslam_points) / len(vslam_points),
        sum(point[1] for point in vslam_points) / len(vslam_points),
    )
    n_mean = (
        sum(point[0] for point in nav_points) / len(nav_points),
        sum(point[1] for point in nav_points) / len(nav_points),
    )
    v_energy = sum(
        (point[0] - v_mean[0]) ** 2 + (point[1] - v_mean[1]) ** 2
        for point in vslam_points
    )
    n_energy = sum(
        (point[0] - n_mean[0]) ** 2 + (point[1] - n_mean[1]) ** 2
        for point in nav_points
    )
    if v_energy <= 1.0e-12 or n_energy <= 1.0e-12:
        raise ValueError("alignment control points must span distinct positions in both maps")
    scale_ratio = math.sqrt(n_energy / v_energy)
    dot = 0.0
    cross = 0.0
    for v, n in zip(vslam_points, nav_points):
        vx, vy = v[0] - v_mean[0], v[1] - v_mean[1]
        nx, ny = n[0] - n_mean[0], n[1] - n_mean[1]
        dot += vx * nx + vy * ny
        cross += vx * ny - vy * nx
    yaw = math.atan2(cross, dot)
    cosine, sine = math.cos(yaw), math.sin(yaw)
    transform = SE2(
        n_mean[0] - (cosine * v_mean[0] - sine * v_mean[1]),
        n_mean[1] - (sine * v_mean[0] + cosine * v_mean[1]),
        yaw,
    )
    residuals = tuple(
        math.hypot(
            transform.x + cosine * v[0] - sine * v[1] - n[0],
            transform.y + sine * v[0] + cosine * v[1] - n[1],
        )
        for v, n in zip(vslam_points, nav_points)
    )
    return AlignmentResult(
        transform, residuals, max(residuals), len(vslam_points), scale_ratio,
    )


@dataclass(frozen=True)
class GlobalPoseConfig:
    nav_map_frame: str = "map"
    vslam_map_frame: str = "vslam_map"
    odom_frame: str = "odom"
    base_frame: str = "base_link"
    alignment: SE2 = field(default_factory=lambda: SE2(0.0, 0.0, 0.0))
    alignment_status: str = "pending"
    max_stamp_delta: float = 0.05
    max_age: float = 0.25
    stable_frames: int = 3
    max_candidate_jump_xy: float = 0.30
    max_candidate_jump_yaw: float = math.radians(15.0)
    max_residual_xy: float = 0.30
    max_residual_yaw: float = math.radians(15.0)
    small_correction_xy: float = 0.10
    small_correction_yaw: float = math.radians(5.0)
    medium_correction_xy: float = 0.30
    medium_correction_yaw: float = math.radians(15.0)

    def __post_init__(self) -> None:
        if self.stable_frames < 1:
            raise ValueError("stable_frames must be positive")
        if self.alignment_status not in ("pending", "complete"):
            raise ValueError("alignment_status must be pending or complete")
        for name, value in (
            ("small_correction_xy", self.small_correction_xy),
            ("small_correction_yaw", self.small_correction_yaw),
            ("medium_correction_xy", self.medium_correction_xy),
            ("medium_correction_yaw", self.medium_correction_yaw),
        ):
            if float(value) < 0.0 or not math.isfinite(float(value)):
                raise ValueError("{} must be a finite non-negative number".format(name))
        if self.medium_correction_xy < self.small_correction_xy:
            raise ValueError("medium_correction_xy must be >= small_correction_xy")
        if self.medium_correction_yaw < self.small_correction_yaw:
            raise ValueError("medium_correction_yaw must be >= small_correction_yaw")


@dataclass(frozen=True)
class PoseUpdate:
    accepted: bool
    reason: str
    candidate: Optional[SE2]
    current: Optional[SE2]
    stable_count: int
    mode: str
    correction_level: str = "none"


class GlobalPoseManagerCore:
    """State machine for the single dynamic ``map -> odom`` owner."""

    def __init__(self, config: Optional[GlobalPoseConfig] = None, mode: str = "legacy_static"):
        self.config = config or GlobalPoseConfig()
        self.mode = mode
        self.current: Optional[SE2] = None
        self._last_candidate: Optional[SE2] = None
        self._stable_count = 0
        self._last_update_time: Optional[float] = None
        self._last_pair_key: Optional[Tuple[float, float]] = None
        if mode not in ("legacy_static", "cuvslam_global", "relocalize_hold", "fault_hold"):
            raise ValueError("unsupported global pose mode: {}".format(mode))
        if mode == "cuvslam_global" and self.config.alignment_status != "complete":
            raise ValueError("cuvslam_global requires complete map alignment")

    def set_mode(self, mode: str) -> None:
        if mode not in ("legacy_static", "cuvslam_global", "relocalize_hold", "fault_hold"):
            raise ValueError("unsupported global pose mode: {}".format(mode))
        if mode == "cuvslam_global" and self.config.alignment_status != "complete":
            raise ValueError("cuvslam_global requires complete map alignment")
        self.mode = mode

    def reset(self) -> None:
        self.current = None
        self._last_candidate = None
        self._stable_count = 0
        self._last_update_time = None
        self._last_pair_key = None

    def _reject(
        self,
        reason: str,
        candidate: Optional[SE2] = None,
        correction_level: str = "none",
    ) -> PoseUpdate:
        return PoseUpdate(
            False, reason, candidate, self.current, self._stable_count, self.mode,
            correction_level,
        )

    def _correction_level(self, candidate: SE2) -> str:
        if self.current is None:
            return "initial"
        distance_xy, distance_yaw = self.current.distance(candidate)
        if (
            distance_xy <= self.config.small_correction_xy
            and distance_yaw <= self.config.small_correction_yaw
        ):
            return "small"
        if (
            distance_xy <= self.config.medium_correction_xy
            and distance_yaw <= self.config.medium_correction_yaw
        ):
            return "medium"
        return "large"

    def update(self, vo: PoseSample, slam: PoseSample, now: Optional[float] = None) -> PoseUpdate:
        now = time.time() if now is None else float(now)
        if self.mode != "cuvslam_global":
            return self._reject("mode_{}".format(self.mode))
        if self.config.alignment_status != "complete":
            return self._reject("alignment_pending")
        pair_key = (float(vo.source_stamp), float(slam.source_stamp))
        if self._last_pair_key == pair_key:
            return self._reject("duplicate_pair")
        if vo.frame_id != self.config.odom_frame or slam.frame_id != self.config.vslam_map_frame:
            return self._reject("frame_mismatch")
        if vo.child_frame_id != self.config.base_frame or slam.child_frame_id != self.config.base_frame:
            return self._reject("child_frame_mismatch")
        if not vo.tracking_ok or not slam.tracking_ok:
            return self._reject("tracking_not_ok")
        if abs(vo.source_stamp - slam.source_stamp) > self.config.max_stamp_delta:
            return self._reject("source_stamp_mismatch")
        for sample in (vo, slam):
            if sample.receive_time is not None and now - sample.receive_time > self.config.max_age:
                return self._reject("stale_sample")
        candidate = self.config.alignment.compose(slam.planar()).compose(vo.planar().inverse())
        correction_level = self._correction_level(candidate)
        if correction_level == "large":
            self._stable_count = 0
            self.mode = "fault_hold"
            return self._reject("candidate_jump", candidate, correction_level)
        if correction_level == "medium":
            self._stable_count = 0
            self.mode = "relocalize_hold"
            return self._reject("correction_requires_hold", candidate, correction_level)
        if self._last_candidate is not None:
            jump_xy, jump_yaw = self._last_candidate.distance(candidate)
            if jump_xy > self.config.max_candidate_jump_xy or jump_yaw > self.config.max_candidate_jump_yaw:
                self._stable_count = 0
                self.mode = "fault_hold"
                return self._reject("candidate_jump", candidate, "large")
        if self._last_candidate is None:
            self._stable_count = 1
        else:
            residual_xy, residual_yaw = self._last_candidate.distance(candidate)
            if residual_xy > self.config.max_residual_xy or residual_yaw > self.config.max_residual_yaw:
                self._stable_count = 0
                return self._reject("candidate_residual", candidate, correction_level)
            self._stable_count += 1
        self._last_candidate = candidate
        self._last_pair_key = pair_key
        if self._stable_count < self.config.stable_frames:
            return self._reject("warming_up", candidate, correction_level)
        self.current = candidate
        self._last_update_time = now
        return PoseUpdate(
            True, "accepted", candidate, self.current, self._stable_count, self.mode,
            correction_level,
        )


def load_global_pose_config(path: Path) -> GlobalPoseConfig:
    """Load a JSON-compatible YAML config without making PyYAML mandatory."""
    config_path = Path(path)
    text = config_path.read_text(encoding="utf-8")
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ValueError("global pose config requires JSON-compatible YAML or PyYAML") from exc
        document = yaml.safe_load(text)
    if not isinstance(document, dict):
        raise ValueError("global pose config must contain an object")
    alignment = document.get("alignment") or {}
    top_level_status = str(document.get("status", "pending"))
    alignment_status = str(alignment.get("status", top_level_status))
    if top_level_status != alignment_status:
        raise ValueError("global pose bundle and alignment status must match")
    if alignment_status == "complete":
        _validate_complete_bundle(document, config_path)
    return GlobalPoseConfig(
        nav_map_frame=str(document.get("nav_map_frame", "map")),
        vslam_map_frame=str(document.get("vslam_map_frame", "vslam_map")),
        odom_frame=str(document.get("odom_frame", "odom")),
        base_frame=str(document.get("base_frame", "base_link")),
        alignment=SE2(
            float(alignment.get("x", 0.0)),
            float(alignment.get("y", 0.0)),
            float(alignment.get("yaw", 0.0)),
        ),
        alignment_status=alignment_status,
        max_stamp_delta=float(document.get("max_stamp_delta", 0.05)),
        max_age=float(document.get("max_age", 0.25)),
        stable_frames=int(document.get("stable_frames", 3)),
        max_candidate_jump_xy=float(document.get("max_candidate_jump_xy", 0.30)),
        max_candidate_jump_yaw=float(document.get("max_candidate_jump_yaw", math.radians(15.0))),
        max_residual_xy=float(document.get("max_residual_xy", 0.30)),
        max_residual_yaw=float(document.get("max_residual_yaw", math.radians(15.0))),
        small_correction_xy=float(document.get("small_correction_xy", 0.10)),
        small_correction_yaw=float(document.get("small_correction_yaw", math.radians(5.0))),
        medium_correction_xy=float(document.get("medium_correction_xy", 0.30)),
        medium_correction_yaw=float(document.get("medium_correction_yaw", math.radians(15.0))),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_path(path: Path) -> str:
    if path.is_file():
        return _sha256_file(path)
    if not path.is_dir():
        return ""
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(_sha256_file(child).encode("ascii"))
    return digest.hexdigest()


def _bundle_path(document: Dict[str, Any], key: str, config_path: Path) -> Path:
    raw = str(document.get(key, ""))
    if not raw:
        raise ValueError("complete alignment bundle is missing {}".format(key))
    path = Path(raw)
    return path if path.is_absolute() else config_path.parent / path


def _validate_complete_bundle(document: Dict[str, Any], config_path: Path) -> None:
    if str(document.get("mode", "")) != "cuvslam_global":
        raise ValueError("complete alignment bundle must use cuvslam_global mode")
    artifact_fields = (
        ("nav_map_yaml", "nav_map_yaml_sha256", False),
        ("nav_map_image", "nav_map_image_sha256", False),
        ("vslam_map", "vslam_map_sha256", True),
        ("extrinsics_file", "extrinsics_sha256", False),
        ("start_prior_file", "start_prior_sha256", False),
    )
    for path_key, hash_key, allow_directory in artifact_fields:
        artifact = _bundle_path(document, path_key, config_path)
        if allow_directory:
            ready = (artifact.is_file() and artifact.stat().st_size > 0) or (
                artifact.is_dir()
                and any(
                    item.is_file() and item.stat().st_size > 0
                    for item in artifact.rglob("*")
                )
            )
            actual_hash = _sha256_path(artifact) if ready else ""
        else:
            ready = artifact.is_file() and artifact.stat().st_size > 0
            actual_hash = _sha256_file(artifact) if ready else ""
        expected_hash = str(document.get(hash_key, ""))
        if not ready or not expected_hash or actual_hash != expected_hash:
            raise ValueError("complete alignment bundle rejected: {} mismatch".format(hash_key))


try:  # ROS is intentionally optional for offline tests.
    import rclpy
    from geometry_msgs.msg import TransformStamped
    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from std_msgs.msg import String
    from tf2_ros import TransformBroadcaster
except ImportError:  # pragma: no cover - exercised on the ROS host only.
    rclpy = None


if rclpy is not None:

    class GlobalPoseManagerNode(Node):
        """ROS wrapper; it is opt-in and never starts in legacy mode by default."""

        def __init__(self) -> None:
            super().__init__("global_pose_manager")
            self.declare_parameter("mode", "legacy_static")
            self.declare_parameter("config_file", "")
            self.declare_parameter("vo_topic", "/odom")
            self.declare_parameter("slam_topic", "/cuvslam/slam_pose")
            self.declare_parameter("record_csv", "")
            mode = str(self.get_parameter("mode").value)
            config_file = str(self.get_parameter("config_file").value)
            config = load_global_pose_config(Path(config_file)) if config_file else GlobalPoseConfig()
            self._core = GlobalPoseManagerCore(config, mode=mode)
            self._vo: Deque[PoseSample] = deque(maxlen=30)
            self._slam: Deque[PoseSample] = deque(maxlen=30)
            self._tf = TransformBroadcaster(self)
            self._status_pub = self.create_publisher(String, "/cuvslam/global_pose_status", 10)
            self._record_handle = None
            self._record_writer = None
            record_csv = str(self.get_parameter("record_csv").value)
            if record_csv:
                parent = Path(record_csv).expanduser().resolve().parent
                parent.mkdir(parents=True, exist_ok=True)
                self._record_handle = open(str(record_csv), "w", newline="", encoding="utf-8")
                self._record_writer = csv.writer(self._record_handle)
                self._record_writer.writerow([
                    "source_stamp", "vo_stamp", "slam_stamp", "stamp_delta",
                    "vo_x", "vo_y", "slam_x", "slam_y", "candidate_x",
                    "candidate_y", "candidate_yaw", "accepted", "reason",
                ])
            qos = QoSProfile(depth=20, reliability=ReliabilityPolicy.BEST_EFFORT)
            self.create_subscription(Odometry, str(self.get_parameter("vo_topic").value), self._on_vo, qos)
            self.create_subscription(Odometry, str(self.get_parameter("slam_topic").value), self._on_slam, qos)
            self.get_logger().info(
                "mode=%s alignment_status=%s vo=%s slam=%s; TF ownership is unique when dynamic" %
                (mode, config.alignment_status, self.get_parameter("vo_topic").value, self.get_parameter("slam_topic").value)
            )

        @staticmethod
        def _sample(message: Any, receive_time: float, frame_override: Optional[str] = None) -> PoseSample:
            pose = message.pose.pose
            return PoseSample(
                source_stamp=float(message.header.stamp.sec) + float(message.header.stamp.nanosec) / 1.0e9,
                frame_id=frame_override or message.header.frame_id,
                child_frame_id=message.child_frame_id,
                x=float(pose.position.x), y=float(pose.position.y), z=float(pose.position.z),
                quaternion=(float(pose.orientation.x), float(pose.orientation.y), float(pose.orientation.z), float(pose.orientation.w)),
                receive_time=receive_time,
            )

        def _on_vo(self, message: Any) -> None:
            self._vo.append(self._sample(message, time.time()))
            self._try_update()

        def _on_slam(self, message: Any) -> None:
            self._slam.append(self._sample(message, time.time(), self._core.config.vslam_map_frame))
            self._try_update()

        def _try_update(self) -> None:
            if not self._vo or not self._slam:
                return
            vo = self._vo[-1]
            slam = min(self._slam, key=lambda item: abs(item.source_stamp - vo.source_stamp))
            result = self._core.update(vo, slam, now=time.time())
            if result.candidate is not None and self._record_writer is not None:
                self._record_writer.writerow([
                    slam.source_stamp, vo.source_stamp, slam.source_stamp,
                    abs(vo.source_stamp - slam.source_stamp), vo.x, vo.y,
                    slam.x, slam.y, result.candidate.x, result.candidate.y,
                    result.candidate.yaw, result.accepted, result.reason,
                ])
                self._record_handle.flush()
            status = String()
            status.data = json.dumps({
                "accepted": result.accepted, "reason": result.reason,
                "mode": result.mode, "stable_count": result.stable_count,
            }, sort_keys=True)
            self._status_pub.publish(status)
            if result.accepted and result.current is not None and self._core.mode == "cuvslam_global":
                self._publish_tf(result.current, slam.source_stamp)

        def _publish_tf(self, transform: SE2, source_stamp: float) -> None:
            message = TransformStamped()
            message.header.stamp.sec = int(source_stamp)
            message.header.stamp.nanosec = int((source_stamp - int(source_stamp)) * 1.0e9)
            message.header.frame_id = self._core.config.nav_map_frame
            message.child_frame_id = self._core.config.odom_frame
            message.transform.translation.x = transform.x
            message.transform.translation.y = transform.y
            message.transform.rotation.z = math.sin(transform.yaw * 0.5)
            message.transform.rotation.w = math.cos(transform.yaw * 0.5)
            self._tf.sendTransform(message)

        def destroy_node(self) -> Any:
            if self._record_handle is not None:
                self._record_handle.close()
            return super().destroy_node()


def main(args: Optional[Sequence[str]] = None) -> int:
    if rclpy is None:
        raise RuntimeError("global_pose_manager requires ROS 2 rclpy")
    rclpy.init(args=args)
    node = GlobalPoseManagerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


__all__ = [
    "AlignmentResult", "GlobalPoseConfig", "GlobalPoseManagerCore", "PosePair",
    "PoseSample", "PoseUpdate", "SE2", "fit_se2_alignment", "load_global_pose_config",
    "normalize_quaternion", "pair_pose_samples", "pose_sample_from_payload",
    "quaternion_from_yaw", "quaternion_to_yaw", "wrap_angle",
]
