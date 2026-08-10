"""Pure-Python building blocks for the competition red-block task.

This module intentionally has no ROS imports.  It is shared by the ROS node
and unit tests so packet parsing, target selection and job completion rules do
not depend on hardware being present.
"""

from __future__ import annotations

import math
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field
from statistics import median
from typing import Deque, Iterable, List, Mapping, Optional, Sequence, Tuple


Point3 = Tuple[float, float, float]


class DetectionContractError(ValueError):
    """The host-side YOLO message does not satisfy the base_link contract."""


class CalibrationError(ValueError):
    """A required fixed map pose is absent or has not passed calibration."""


@dataclass(frozen=True)
class BlockDetection:
    """One valid 3-D coloured block observation in ``base_link``."""

    class_name: str
    position_m: Point3
    confidence: float


@dataclass(frozen=True)
class HostDetectionFrame:
    """One validated packet published by ``yolo_udp_bridge``."""

    sequence: int
    received_monotonic_s: float
    red_blocks: Tuple[BlockDetection, ...]
    green_blocks: Tuple[BlockDetection, ...]


def parse_host_detection_packet(
    packet: Mapping[str, object],
    received_monotonic_s: float,
    min_confidence: float,
    min_depth_valid_ratio: float,
) -> HostDetectionFrame:
    """Parse only the fields needed by the manipulation state machine.

    Invalid individual detections are ignored.  Invalid packet-level fields are
    rejected because consuming a frame from another coordinate system would
    make the velocity controller unsafe.
    """

    if packet.get("frame_id") != "base_link":
        raise DetectionContractError("YOLO frame_id must be base_link")
    sequence = packet.get("sequence")
    if not isinstance(sequence, int) or sequence < 0:
        raise DetectionContractError("YOLO sequence must be a non-negative integer")
    detections = packet.get("detections")
    if not isinstance(detections, list):
        raise DetectionContractError("YOLO detections must be an array")

    red: List[BlockDetection] = []
    green: List[BlockDetection] = []
    for detection in detections:
        if not isinstance(detection, Mapping):
            continue
        class_name = detection.get("class_name")
        if class_name not in {"red", "green"}:
            continue
        if not detection.get("position_valid", False):
            continue
        confidence = detection.get("confidence")
        depth_ratio = detection.get("depth_valid_ratio")
        position = detection.get("position_m")
        if not isinstance(confidence, (int, float)) or confidence < min_confidence:
            continue
        if not isinstance(depth_ratio, (int, float)) or depth_ratio < min_depth_valid_ratio:
            continue
        if not isinstance(position, (list, tuple)) or len(position) != 3:
            continue
        try:
            point = tuple(float(value) for value in position)
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in point):
            continue
        block = BlockDetection(str(class_name), point, float(confidence))
        if class_name == "red":
            red.append(block)
        else:
            green.append(block)

    return HostDetectionFrame(
        sequence=sequence,
        received_monotonic_s=float(received_monotonic_s),
        red_blocks=tuple(red),
        green_blocks=tuple(green),
    )


def median_point(points: Sequence[Point3]) -> Point3:
    """Return a coordinate-wise median, robust against one noisy depth frame."""

    if not points:
        raise ValueError("cannot calculate a median for an empty point set")
    return tuple(float(median([point[index] for point in points])) for index in range(3))


@dataclass
class _SpatialTrack:
    """Short-lived observation cluster; it never relies on detector array order."""

    points: List[Point3] = field(default_factory=list)

    @property
    def centre(self) -> Point3:
        return median_point(self.points)

    def distance_to(self, point: Point3) -> float:
        centre = self.centre
        return math.sqrt(sum((centre[index] - point[index]) ** 2 for index in range(3)))


class StableRedObserver:
    """Collect stable multi-frame red/green observations before selecting a target."""

    def __init__(
        self,
        window_size: int,
        required_stable_frames: int,
        match_gate_m: float,
    ) -> None:
        self._frames: Deque[HostDetectionFrame] = deque(maxlen=max(1, int(window_size)))
        self._required_stable_frames = max(1, int(required_stable_frames))
        self._match_gate_m = max(0.001, float(match_gate_m))

    def clear(self) -> None:
        self._frames.clear()

    def add(self, frame: HostDetectionFrame) -> None:
        """Store a new sequence once; repeated ROS messages must not add votes."""

        if self._frames and frame.sequence <= self._frames[-1].sequence:
            return
        self._frames.append(frame)

    def select_target(
        self,
        expected_red_count: int,
        expected_green_count: int,
        reference_base_xy: Tuple[float, float],
    ) -> Optional[Point3]:
        """Return a median red target when the complete platform view is stable.

        The required number of red and green blocks is checked per frame.  Red
        points are then clustered spatially, so a reordered YOLO array cannot
        change the selected physical block.
        """

        valid_frames = [
            frame for frame in self._frames
            if len(frame.red_blocks) == expected_red_count
            and len(frame.green_blocks) == expected_green_count
        ]
        if len(valid_frames) < self._required_stable_frames:
            return None
        valid_frames = valid_frames[-self._required_stable_frames:]

        tracks: List[_SpatialTrack] = []
        for frame in valid_frames:
            for block in frame.red_blocks:
                candidates = [track for track in tracks if track.distance_to(block.position_m) <= self._match_gate_m]
                if candidates:
                    min(candidates, key=lambda track: track.distance_to(block.position_m)).points.append(block.position_m)
                else:
                    tracks.append(_SpatialTrack(points=[block.position_m]))

        stable_tracks = [track for track in tracks if len(track.points) >= self._required_stable_frames]
        if len(stable_tracks) != expected_red_count:
            return None

        ref_x, ref_y = reference_base_xy
        selected = min(
            (track.centre for track in stable_tracks),
            key=lambda point: (abs(point[1] - ref_y), abs(point[0] - ref_x)),
        )
        return selected


