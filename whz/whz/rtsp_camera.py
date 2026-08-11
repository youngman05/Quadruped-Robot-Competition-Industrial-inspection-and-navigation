"""Bounded GStreamer reader for the Lite3 front RTSP camera."""

from __future__ import annotations

import json
import os
import time
import warnings
from typing import List, Optional, Tuple

import numpy as np


DEFAULT_RTSP_URL = "rtsp://192.168.1.120:8554/test"
_JETSON_TLS_FIX = "/lib/aarch64-linux-gnu/libgomp.so.1"

_NVVDEC_PIPELINE = (
    "rtspsrc location={url} latency={latency} ! "
    "rtph264depay ! h264parse config-interval=1 ! "
    "nvv4l2decoder ! video/x-raw(memory:NVMM) ! "
    "nvvidconv ! video/x-raw,format=BGRx ! "
    "videoconvert ! video/x-raw,format=BGR ! "
    "appsink name=sink sync=false max-buffers=1 drop=true"
)

_AVDEC_PIPELINE = (
    "rtspsrc location={url} latency={latency} ! "
    "rtph264depay ! h264parse config-interval=1 ! avdec_h264 ! "
    "videoconvert ! video/x-raw,format=BGR ! "
    "appsink name=sink sync=false max-buffers=1 drop=true"
)


class RTSPCamera:
    """Read fresh BGR frames with connection, frame, and bus-error bounds."""

    def __init__(
        self,
        url: str = DEFAULT_RTSP_URL,
        connect_timeout_sec: float = 8.0,
        frame_timeout_sec: float = 2.0,
        prefer_hw_decode: bool = False,
        latency_ms: int = 100,
        gst_module=None,
    ) -> None:
        self.url = str(url)
        self.connect_timeout_sec = float(connect_timeout_sec)
        self.frame_timeout_sec = float(frame_timeout_sec)
        self.prefer_hw_decode = bool(prefer_hw_decode)
        self.latency_ms = int(latency_ms)
        self._pipeline = None
        self._sink = None
        self._bus = None
        self._width = 0
        self._height = 0
        self._last_frame_id = None
        self._sample_sequence = 0
        self._closed = False

        if os.path.exists(_JETSON_TLS_FIX) and _JETSON_TLS_FIX not in os.environ.get(
            "LD_PRELOAD", ""
        ):
            warnings.warn(
                "Jetson detected without libgomp preload; start the process with "
                "LD_PRELOAD=/lib/aarch64-linux-gnu/libgomp.so.1 if imports fail.",
                RuntimeWarning,
            )

        self._Gst = gst_module or self._init_gst()
        self._open()

    @staticmethod
    def _init_gst():
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        Gst.init(None)
        return Gst

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def shape(self) -> Tuple[int, int, int]:
        return self._height, self._width, 3

    def _open(self) -> None:
        templates = [_AVDEC_PIPELINE]
        if self.prefer_hw_decode:
            templates.insert(0, _NVVDEC_PIPELINE)

        errors = []
        for template in templates:
            try:
                self._start_pipeline(template)
                _, frame_id = self._read_packet(self.connect_timeout_sec)
                self._last_frame_id = frame_id
                return
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
                self._teardown_pipeline()

        raise RuntimeError("RTSP connection failed: %s" % " | ".join(errors))

    def _start_pipeline(self, template: str) -> None:
        pipeline_text = template.format(
            url=json.dumps(self.url),
            latency=max(0, self.latency_ms),
        )
        self._pipeline = self._Gst.parse_launch(pipeline_text)
        self._sink = self._pipeline.get_by_name("sink")
        if self._sink is None:
            raise RuntimeError("GStreamer pipeline has no appsink named 'sink'")
        self._bus = self._pipeline.get_bus()

        state_result = self._pipeline.set_state(self._Gst.State.PLAYING)
        if state_result == self._Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("GStreamer pipeline failed to enter PLAYING")

    def read(self, timeout_sec: Optional[float] = None) -> np.ndarray:
        """Return a sample newer than the previously returned sample."""
        if self._closed:
            raise RuntimeError("RTSP camera is closed")

        timeout = self.frame_timeout_sec if timeout_sec is None else float(timeout_sec)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                raise TimeoutError("Timed out waiting for a distinct RTSP frame")
            frame, frame_id = self._read_packet(remaining)
            if frame_id == self._last_frame_id:
                continue
            self._last_frame_id = frame_id
            return frame

    def read_frames(self, count: int, timeout_sec: Optional[float] = None) -> List[np.ndarray]:
        """Read ``count`` distinct stream samples, bounding every frame wait."""
        frame_count = int(count)
        if frame_count < 1:
            raise ValueError("count must be at least 1")
        return [self.read(timeout_sec=timeout_sec) for _ in range(frame_count)]

    def _read_packet(self, timeout_sec: float) -> Tuple[np.ndarray, object]:
        self._raise_bus_error()
        timeout_ns = max(1, int(float(timeout_sec) * self._Gst.SECOND))
        sample = self._sink.emit("try-pull-sample", timeout_ns)
        if sample is None:
            self._raise_bus_error()
            raise TimeoutError("Timed out waiting for an RTSP sample")

        caps = sample.get_caps()
        structure = caps.get_structure(0)
        width = int(structure.get_value("width"))
        height = int(structure.get_value("height"))
        if width <= 0 or height <= 0:
            raise RuntimeError("Invalid RTSP frame dimensions")

        buffer = sample.get_buffer()
        frame_id = self._frame_id(buffer)
        ok, info = buffer.map(self._Gst.MapFlags.READ)
        if not ok:
            raise RuntimeError("Failed to map GStreamer RTSP buffer")
        try:
            data = np.frombuffer(info.data, dtype=np.uint8)
            minimum_size = width * height * 3
            if data.size < minimum_size or data.size % height != 0:
                raise RuntimeError(
                    "Unexpected RTSP buffer size: got %d, need at least %d"
                    % (data.size, minimum_size)
                )
            row_stride = data.size // height
            if row_stride < width * 3:
                raise RuntimeError("RTSP row stride is smaller than the BGR row")
            frame = data.reshape((height, row_stride))[:, : width * 3]
            frame = frame.reshape((height, width, 3)).copy()
        finally:
            buffer.unmap(info)

        self._width = width
        self._height = height
        return frame, frame_id

    def _frame_id(self, buffer):
        clock_none = int(self._Gst.CLOCK_TIME_NONE)
        identifiers = []
        for name in ("pts", "dts", "offset"):
            value = int(getattr(buffer, name, clock_none))
            if value != clock_none:
                identifiers.append((name, value))
        if identifiers:
            return tuple(identifiers)

        self._sample_sequence += 1
        return ("sample", self._sample_sequence)

    def _raise_bus_error(self) -> None:
        if self._bus is None:
            return
        message = self._bus.timed_pop_filtered(
            0,
            self._Gst.MessageType.ERROR | self._Gst.MessageType.EOS,
        )
        if message is None:
            return
        if message.type == self._Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            detail = (debug or "").strip()
            raise RuntimeError("GStreamer error: %s%s" % (error, ": " + detail if detail else ""))
        raise RuntimeError("RTSP stream reached end-of-stream")

    def _teardown_pipeline(self) -> None:
        if self._pipeline is not None:
            try:
                self._pipeline.set_state(self._Gst.State.NULL)
            except Exception:  # noqa: BLE001
                pass
        self._pipeline = None
        self._sink = None
        self._bus = None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._teardown_pipeline()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass
