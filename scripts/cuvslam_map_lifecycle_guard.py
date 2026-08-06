#!/usr/bin/env python3
"""Fail-closed checks and goal payloads for cuVSLAM map lifecycle actions.

This module validates the complete map bundle and emits goals for the exact
Isaac ROS 2.1 interface installed on the competition Jetson.
"""

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


LOAD_ACTION_NAME = "/visual_slam/load_map_and_localize"
LOAD_ACTION_TYPE = "isaac_ros_visual_slam_interfaces/action/LoadMapAndLocalize"
SAVE_ACTION_NAME = "/visual_slam/save_map"
SAVE_ACTION_TYPE = "isaac_ros_visual_slam_interfaces/action/SaveMap"


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_path(path):
    """Hash either a saved-map file or directory deterministically."""
    path = Path(path)
    if path.is_file():
        return sha256_file(path)
    if not path.is_dir():
        return ""
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(sha256_file(child).encode("ascii"))
    return digest.hexdigest()


def map_path_ready(path):
    path = Path(path)
    return (path.is_file() and path.stat().st_size > 0) or (
        path.is_dir()
        and any(item.is_file() and item.stat().st_size > 0 for item in path.rglob("*"))
    )


@dataclass(frozen=True)
class MapBundle:
    nav_map_id: str
    vslam_map_id: str
    nav_map_yaml: Path
    vslam_map: Path
    extrinsics_file: Path
    start_prior_file: Path
    alignment_config: Path


@dataclass(frozen=True)
class LocalizationPrior:
    x: float
    y: float
    yaw: float
    frame_id: str = "map"

    def __post_init__(self):
        for name, value in (("x", self.x), ("y", self.y), ("yaw", self.yaw)):
            if not math.isfinite(float(value)):
                raise ValueError("prior {} must be finite".format(name))
        if not self.frame_id:
            raise ValueError("prior frame_id is required")


