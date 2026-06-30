"""ROS Image topic frame buffer."""

from __future__ import annotations

import threading
import time
from typing import List, Optional, Tuple

import cv2
import numpy as np
from sensor_msgs.msg import Image


class RosImageFrameBuffer:
    """Cache incoming ROS Image frames and wait for fresh frames on demand."""

    def __init__(self, node, image_topic: str, queue_size: int = 10) -> None:
        self._node = node
        self._condition = threading.Condition()
        self._frame = None
        self._sequence = 0
        self._subscription = node.create_subscription(
            Image,
            image_topic,
            self._on_image,
            int(queue_size),
        )

    def wait_for_frames(self, count: int, timeout_sec: float) -> List[np.ndarray]:
        frames: List[np.ndarray] = []
        deadline = time.monotonic() + float(timeout_sec)
        last_sequence = self._sequence

        while len(frames) < int(count):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            with self._condition:
                self._condition.wait_for(
                    lambda: self._sequence > last_sequence,
                    timeout=remaining,
                )
                if self._sequence <= last_sequence or self._frame is None:
                    continue
                frame = self._frame.copy()
                last_sequence = self._sequence

            frames.append(frame)

        if len(frames) < int(count):
            raise RuntimeError(
                f"Timed out waiting for {count} ROS image frames; got {len(frames)}"
            )
        return frames

    def _on_image(self, msg: Image) -> None:
        try:
            frame = self._decode_image(msg)
        except Exception as exc:  # noqa: BLE001
            self._node.get_logger().warn(f"Failed to decode image message: {exc}")
            return

        with self._condition:
            self._frame = frame
            self._sequence += 1
            self._condition.notify_all()

    def _decode_image(self, msg: Image) -> np.ndarray:
        data = np.frombuffer(msg.data, dtype=np.uint8)
        if msg.encoding in ("bgr8", "8UC3"):
            return data.reshape((msg.height, msg.width, 3)).copy()
        if msg.encoding == "rgb8":
            rgb = data.reshape((msg.height, msg.width, 3))
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        if msg.encoding in ("mono8", "8UC1"):
            mono = data.reshape((msg.height, msg.width))
            return cv2.cvtColor(mono, cv2.COLOR_GRAY2BGR)
        if msg.encoding == "bgra8":
            bgra = data.reshape((msg.height, msg.width, 4))
            return cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
        if msg.encoding == "rgba8":
            rgba = data.reshape((msg.height, msg.width, 4))
            return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)
        raise ValueError(f"Unsupported image encoding: {msg.encoding}")


class RosRgbdFrameBuffer:
    """Cache color and aligned depth frames, then return fresh RGB-D pairs."""

    def __init__(
        self,
        node,
        image_topic: str,
        depth_topic: str,
        queue_size: int = 10,
    ) -> None:
        self._node = node
        self._condition = threading.Condition()
        self._color_frame = None
        self._depth_frame = None
        self._color_sequence = 0
        self._depth_sequence = 0
        self._color_subscription = node.create_subscription(
            Image,
            image_topic,
            self._on_color,
            int(queue_size),
        )
        self._depth_subscription = node.create_subscription(
            Image,
            depth_topic,
            self._on_depth,
            int(queue_size),
        )

    def wait_for_frames(
        self,
        count: int,
        timeout_sec: float,
    ) -> List[Tuple[np.ndarray, Optional[np.ndarray]]]:
        frames: List[Tuple[np.ndarray, Optional[np.ndarray]]] = []
        deadline = time.monotonic() + float(timeout_sec)
        last_color_sequence = self._color_sequence

        while len(frames) < int(count):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            with self._condition:
                self._condition.wait_for(
                    lambda: self._color_sequence > last_color_sequence,
                    timeout=remaining,
                )
                if self._color_sequence <= last_color_sequence or self._color_frame is None:
                    continue
                color = self._color_frame.copy()
                depth = self._depth_frame.copy() if self._depth_frame is not None else None
                last_color_sequence = self._color_sequence

            frames.append((color, depth))

        if len(frames) < int(count):
            raise RuntimeError(
                f"Timed out waiting for {count} ROS RGB-D frames; got {len(frames)}"
            )
        return frames

    def _on_color(self, msg: Image) -> None:
        try:
            frame = RosImageFrameBuffer._decode_image(self, msg)
        except Exception as exc:  # noqa: BLE001
            self._node.get_logger().warn(f"Failed to decode color image message: {exc}")
            return

        with self._condition:
            self._color_frame = frame
            self._color_sequence += 1
            self._condition.notify_all()

    def _on_depth(self, msg: Image) -> None:
        try:
            frame = self._decode_depth(msg)
        except Exception as exc:  # noqa: BLE001
            self._node.get_logger().warn(f"Failed to decode depth image message: {exc}")
            return

        with self._condition:
            self._depth_frame = frame
            self._depth_sequence += 1
            self._condition.notify_all()

    def _decode_depth(self, msg: Image) -> np.ndarray:
        if msg.encoding in ("16UC1", "mono16"):
            depth = np.frombuffer(msg.data, dtype=np.uint16).reshape((msg.height, msg.width))
            return depth.astype(np.float32) * 0.001
        if msg.encoding == "32FC1":
            return np.frombuffer(msg.data, dtype=np.float32).reshape((msg.height, msg.width)).copy()
        raise ValueError(f"Unsupported depth encoding: {msg.encoding}")
