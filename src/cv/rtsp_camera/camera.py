"""Lite3 front wide-angle camera via RTSP + GStreamer.

Data flow:
    Lite3 前置广角相机 (130° FOV)
        ↓ CSI
    RK3588 运动主机 (192.168.1.120)
        ↓ RTSP H.264 @ 1280×720 30fps
    Jetson Xavier NX (192.168.1.111)
        ↓ GStreamer avdec_h264 → BGR
    numpy.ndarray (720, 1280, 3) uint8

Usage:
    from cv.rtsp_camera import RTSPCamera

    cam = RTSPCamera()
    frame = cam.read()          # blocking, returns (720, 1280, 3) BGR
    cam.close()

    # or as context manager
    with RTSPCamera() as cam:
        frame = cam.read()
"""

from __future__ import annotations

import os
import sys
import time
from typing import Optional, Tuple

import numpy as np

# Jetson L4T has a static TLS block bug: libgomp.so.1 fails to load in
# Python processes unless it is preloaded before the interpreter starts.
# We can't fix it at runtime, so we check and warn.
_JETSON_TLS_FIX = "/lib/aarch64-linux-gnu/libgomp.so.1"
if os.path.exists(_JETSON_TLS_FIX) and _JETSON_TLS_FIX not in os.environ.get("LD_PRELOAD", ""):
    import warnings
    warnings.warn(
        "Jetson detected but libgomp not preloaded. "
        "Run with: LD_PRELOAD=/lib/aarch64-linux-gnu/libgomp.so.1 python3 ..."
    )

# GStreamer is imported lazily in __init__ so the warning above fires first.

_NVVDEC_PIPELINE = (
    "rtspsrc location={url} latency=0 ! "
    "rtph264depay ! h264parse config-interval=1 ! "
    "nvv4l2decoder ! "
    "video/x-raw(memory:NVMM) ! nvvidconv ! video/x-raw,format=BGRx ! "
    "videoconvert ! video/x-raw,format=BGR ! "
    "appsink name=sink sync=false max-buffers=1 drop=true"
)

_AVDEC_PIPELINE = (
    "rtspsrc location={url} latency=0 ! "
    "rtph264depay ! h264parse ! avdec_h264 ! "
    "videoconvert ! video/x-raw,format=BGR ! "
    "appsink name=sink sync=false max-buffers=1 drop=true"
)


class RTSPCamera:
    """Pull frames from Lite3's built-in front camera via RTSP.

    Parameters
    ----------
    url : str
        RTSP stream URL. Default is the Lite3 motion host.
    prefer_hw : bool
        Try nvv4l2decoder hardware decode first (Jetson only).
        Falls back to avdec_h264 if it fails.
    """

    def __init__(
        self,
        url: str = "rtsp://192.168.1.120:8554/test",
        prefer_hw: bool = False,
    ):
        self._url = url
        self._pipeline = None
        self._sink = None
        self._width: int = 0
        self._height: int = 0
        Gi = self._init_gst()
        self._Gst = Gi.repository.Gst
        Gst = self._Gst

        # Build pipeline — try hardware first if requested
        if prefer_hw:
            pipe_str = _NVVDEC_PIPELINE.format(url=url)
            try:
                self._pipeline = Gst.parse_launch(pipe_str)
            except Exception:
                pipe_str = _AVDEC_PIPELINE.format(url=url)
                self._pipeline = Gst.parse_launch(pipe_str)
        else:
            pipe_str = _AVDEC_PIPELINE.format(url=url)
            self._pipeline = Gst.parse_launch(pipe_str)

        self._sink = self._pipeline.get_by_name("sink")
        self._pipeline.set_state(Gst.State.PLAYING)

        # Probe resolution from first frame
        self._probe()

    @staticmethod
    def _init_gst():
        """Lazy init GStreamer to allow warnings to print first."""
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        return gi

    def _probe(self):
        """Pull one sample to discover resolution, then reuse it as first frame."""
        sample = self._sink.emit("pull-sample")
        if sample is None:
            raise RuntimeError(f"RTSP stream returned no data: {self._url}")
        caps = sample.get_caps()
        struct = caps.get_structure(0)
        self._width = struct.get_value("width")
        self._height = struct.get_value("height")

    # -- public API -------------------------------------------------------

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def shape(self) -> Tuple[int, int, int]:
        return (self._height, self._width, 3)

    def read(self) -> np.ndarray:
        """Pull the next frame. Blocks until a frame is available.

        Returns
        -------
        frame : np.ndarray
            BGR image of shape (height, width, 3), dtype uint8.
        """
        sample = self._sink.emit("pull-sample")
        if sample is None:
            raise RuntimeError("RTSP stream ended unexpectedly")

        buf = sample.get_buffer()
        ok, info = buf.map(self._Gst.MapFlags.READ)
        if not ok:
            raise RuntimeError("Failed to map GStreamer buffer")

        frame = np.frombuffer(info.data, dtype=np.uint8).reshape(
            (self._height, self._width, 3)
        ).copy()  # copy: free GStreamer memory immediately

        buf.unmap(info)
        return frame

    def close(self) -> None:
        """Stop the pipeline and release resources."""
        if self._pipeline is not None:
            self._pipeline.set_state(self._Gst.State.NULL)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False

    def __del__(self):
        self.close()
