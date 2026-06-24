#!/usr/bin/env python3
"""D455 live viewer — color + depth overlay. Press Q to quit."""

from __future__ import annotations

import cv2
import numpy as np

from cv.realsense_camera import RealsenseCamera


def main() -> None:
    with RealsenseCamera() as cam:
        print(f"D455 viewer — {cam.device_name} ({cam.serial})")
        print("Press Q in the window to quit.")

        while True:
            color, depth = cam.get_frames()
            if color is None:
                continue

            # Depth colormap (0~3m)
            depth_clipped = np.clip(depth, 0, 3000).astype(np.float32) if depth is not None else np.zeros_like(color[:, :, 0], dtype=np.float32)
            depth_jet = cv2.applyColorMap(
                cv2.convertScaleAbs(depth_clipped, alpha=255.0 / 3000),
                cv2.COLORMAP_JET,
            )

            # Overlay
            overlay = cv2.addWeighted(color, 0.5, depth_jet, 0.5, 0)

            # Center depth readout
            cx, cy = cam.width // 2, cam.height // 2
            center_d = cam.get_distance(cx, cy)
            cv2.putText(overlay, f"Center: {center_d:.3f}m",
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            # Show: Color | Depth | Overlay
            display = np.hstack((color, depth_jet, overlay))
            cv2.imshow("D455 [Q to quit]", display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break

    cv2.destroyAllWindows()
    print("Done.")


if __name__ == "__main__":
    main()
