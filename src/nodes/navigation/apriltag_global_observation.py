"""AprilTag absolute-observation contract for grab/drop zones only."""

import math
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple


ALLOWED_REGIONS = frozenset(("grab", "drop"))


@dataclass(frozen=True)
class AprilTagObservation:
    tag_id: int
    region: str
    map_x: float
    map_y: float
    map_yaw: float
    reprojection_error_px: float
    depth_residual_m: float
    vio_residual_m: float
    stable_frames: int
    stationary: bool
    map_frame: str = "map"

    def __post_init__(self) -> None:
        if isinstance(self.tag_id, bool) or not isinstance(self.tag_id, int):
            raise ValueError("tag_id must be an integer")
        if not self.map_frame:
            raise ValueError("map_frame is required")
        for name, value in (
            ("map_x", self.map_x),
            ("map_y", self.map_y),
            ("map_yaw", self.map_yaw),
            ("reprojection_error_px", self.reprojection_error_px),
            ("depth_residual_m", self.depth_residual_m),
            ("vio_residual_m", self.vio_residual_m),
        ):
            if not math.isfinite(float(value)):
                raise ValueError("{} must be finite".format(name))
        for name, value in (
            ("reprojection_error_px", self.reprojection_error_px),
            ("depth_residual_m", self.depth_residual_m),
            ("vio_residual_m", self.vio_residual_m),
        ):
            if float(value) < 0.0:
                raise ValueError("{} must be non-negative".format(name))
        if isinstance(self.stable_frames, bool) or not isinstance(self.stable_frames, int):
            raise ValueError("stable_frames must be an integer")
        if self.stable_frames < 0:
            raise ValueError("stable_frames must be non-negative")


@dataclass(frozen=True)
class AbsolutePoseCandidate:
    accepted: bool
    reason: str
    tag_id: Optional[int] = None
    region: Optional[str] = None
    pose: Optional[Tuple[float, float, float]] = None


def validate_apriltag_observation(
    observation: AprilTagObservation,
    *,
    expected_map_frame: str = "map",
    tag_map: Optional[Mapping[int, object]] = None,
    max_reprojection_error_px: float = 2.5,
    max_depth_residual_m: float = 0.05,
    max_vio_residual_m: float = 0.30,
    min_stable_frames: int = 5,
) -> AbsolutePoseCandidate:
    """Apply every safety gate before submitting an absolute pose candidate."""
    if observation.region not in ALLOWED_REGIONS:
        return AbsolutePoseCandidate(False, "region_not_allowed")
    if observation.map_frame != expected_map_frame:
        return AbsolutePoseCandidate(False, "map_frame_mismatch")
    if tag_map is None or observation.tag_id not in tag_map:
        return AbsolutePoseCandidate(False, "tag_id_not_in_map")
    tag_entry = tag_map[observation.tag_id]
    if not isinstance(tag_entry, Mapping):
        return AbsolutePoseCandidate(False, "invalid_tag_map_entry")
    if str(tag_entry.get("region", "")) != observation.region:
        return AbsolutePoseCandidate(False, "tag_region_mismatch")
    if str(tag_entry.get("map_frame", expected_map_frame)) != expected_map_frame:
        return AbsolutePoseCandidate(False, "tag_map_frame_mismatch")
    tag_pose = tag_entry.get("pose")
    if not isinstance(tag_pose, Mapping):
        return AbsolutePoseCandidate(False, "tag_pose_missing")
    try:
        if not all(
            math.isfinite(float(tag_pose[name])) for name in ("x", "y", "yaw")
        ):
            return AbsolutePoseCandidate(False, "tag_pose_invalid")
    except (KeyError, TypeError, ValueError):
        return AbsolutePoseCandidate(False, "tag_pose_invalid")
    if not observation.stationary:
        return AbsolutePoseCandidate(False, "robot_not_stationary")
    if observation.stable_frames < min_stable_frames:
        return AbsolutePoseCandidate(False, "insufficient_stable_frames")
    if observation.reprojection_error_px > max_reprojection_error_px:
        return AbsolutePoseCandidate(False, "reprojection_error")
    if observation.depth_residual_m > max_depth_residual_m:
        return AbsolutePoseCandidate(False, "depth_residual")
    if observation.vio_residual_m > max_vio_residual_m:
        return AbsolutePoseCandidate(False, "vio_residual")
    return AbsolutePoseCandidate(
        True,
        "accepted",
        observation.tag_id,
        observation.region,
        (
            float(observation.map_x),
            float(observation.map_y),
            math.atan2(math.sin(observation.map_yaw), math.cos(observation.map_yaw)),
        ),
    )


__all__ = ["ALLOWED_REGIONS", "AbsolutePoseCandidate", "AprilTagObservation", "validate_apriltag_observation"]