@dataclass
class LockedTarget:
    """The selected physical red block, followed by nearest spatial position."""

    last_position_base: Point3
    last_sequence: int
    lost_frames: int = 0

    def match(self, frame: HostDetectionFrame, gate_m: float) -> Optional[Point3]:
        """Match the nearest red detection without using a YOLO list index."""

        if frame.sequence <= self.last_sequence:
            return None
        self.last_sequence = frame.sequence
        if not frame.red_blocks:
            self.lost_frames += 1
            return None

        candidate = min(
            (block.position_m for block in frame.red_blocks),
            key=lambda point: math.dist(point, self.last_position_base),
        )
        if math.dist(candidate, self.last_position_base) > gate_m:
            self.lost_frames += 1
            return None
        self.last_position_base = candidate
        self.lost_frames = 0
        return candidate


@dataclass(frozen=True)
class AxisPulse:
    """One short, single-axis command followed by a mandatory stop/settle."""

    speed_mps: float
    duration_s: float


def proportional_axis_pulse(
    error_m: float,
    gain_s_inv: float,
    max_speed_mps: float,
    min_speed_mps: float,
    min_duration_s: float,
    max_duration_s: float,
    direction_sign: float = 1.0,
) -> AxisPulse:
    """Build a bounded incremental-P command for a single robot axis."""

    if max_speed_mps <= 0 or min_speed_mps <= 0 or min_duration_s <= 0:
        raise ValueError("alignment speed and duration limits must be positive")
    if min_speed_mps > max_speed_mps or min_duration_s > max_duration_s:
        raise ValueError("invalid alignment bounds")
    raw_speed = float(gain_s_inv) * float(error_m)
    magnitude = min(max(abs(raw_speed), min_speed_mps), max_speed_mps)
    speed = math.copysign(magnitude * abs(float(direction_sign)), raw_speed * float(direction_sign))
    duration = min(max(abs(float(error_m)) / magnitude, min_duration_s), max_duration_s)
    return AxisPulse(speed_mps=speed, duration_s=duration)


@dataclass
class JobQueue:
    """Sorted abnormal-zone queue with an explicit place-success completion rule."""

    zones: Tuple[str, ...]
    index: int = 0

    @classmethod
    def from_zones(cls, zones: Iterable[str], required_count: int = 2) -> "JobQueue":
        cleaned = tuple(sorted({str(zone).strip().upper() for zone in zones if str(zone).strip()}))
        if len(cleaned) != required_count or any(zone not in {"A", "B", "C", "D"} for zone in cleaned):
            raise ValueError("exactly two distinct abnormal zones from A/B/C/D are required")
        return cls(zones=cleaned)

    @property
    def current_zone(self) -> str:
        if self.index >= len(self.zones):
            raise IndexError("all manipulation jobs are already complete")
        return self.zones[self.index]

    @property
    def complete(self) -> bool:
        return self.index >= len(self.zones)

    def complete_current(self, place_success: bool) -> bool:
        """Advance only after the fixed placement service explicitly succeeds."""

        if not place_success or self.complete:
            return False
        self.index += 1
        return True


@dataclass(frozen=True)
class ManipulationSites:
    """The calibrated map poses consumed by the red-block task."""

    calibration_set_id: str
    grasp_i0: Tuple[float, float, float]
    placements: Mapping[str, Tuple[float, float, float]]


def load_manipulation_sites(
    path: Path,
    zones: Iterable[str],
    required_status: str = "calibrated",
) -> ManipulationSites:
    """Load I0 and the requested A/B/C/D poses from the single calibration file."""

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - deployment dependency
        raise CalibrationError("PyYAML is required to load competition sites") from exc

    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        poses = data["dog_poses"]
        calibration_set_id = str(data["calibration_set"]["id"])
    except (OSError, KeyError, TypeError) as exc:
        raise CalibrationError("cannot read competition site calibration: {}".format(exc)) from exc

    def pose_for(name: str) -> Tuple[float, float, float]:
        entry = poses.get(name)
        if not isinstance(entry, Mapping):
            raise CalibrationError("missing calibration entry {}".format(name))
        if entry.get("status") != required_status:
            raise CalibrationError(
                "{} status is {!r}, required {!r}".format(name, entry.get("status"), required_status)
            )
        pose = entry.get("pose_map_m_rad")
        if not isinstance(pose, (list, tuple)) or len(pose) != 3:
            raise CalibrationError("{} must contain [x_m, y_m, yaw_rad]".format(name))
        try:
            result = tuple(float(value) for value in pose)
        except (TypeError, ValueError) as exc:
            raise CalibrationError("{} pose contains a non-numeric value".format(name)) from exc
        if not all(math.isfinite(value) for value in result):
            raise CalibrationError("{} pose contains a non-finite value".format(name))
        return result

    queue = JobQueue.from_zones(zones)
    placements = {zone: pose_for("placement_{}".format(zone)) for zone in queue.zones}
    return ManipulationSites(
        calibration_set_id=calibration_set_id,
        grasp_i0=pose_for("grasp_i0"),
        placements=placements,
    )
