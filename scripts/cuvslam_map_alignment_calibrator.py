#!/usr/bin/env python3
"""Fit and validate the fixed Nav2-map <- cuVSLAM-map SE(2) alignment."""

import argparse
import hashlib
import json
import math
from pathlib import Path

from nodes.navigation.global_pose_manager import fit_se2_alignment


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_path(path):
    """Hash a map file or directory deterministically, including filenames."""
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


def nav_map_image_path(nav_map_yaml):
    """Resolve the PGM referenced by a Nav2 map YAML.

    Nav2 map YAML is intentionally parsed with PyYAML when available.  The
    fallback handles the simple ``image: filename`` form used in this repo so
    the calibrator remains usable on a minimal Jetson Python installation.
    """
    path = Path(nav_map_yaml)
    if not path.is_file():
        return None
    document = None
    try:
        import yaml  # type: ignore
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (ImportError, ValueError):
        document = None
    image = document.get("image") if isinstance(document, dict) else None
    if not image:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("image:"):
                image = line.split(":", 1)[1].strip().strip("'\"")
                break
    if not image:
        return None
    image_path = Path(str(image))
    return image_path if image_path.is_absolute() else path.parent / image_path


def load_json_object(path):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("{} must contain a JSON object".format(path))
    return document


def extrinsics_are_valid(path):
    try:
        document = load_json_object(path)
        translation = document["translation_m"]
        rotation = document["rotation_rpy_rad"]
        values = [
            translation[axis] for axis in ("x", "y", "z")
        ] + [rotation[axis] for axis in ("roll", "pitch", "yaw")]
        return (
            document.get("parent_frame") == "base_link"
            and document.get("child_frame") == "camera_link"
            and all(math.isfinite(float(value)) for value in values)
        )
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
        return False


def start_prior_is_valid(path, nav_map_id):
    try:
        document = load_json_object(path)
        return (
            document.get("frame_id") == "map"
            and document.get("map_id") == nav_map_id
            and all(
                math.isfinite(float(document[name]))
                for name in ("x", "y", "yaw")
            )
        )
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
        return False


def load_points(path):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    points = document.get("control_points") if isinstance(document, dict) else document
    if not isinstance(points, list):
        raise ValueError("control_points must be a list")
    vslam, nav = [], []
    for index, point in enumerate(points):
        try:
            v = point["vslam_map"]
            n = point["nav_map"]
            vslam.append((float(v["x"]), float(v["y"])))
            nav.append((float(n["x"]), float(n["y"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid control point at index {}".format(index)) from exc
    return vslam, nav


def build_alignment_document(
    points_path,
    *,
    nav_map_yaml,
    nav_map_id,
    vslam_map,
    vslam_map_id,
    extrinsics_file,
    start_prior_file,
    max_residual_m=0.10,
    max_scale_error=0.05,
    yaw_hint=None,
):
    vslam_points, nav_points = load_points(points_path)
    result = fit_se2_alignment(vslam_points, nav_points, yaw_hint=yaw_hint)
    nav_path = Path(nav_map_yaml).resolve()
    vslam_path = Path(vslam_map).resolve()
    extrinsics_path = Path(extrinsics_file).resolve() if extrinsics_file else Path()
    start_prior_path = Path(start_prior_file).resolve() if start_prior_file else Path()
    nav_image = nav_map_image_path(nav_path)
    bundle_ready = bool(
        nav_map_id
        and vslam_map_id
        and nav_path.is_file()
        and nav_image is not None
        and nav_image.is_file()
        and nav_image.stat().st_size > 0
        and map_path_ready(vslam_path)
        and bool(extrinsics_file)
        and extrinsics_path.is_file()
        and extrinsics_are_valid(extrinsics_path)
        and bool(start_prior_file)
        and start_prior_path.is_file()
        and start_prior_is_valid(start_prior_path, nav_map_id)
    )
    complete = (
        result.point_count >= 2
        and result.max_residual <= float(max_residual_m)
        and abs(result.scale_ratio - 1.0) <= float(max_scale_error)
        and bundle_ready
    )
    return {
        "version": 1,
        "status": "complete" if complete else "pending",
        "mode": "legacy_static" if not complete else "cuvslam_global",
        "nav_map_frame": "map",
        "vslam_map_frame": "vslam_map",
        "odom_frame": "odom",
        "base_frame": "base_link",
        "nav_map_id": nav_map_id,
        "vslam_map_id": vslam_map_id,
        "nav_map_yaml": str(nav_path),
        "nav_map_yaml_sha256": sha256_file(nav_path) if nav_path.is_file() else "",
        "vslam_map": str(vslam_path),
        "nav_map_image": str(nav_image) if nav_image is not None else "",
        "nav_map_image_sha256": sha256_file(nav_image) if nav_image is not None and nav_image.is_file() else "",
        "vslam_map_sha256": sha256_path(vslam_path),
        "vslam_map_kind": "directory" if vslam_path.is_dir() else "file" if vslam_path.is_file() else "missing",
        "extrinsics_file": str(extrinsics_path) if extrinsics_file else "",
        "extrinsics_sha256": sha256_file(extrinsics_path) if extrinsics_path.is_file() else "",
        "start_prior_file": str(start_prior_path) if start_prior_file else "",
        "start_prior_sha256": sha256_file(start_prior_path) if start_prior_path.is_file() else "",
        "alignment": {
            "status": "complete" if complete else "pending",
            "x": result.transform.x,
            "y": result.transform.y,
            "yaw": result.transform.yaw,
            "control_points": result.point_count,
            "residuals_m": list(result.residuals),
            "max_residual_m": result.max_residual,
            "scale_ratio": result.scale_ratio,
            "max_scale_error": float(max_scale_error),
        },
        "production_gate": (
            "approved multi-point bundle"
            if complete
            else "pending: require >=2 control points, map/extrinsics/prior hashes, residual and scale thresholds"
        ),
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", required=True, help="JSON control-point file")
    parser.add_argument("--nav-map-yaml", required=True)
    parser.add_argument("--vslam-map", required=True)
    parser.add_argument("--nav-map-id", required=True)
    parser.add_argument("--vslam-map-id", required=True)
    parser.add_argument("--extrinsics-file", required=True)
    parser.add_argument("--start-prior-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-residual-m", type=float, default=0.10)
    parser.add_argument("--max-scale-error", type=float, default=0.05)
    parser.add_argument("--yaw-hint", type=float)
    return parser.parse_args()


def main():
    args = parse_args()
    document = build_alignment_document(
        args.points,
        nav_map_yaml=args.nav_map_yaml,
        nav_map_id=args.nav_map_id,
        vslam_map=args.vslam_map,
        vslam_map_id=args.vslam_map_id,
        extrinsics_file=args.extrinsics_file,
        start_prior_file=args.start_prior_file,
        max_residual_m=args.max_residual_m,
        max_scale_error=args.max_scale_error,
        yaw_hint=args.yaw_hint,
    )
    Path(args.output).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": document["status"],
        "control_points": document["alignment"]["control_points"],
        "max_residual_m": document["alignment"]["max_residual_m"],
        "output": str(Path(args.output).resolve()),
    }, sort_keys=True))
    return 0 if document["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
