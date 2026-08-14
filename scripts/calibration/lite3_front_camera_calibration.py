#!/usr/bin/env python3
"""Calibrate the Lite3 front RTSP camera with a chessboard.

Use the same 1280x720 RTSP stream as the QR alignment node.  The default
model is OpenCV fisheye, appropriate for the Lite3's 130-degree front lens.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
import yaml

from cv.rtsp_camera import RTSPCamera


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-dir", type=Path, help="Interactively collect chessboard frames.")
    parser.add_argument("--images-dir", type=Path, help="Directory of collected PNG frames to solve.")
    parser.add_argument("--board-cols", type=int, default=9, help="Inner chessboard corners per row.")
    parser.add_argument("--board-rows", type=int, default=6, help="Inner chessboard corners per column.")
    parser.add_argument("--square-mm", type=float, default=25.0, help="Measured square edge length.")
    parser.add_argument("--rtsp-url", default="rtsp://192.168.1.120:8554/test")
    parser.add_argument("--model", choices=("fisheye", "pinhole"), default="fisheye")
    parser.add_argument("--output", type=Path, default=Path("configs/camera/lite3_front_calibration.yaml"))
    parser.add_argument("--update-qr-config", type=Path, help="Explicitly replace K/D/model in this QR config.")
    return parser.parse_args()


def detect_corners(gray, pattern):
    found, corners = cv2.findChessboardCorners(
        gray, pattern,
        cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE,
    )
    if not found:
        return None
    return cv2.cornerSubPix(
        gray, corners, (11, 11), (-1, -1),
        (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-4),
    )


def capture(args):
    output = args.capture_dir
    output.mkdir(parents=True, exist_ok=True)
    pattern = (args.board_cols, args.board_rows)
    count = len(list(output.glob("*.png")))
    with RTSPCamera(args.rtsp_url, prefer_hw=False) as camera:
        while True:
            frame = camera.read()
            corners = detect_corners(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), pattern)
            preview = frame.copy()
            cv2.drawChessboardCorners(preview, pattern, corners, corners is not None)
            cv2.putText(preview, "c: save  q: quit  saved: {}".format(count), (20, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.imshow("Lite3 front camera calibration", preview)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("c") and corners is not None:
                path = output / "frame_{:03d}.png".format(count)
                cv2.imwrite(str(path), frame)
                count += 1
                print("saved {}".format(path))
    cv2.destroyAllWindows()


def board_object_points(args):
    grid_x, grid_y = np.meshgrid(range(args.board_cols), range(args.board_rows))
    points = np.zeros((args.board_cols * args.board_rows, 3), dtype=np.float64)
    points[:, :2] = np.column_stack((grid_x.ravel(), grid_y.ravel())) * (args.square_mm / 1000.0)
    return points


def solve(args):
    pattern = (args.board_cols, args.board_rows)
    object_template = board_object_points(args)
    object_points, image_points, image_size = [], [], None
    paths = sorted(args.images_dir.glob("*.png")) + sorted(args.images_dir.glob("*.jpg"))
    for path in paths:
        image = cv2.imread(str(path))
        if image is None:
            continue
        size = (image.shape[1], image.shape[0])
        if image_size is None:
            image_size = size
        if size != image_size:
            raise ValueError("all calibration images must have one resolution")
        corners = detect_corners(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), pattern)
        if corners is not None:
            object_points.append(object_template.copy())
            image_points.append(corners.reshape(-1, 2))
    if image_size is None or len(image_points) < 15:
        raise ValueError("need at least 15 valid chessboard images; found {}".format(len(image_points)))

    if args.model == "fisheye":
        obj = [points.reshape(1, -1, 3) for points in object_points]
        img = [points.reshape(1, -1, 2) for points in image_points]
        matrix = np.eye(3, dtype=np.float64)
        distortion = np.zeros((4, 1), dtype=np.float64)
        rms, matrix, distortion, _rvecs, _tvecs = cv2.fisheye.calibrate(
            obj, img, image_size, matrix, distortion, None, None,
            cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC | cv2.fisheye.CALIB_CHECK_COND | cv2.fisheye.CALIB_FIX_SKEW,
            (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-7),
        )
    else:
        rms, matrix, distortion, _rvecs, _tvecs = cv2.calibrateCamera(
            object_points, image_points, image_size, None, None,
        )

    result = {
        "lite3_qr_pose_publisher": {
            "ros__parameters": {
                "calibration_configured": True,
                "camera_matrix": [float(value) for value in matrix.reshape(-1)],
                "distortion_coefficients": [float(value) for value in distortion.reshape(-1)],
                "distortion_model": args.model,
                "calibration_image_width": image_size[0],
                "calibration_image_height": image_size[1],
                "calibration_valid_images": len(image_points),
                "calibration_rms_px": float(rms),
            }
        }
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(result, sort_keys=False), encoding="utf-8")
    print("model={} images={} rms_px={:.4f}".format(args.model, len(image_points), rms))
    print("wrote {}".format(args.output))
    if args.update_qr_config:
        config = yaml.safe_load(args.update_qr_config.read_text(encoding="utf-8"))
        params = config["lite3_qr_pose_publisher"]["ros__parameters"]
        params.update(result["lite3_qr_pose_publisher"]["ros__parameters"])
        args.update_qr_config.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        print("updated {}".format(args.update_qr_config))


def main():
    args = parse_args()
    if bool(args.capture_dir) == bool(args.images_dir):
        raise SystemExit("select exactly one of --capture-dir or --images-dir")
    if args.capture_dir:
        capture(args)
    else:
        solve(args)


if __name__ == "__main__":
    main()
