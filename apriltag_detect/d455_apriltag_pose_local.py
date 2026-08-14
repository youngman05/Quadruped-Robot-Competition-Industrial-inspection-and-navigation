#!/usr/bin/env python3
"""Run the production D455 AprilTag pose logic locally without ROS or UDP."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Iterable, Optional, Sequence

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_CORE = REPO_ROOT / "docker" / "d455_perception"
sys.path.insert(0, str(PRODUCTION_CORE))

from apriltag_pose_core import AprilTagPoseDetector, TagPose, quaternion_xyzw  # noqa: E402


DEFAULT_CAMERA_MATRIX = (617.0, 617.0, 320.0, 240.0)
DEFAULT_TAG_SIZE_M = 0.100
DEFAULT_TAG_IDS = (0, 1, 2, 3)
DEFAULT_MAX_REPROJECTION_ERROR_PX = 3.0
RELAY_FILE_NAME = "latest_color.jpg"


def camera_matrix(fx: float, fy: float, cx: float, cy: float) -> np.ndarray:
    return np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64)


def parse_csv_numbers(value: str, name: str) -> list[float]:
    try:
        result = [float(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("{} must be comma-separated numbers".format(name)) from exc
    if not result:
        raise argparse.ArgumentTypeError("{} cannot be empty".format(name))
    return result


def parse_ids(value: str) -> tuple[int, ...]:
    try:
        result = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("tag IDs must be comma-separated integers") from exc
    if not result or any(item < 0 for item in result):
        raise argparse.ArgumentTypeError("tag IDs must be non-negative and non-empty")
    return result


def pose_record(pose: TagPose) -> dict[str, object]:
    return {
        "tag_id": pose.tag_id,
        "position_m": list(pose.position_m),
        "orientation_xyzw": list(quaternion_xyzw(pose.rotation)),
        "reprojection_error_px": pose.reprojection_error_px,
    }


def print_poses(poses: Sequence[TagPose]) -> None:
    if not poses:
        print("no accepted AprilTags")
        return
    for pose in poses:
        x, y, z = pose.position_m
        distance = float(np.linalg.norm(pose.position_m))
        print(
            "tag_id={} optical_tvec=[{:+.4f}, {:+.4f}, {:+.4f}]m "
            "distance={:.4f}m reprojection_error={:.3f}px".format(
                pose.tag_id, x, y, z, distance, pose.reprojection_error_px
            )
        )


def annotate(
    image_bgr: np.ndarray,
    poses: Sequence[TagPose],
    intrinsic: np.ndarray,
    distortion: np.ndarray,
    tag_size_m: float,
) -> np.ndarray:
    output = image_bgr.copy()
    half = tag_size_m * 0.5
    axis_length = tag_size_m * 0.5
    overlay_points = np.array(
        [
            [0.0, -half, half],
            [0.0, half, half],
            [0.0, half, -half],
            [0.0, -half, -half],
            [0.0, 0.0, 0.0],
            [axis_length, 0.0, 0.0],
            [0.0, axis_length, 0.0],
            [0.0, 0.0, axis_length],
        ],
        dtype=np.float64,
    )
    for pose in poses:
        rvec, _ = cv2.Rodrigues(pose.rotation)
        points, _ = cv2.projectPoints(
            overlay_points, rvec, np.asarray(pose.position_m), intrinsic, distortion
        )
        points = np.rint(points.reshape(-1, 2)).astype(np.int32)
        corners = points[:4]
        axes = points[4:]
        cv2.polylines(output, [corners], True, (0, 255, 0), 2, cv2.LINE_AA)
        center = tuple(np.rint(corners.mean(axis=0)).astype(np.int32))
        cv2.circle(output, center, 4, (0, 255, 255), -1, cv2.LINE_AA)
        origin = tuple(axes[0])
        for endpoint, color in zip(axes[1:], ((0, 0, 255), (0, 255, 0), (255, 0, 0))):
            cv2.line(output, origin, tuple(endpoint), color, 2, cv2.LINE_AA)
        x, y, z = pose.position_m
        distance = float(np.linalg.norm(pose.position_m))
        label = "ID:{} X:{:+.3f} Y:{:+.3f} Z:{:.3f}m dist:{:.2f}m err:{:.2f}px".format(
            pose.tag_id, x, y, z, distance, pose.reprojection_error_px
        )
        label_origin = (int(corners[0, 0]), max(24, int(corners[0, 1]) - 10))
        cv2.putText(output, label, label_origin, cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(output, label, label_origin, cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 0), 1, cv2.LINE_AA)
    return output


def process_image(
    detector: AprilTagPoseDetector,
    image_bgr: np.ndarray,
    intrinsic: np.ndarray,
    distortion: np.ndarray,
    save_out: Optional[Path],
) -> list[TagPose]:
    poses = detector.detect(image_bgr, intrinsic, distortion)
    print_poses(poses)
    if save_out is not None:
        annotated = annotate(image_bgr, poses, intrinsic, distortion, detector.tag_size_m)
        if not cv2.imwrite(str(save_out), annotated):
            raise RuntimeError("failed to write {}".format(save_out))
        print("annotated image saved to {}".format(save_out))
    return poses


def run_static(args: argparse.Namespace, detector: AprilTagPoseDetector, intrinsic: np.ndarray, distortion: np.ndarray) -> int:
    image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if image is None:
        print("failed to read image: {}".format(args.image), file=sys.stderr)
        return 1
    process_image(detector, image, intrinsic, distortion, args.save_out)
    return 0


def run_relay(args: argparse.Namespace, detector: AprilTagPoseDetector, intrinsic: np.ndarray, distortion: np.ndarray) -> int:
    image_path = args.relay / RELAY_FILE_NAME
    last_mtime = None
    print("watching {} every {:.2f}s".format(image_path, args.interval))
    try:
        while True:
            if image_path.exists() and image_path.stat().st_mtime != last_mtime:
                last_mtime = image_path.stat().st_mtime
                image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
                if image is not None:
                    process_image(detector, image, intrinsic, distortion, args.save_out)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


def run_selftest(args: argparse.Namespace, detector: AprilTagPoseDetector, intrinsic: np.ndarray, distortion: np.ndarray) -> int:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    tag = cv2.aruco.generateImageMarker(dictionary, DEFAULT_TAG_IDS[0], 240)
    image = np.full((600, 800, 3), 255, dtype=np.uint8)
    image[180:420, 280:520] = cv2.cvtColor(tag, cv2.COLOR_GRAY2BGR)
    process_image(detector, image, intrinsic, distortion, args.save_out)
    return 0


def run_live(args: argparse.Namespace, detector: AprilTagPoseDetector) -> int:
    try:
        import pyrealsense2 as rs
    except ImportError:
        print("--live requires pyrealsense2", file=sys.stderr)
        return 2
    pipeline = rs.pipeline()
    config = rs.config()
    if args.serial:
        config.enable_device(args.serial)
    config.enable_stream(rs.stream.color, args.width, args.height, rs.format.bgr8, args.fps)
    profile = pipeline.start(config)
    try:
        color_profile = profile.get_stream(rs.stream.color).as_video_stream_profile()
        info = color_profile.get_intrinsics()
        intrinsic = camera_matrix(float(info.fx), float(info.fy), float(info.ppx), float(info.ppy))
        distortion = np.asarray(info.coeffs, dtype=np.float64)
        print("live K={} D={}".format(intrinsic.reshape(-1).tolist(), distortion.tolist()))
        while True:
            frame = pipeline.wait_for_frames().get_color_frame()
            if frame is None:
                continue
            image = np.asanyarray(frame.get_data())
            poses = detector.detect(image, intrinsic, distortion)
            print_poses(poses)
            display = annotate(image, poses, intrinsic, distortion, detector.tag_size_m)
            cv2.imshow("D455 AprilTag production pose logic", display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s"):
                stamp = time.strftime("%Y%m%d_%H%M%S")
                args.capture_dir.mkdir(parents=True, exist_ok=True)
                image_path = args.capture_dir / "apriltag_{}.png".format(stamp)
                json_path = args.capture_dir / "apriltag_{}.json".format(stamp)
                cv2.imwrite(str(image_path), display)
                json_path.write_text(json.dumps({"frame_id": "camera_color_optical_frame", "detections": [pose_record(pose) for pose in poses]}, indent=2) + "\n")
                print("saved {} and {}".format(image_path, json_path))
    finally:
        pipeline.stop()
        cv2.destroyAllWindows()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local D455 AprilTag production-pose checker")
    parser.add_argument("image", type=Path, nargs="?", help="single BGR image")
    parser.add_argument("--selftest", action="store_true", help="generate and detect tag36h11 ID 0")
    parser.add_argument("--relay", type=Path, metavar="DIR", help="watch DIR/latest_color.jpg")
    parser.add_argument("--interval", type=float, default=0.2, help="relay polling period in seconds")
    parser.add_argument("--live", action="store_true", help="run directly against a RealSense color stream")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--serial")
    parser.add_argument("--capture-dir", type=Path, default=Path("captures/apriltag_production"))
    parser.add_argument("--save-out", type=Path, help="save an annotated static or relay image")
    parser.add_argument("--tag-size", type=float, default=DEFAULT_TAG_SIZE_M, help="black square side in metres")
    parser.add_argument("--expected-ids", type=parse_ids, default=DEFAULT_TAG_IDS, help="accepted IDs, e.g. 0,1,2,3")
    parser.add_argument("--max-reproj-error", type=float, default=DEFAULT_MAX_REPROJECTION_ERROR_PX)
    parser.add_argument("--fx", type=float, default=DEFAULT_CAMERA_MATRIX[0])
    parser.add_argument("--fy", type=float, default=DEFAULT_CAMERA_MATRIX[1])
    parser.add_argument("--cx", type=float, default=DEFAULT_CAMERA_MATRIX[2])
    parser.add_argument("--cy", type=float, default=DEFAULT_CAMERA_MATRIX[3])
    parser.add_argument("--dist-coeffs", type=lambda value: parse_csv_numbers(value, "dist-coeffs"), default=[0.0] * 5, help="CameraInfo D, e.g. k1,k2,p1,p2,k3")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    modes = sum(bool(value) for value in (args.image, args.selftest, args.relay, args.live))
    if modes != 1:
        print("select exactly one input mode: IMAGE, --selftest, --relay, or --live", file=sys.stderr)
        return 2
    if args.tag_size <= 0.0 or args.max_reproj_error <= 0.0 or args.interval <= 0.0:
        print("tag size, reprojection threshold, and interval must be positive", file=sys.stderr)
        return 2
    detector = AprilTagPoseDetector(args.tag_size, args.expected_ids, args.max_reproj_error)
    if args.live:
        return run_live(args, detector)
    intrinsic = camera_matrix(args.fx, args.fy, args.cx, args.cy)
    distortion = np.asarray(args.dist_coeffs, dtype=np.float64)
    if args.selftest:
        return run_selftest(args, detector, intrinsic, distortion)
    if args.relay:
        return run_relay(args, detector, intrinsic, distortion)
    return run_static(args, detector, intrinsic, distortion)


if __name__ == "__main__":
    raise SystemExit(main())