def validate_bundle(bundle, *, expected_alignment_status="complete"):
    errors = []
    if not bundle.nav_map_id or not bundle.vslam_map_id:
        errors.append("map ids are required")
    for label, path in (
        ("nav_map_yaml", bundle.nav_map_yaml),
        ("extrinsics_file", bundle.extrinsics_file),
        ("start_prior_file", bundle.start_prior_file),
        ("alignment_config", bundle.alignment_config),
    ):
        if not Path(path).is_file():
            errors.append("{} does not exist: {}".format(label, path))
    if not map_path_ready(bundle.vslam_map):
        errors.append("vslam_map is missing or empty: {}".format(bundle.vslam_map))
    alignment_status = ""
    document = {}
    nav_map_yaml_hash = sha256_file(bundle.nav_map_yaml) if Path(bundle.nav_map_yaml).is_file() else ""
    vslam_map_hash = sha256_path(bundle.vslam_map)
    nav_map_image_hash = ""
    extrinsics_hash = sha256_file(bundle.extrinsics_file) if Path(bundle.extrinsics_file).is_file() else ""
    start_prior_hash = sha256_file(bundle.start_prior_file) if Path(bundle.start_prior_file).is_file() else ""
    alignment_config_hash = sha256_file(bundle.alignment_config) if Path(bundle.alignment_config).is_file() else ""
    if Path(bundle.alignment_config).is_file():
        try:
            document = json.loads(Path(bundle.alignment_config).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            errors.append("alignment config is invalid JSON: {}".format(exc))
            document = {}
        if not isinstance(document, dict):
            errors.append("alignment config must contain a JSON object")
            document = {}
        alignment_status = str((document.get("alignment") or {}).get("status", document.get("status", "")))
        top_level_status = str(document.get("status", ""))
        if top_level_status != expected_alignment_status:
            errors.append("bundle status is {!r}, expected {!r}".format(top_level_status, expected_alignment_status))
        if alignment_status != expected_alignment_status:
            errors.append("alignment status is {!r}, expected {!r}".format(alignment_status, expected_alignment_status))
        if str(document.get("mode", "")) != "cuvslam_global":
            errors.append("bundle mode must be cuvslam_global")
        if str(document.get("nav_map_id", "")) != bundle.nav_map_id:
            errors.append("nav_map_id mismatch")
        if str(document.get("vslam_map_id", "")) != bundle.vslam_map_id:
            errors.append("vslam_map_id mismatch")
        expected_nav_yaml_hash = str(document.get("nav_map_yaml_sha256", ""))
        expected_vslam_hash = str(document.get("vslam_map_sha256", ""))
        if not expected_nav_yaml_hash or expected_nav_yaml_hash != nav_map_yaml_hash:
            errors.append("nav_map_yaml SHA-256 mismatch")
        if not expected_vslam_hash or expected_vslam_hash != vslam_map_hash:
            errors.append("vslam_map SHA-256 mismatch")
        if str(document.get("extrinsics_sha256", "")) != extrinsics_hash:
            errors.append("extrinsics SHA-256 mismatch")
        if str(document.get("start_prior_sha256", "")) != start_prior_hash:
            errors.append("start_prior SHA-256 mismatch")
        nav_map_image = Path(str(document.get("nav_map_image", "")))
        if not nav_map_image.is_absolute():
            nav_map_image = Path(bundle.alignment_config).parent / nav_map_image
        if not str(document.get("nav_map_image", "")) or not nav_map_image.is_file():
            errors.append("nav_map_image does not exist: {}".format(nav_map_image))
        else:
            nav_map_image_hash = sha256_file(nav_map_image)
            expected_nav_image_hash = str(document.get("nav_map_image_sha256", ""))
            if not expected_nav_image_hash or expected_nav_image_hash != nav_map_image_hash:
                errors.append("nav_map_image SHA-256 mismatch")
        configured_nav_path = Path(str(document.get("nav_map_yaml", "")))
        configured_vslam_path = Path(str(document.get("vslam_map", "")))
        configured_extrinsics_path = Path(str(document.get("extrinsics_file", "")))
        configured_start_prior_path = Path(str(document.get("start_prior_file", "")))
        if not configured_nav_path.is_absolute():
            configured_nav_path = Path(bundle.alignment_config).parent / configured_nav_path
        if not configured_vslam_path.is_absolute():
            configured_vslam_path = Path(bundle.alignment_config).parent / configured_vslam_path
        if not configured_extrinsics_path.is_absolute():
            configured_extrinsics_path = Path(bundle.alignment_config).parent / configured_extrinsics_path
        if not configured_start_prior_path.is_absolute():
            configured_start_prior_path = Path(bundle.alignment_config).parent / configured_start_prior_path
        try:
            nav_paths_match = configured_nav_path.resolve() == Path(bundle.nav_map_yaml).resolve()
        except OSError:
            nav_paths_match = False
        try:
            vslam_paths_match = configured_vslam_path.resolve() == Path(bundle.vslam_map).resolve()
        except OSError:
            vslam_paths_match = False
        try:
            extrinsics_paths_match = configured_extrinsics_path.resolve() == Path(bundle.extrinsics_file).resolve()
        except OSError:
            extrinsics_paths_match = False
        try:
            start_prior_paths_match = configured_start_prior_path.resolve() == Path(bundle.start_prior_file).resolve()
        except OSError:
            start_prior_paths_match = False
        if not nav_paths_match:
            errors.append("nav_map_yaml path mismatch")
        if not vslam_paths_match:
            errors.append("vslam_map path mismatch")
        if not extrinsics_paths_match:
            errors.append("extrinsics path mismatch")
        if not start_prior_paths_match:
            errors.append("start_prior path mismatch")
        if Path(bundle.start_prior_file).is_file():
            try:
                start_prior = json.loads(Path(bundle.start_prior_file).read_text(encoding="utf-8"))
                if start_prior.get("frame_id") != "map":
                    errors.append("start_prior frame_id must be map")
                if start_prior.get("map_id") != bundle.nav_map_id:
                    errors.append("start_prior map_id mismatch")
                for name in ("x", "y", "yaw"):
                    if not math.isfinite(float(start_prior[name])):
                        errors.append("start_prior {} must be finite".format(name))
            except (AttributeError, KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
                errors.append("start_prior is invalid")
        if Path(bundle.extrinsics_file).is_file():
            try:
                extrinsics = json.loads(Path(bundle.extrinsics_file).read_text(encoding="utf-8"))
                translation = extrinsics["translation_m"]
                rotation = extrinsics["rotation_rpy_rad"]
                if extrinsics.get("parent_frame") != "base_link":
                    errors.append("extrinsics parent_frame must be base_link")
                if extrinsics.get("child_frame") != "camera_link":
                    errors.append("extrinsics child_frame must be camera_link")
                values = [translation[name] for name in ("x", "y", "z")]
                values += [rotation[name] for name in ("roll", "pitch", "yaw")]
                if not all(math.isfinite(float(value)) for value in values):
                    errors.append("extrinsics values must be finite")
            except (AttributeError, KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
                errors.append("extrinsics file is invalid")
    return {
        "ok": not errors,
        "errors": errors,
        "nav_map_yaml_sha256": nav_map_yaml_hash,
        "nav_map_image_sha256": nav_map_image_hash,
        "vslam_map_sha256": vslam_map_hash,
        "extrinsics_sha256": extrinsics_hash,
        "start_prior_sha256": start_prior_hash,
        "alignment_config_sha256": alignment_config_hash,
        "alignment_status": alignment_status,
    }


def _alignment_document(bundle):
    document = json.loads(Path(bundle.alignment_config).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("alignment config must contain a JSON object")
    return document


def _alignment_transform(bundle):
    alignment = _alignment_document(bundle).get("alignment") or {}
    try:
        values = (
            float(alignment["x"]),
            float(alignment["y"]),
            float(alignment["yaw"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("alignment transform is incomplete") from exc
    if not all(math.isfinite(value) for value in values):
        raise ValueError("alignment transform must be finite")
    return values


def nav_map_point_to_vslam_map(bundle, x, y):
    """Apply inverse(T_nav_map_vslam_map) to a Nav2-map point."""
    alignment_x, alignment_y, alignment_yaw = _alignment_transform(bundle)
    delta_x = float(x) - alignment_x
    delta_y = float(y) - alignment_y
    cosine = math.cos(alignment_yaw)
    sine = math.sin(alignment_yaw)
    return (
        cosine * delta_x + sine * delta_y,
        -sine * delta_x + cosine * delta_y,
    )


def vslam_map_pose_to_nav_map(bundle, x, y, yaw):
    """Apply T_nav_map_vslam_map to a localized pose from the action result."""
    alignment_x, alignment_y, alignment_yaw = _alignment_transform(bundle)
    cosine = math.cos(alignment_yaw)
    sine = math.sin(alignment_yaw)
    return (
        alignment_x + cosine * float(x) - sine * float(y),
        alignment_y + sine * float(x) + cosine * float(y),
        math.atan2(
            math.sin(alignment_yaw + float(yaw)),
            math.cos(alignment_yaw + float(yaw)),
        ),
    )


def save_map_goal(map_url):
    map_path = PurePosixPath(str(map_url))
    if not map_path.is_absolute():
        raise ValueError("save_map map_url must be an absolute container-local path")
    if ".." in map_path.parts:
        raise ValueError("save_map map_url must not contain parent traversal")
    return {
        "action_name": SAVE_ACTION_NAME,
        "action_type": SAVE_ACTION_TYPE,
        "goal": {"map_url": str(map_path)},
        "fail_closed": True,
    }


def load_map_and_localize_goal(bundle, prior):
    """Return the exact Isaac ROS 2.1 action goal after bundle validation.

    This installed action accepts only a translation in the saved cuVSLAM map
    frame.  The Nav2-map prior is therefore transformed before it is sent;
    yaw remains an explicit post-action validation requirement.
    """
    result = validate_bundle(bundle)
    if not result["ok"]:
        raise ValueError("map bundle rejected: {}".format("; ".join(result["errors"])))
    if prior.frame_id != "map":
        raise ValueError("localize_near_point prior must use Nav2 map frame")
    vslam_x, vslam_y = nav_map_point_to_vslam_map(bundle, prior.x, prior.y)
    return {
        "action_name": LOAD_ACTION_NAME,
        "action_type": LOAD_ACTION_TYPE,
        "goal": {
            "map_url": str(bundle.vslam_map),
            "localize_near_point": {"x": vslam_x, "y": vslam_y, "z": 0.0},
        },
        "expected_nav_map_prior": {
            "frame_id": prior.frame_id,
            "x": prior.x,
            "y": prior.y,
            "yaw": prior.yaw,
        },
        "nav_map_id": bundle.nav_map_id,
        "vslam_map_id": bundle.vslam_map_id,
        "expected_hashes": result,
        "fail_closed": True,
    }


def validate_localization_result(
    bundle,
    prior,
    *,
    action_success,
    localized_vslam_pose,
    max_xy_error_m=0.30,
    max_yaw_error_rad=math.radians(15.0),
):
    """Validate the returned saved-map pose before enabling global TF/Nav2."""
    bundle_result = validate_bundle(bundle)
    errors = list(bundle_result["errors"])
    if not action_success:
        errors.append("load_map_and_localize action reported failure")
    if prior.frame_id != "map":
        errors.append("localization prior frame must be map")
    try:
        localized = (
            float(localized_vslam_pose["x"]),
            float(localized_vslam_pose["y"]),
            float(localized_vslam_pose["yaw"]),
        )
        if not all(math.isfinite(value) for value in localized):
            raise ValueError("non-finite pose")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append("localized pose is invalid: {}".format(exc))
        localized = None
    nav_pose = None
    xy_error = None
    yaw_error = None
    if localized is not None and not errors:
        nav_pose = vslam_map_pose_to_nav_map(bundle, *localized)
        xy_error = math.hypot(nav_pose[0] - prior.x, nav_pose[1] - prior.y)
        yaw_error = abs(math.atan2(
            math.sin(nav_pose[2] - prior.yaw),
            math.cos(nav_pose[2] - prior.yaw),
        ))
        if xy_error > float(max_xy_error_m):
            errors.append("localized XY residual exceeds threshold")
        if yaw_error > float(max_yaw_error_rad):
            errors.append("localized yaw residual exceeds threshold")
    return {
        "ok": not errors,
        "errors": errors,
        "localized_nav_map_pose": (
            {"x": nav_pose[0], "y": nav_pose[1], "yaw": nav_pose[2]}
            if nav_pose is not None else None
        ),
        "xy_error_m": xy_error,
        "yaw_error_rad": yaw_error,
        "bundle": bundle_result,
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nav-map-id", required=True)
    parser.add_argument("--vslam-map-id", required=True)
    parser.add_argument("--nav-map-yaml", required=True, type=Path)
    parser.add_argument("--vslam-map", required=True, type=Path)
    parser.add_argument("--alignment-config", required=True, type=Path)
    parser.add_argument("--extrinsics-file", required=True, type=Path)
    parser.add_argument("--start-prior-file", required=True, type=Path)
    parser.add_argument("--prior-x", required=True, type=float)
    parser.add_argument("--prior-y", required=True, type=float)
    parser.add_argument("--prior-yaw", required=True, type=float)
    return parser.parse_args()


def main():
    args = parse_args()
    bundle = MapBundle(
        args.nav_map_id,
        args.vslam_map_id,
        args.nav_map_yaml,
        args.vslam_map,
        args.extrinsics_file,
        args.start_prior_file,
        args.alignment_config,
    )
    prior = LocalizationPrior(args.prior_x, args.prior_y, args.prior_yaw)
    print(json.dumps(load_map_and_localize_goal(bundle, prior), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
