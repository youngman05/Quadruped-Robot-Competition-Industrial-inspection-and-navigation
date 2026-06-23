"""Intel RealSense D455 camera wrapper.

Supports: RGB, Depth, Infrared stereo, IMU (BMI055 Accel + Gyro).

cuVSLAM-ready preset:
    cam = RealsenseCamera.for_cuvslam()
    while True:
        left_ir, right_ir = cam.get_infrared_frames()
        accel, gyro = cam.get_imu_data()

Gauge detection preset:
    cam = RealsenseCamera.for_gauge()
    color, _ = cam.get_frames()

Full preset (everything on):
    cam = RealsenseCamera(
        enable_color=True, enable_depth=True,
        enable_infrared=True, enable_imu=True,
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

import pyrealsense2 as rs


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class CameraConfig:
    """Stream configuration loaded from YAML."""

    width: int = 640
    height: int = 480
    fps: int = 30

    @classmethod
    def from_yaml(cls, path: Union[str, Path], section: str = "camera") -> "CameraConfig":
        """Load from a YAML config file (e.g. configs/camera/d455.yaml)."""
        import yaml

        path = Path(path)
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        cam = data[section]
        color = cam["color"]
        return cls(width=color["width"], height=color["height"], fps=color["fps"])


@dataclass
class IMUSample:
    """One IMU reading (BMI055)."""

    accel_x: float = 0.0  # m/s^2
    accel_y: float = 0.0
    accel_z: float = 0.0
    gyro_x: float = 0.0  # rad/s
    gyro_y: float = 0.0
    gyro_z: float = 0.0
    timestamp_ms: float = 0.0

    @property
    def accel(self) -> Tuple[float, float, float]:
        return (self.accel_x, self.accel_y, self.accel_z)

    @property
    def gyro(self) -> Tuple[float, float, float]:
        return (self.gyro_x, self.gyro_y, self.gyro_z)


# ---------------------------------------------------------------------------
# Main camera class
# ---------------------------------------------------------------------------


class RealsenseCamera:
    """Intel RealSense D455 camera with stereo IR + IMU support.

    Stream toggles (all default False except color and depth):

        enable_color / enable_depth / enable_infrared / enable_imu

    cuVSLAM-ready:
        RealsenseCamera(
            enable_color=False, enable_depth=False,
            enable_infrared=True, enable_imu=True,
            projector_on=False,
        )

    Gauge detection:
        RealsenseCamera(
            enable_color=True, enable_depth=False,
            enable_infrared=False, enable_imu=False,
        )

    Everything:
        RealsenseCamera(
            enable_color=True, enable_depth=True,
            enable_infrared=True, enable_imu=True,
        )
    """

    # -- IMU rates supported by D455 BMI055 --------------------------------
    VALID_ACCEL_RATES = (100, 200, 400)
    VALID_GYRO_RATES = (200, 400)

    # ------------------------------------------------------------------
    # Factory presets
    # ------------------------------------------------------------------

    @classmethod
    def for_cuvslam(
        cls,
        width: int = 640,
        height: int = 480,
        accel_rate: int = 200,
        gyro_rate: int = 200,
    ) -> "RealsenseCamera":
        """Create a camera configured for cuVSLAM.

        Enables infrared stereo + IMU, disables color/depth/projector.
        """
        return cls(
            width=width, height=height,
            enable_color=False, enable_depth=False,
            enable_infrared=True, enable_imu=True,
            imu_accel_rate=accel_rate, imu_gyro_rate=gyro_rate,
            projector_on=False,
        )

    @classmethod
    def for_gauge(
        cls,
        width: int = 640,
        height: int = 480,
    ) -> "RealsenseCamera":
        """Create a camera configured for gauge detection (color only)."""
        return cls(
            width=width, height=height,
            enable_color=True, enable_depth=False,
            enable_infrared=False, enable_imu=False,
        )

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        *,
        # Stream toggles
        enable_color: bool = True,
        enable_depth: bool = True,
        enable_infrared: bool = False,
        enable_imu: bool = False,
        # Depth
        align_depth: bool = True,
        # IMU
        imu_accel_rate: int = 200,
        imu_gyro_rate: int = 200,
        # Projector
        projector_on: bool = True,
        # Config object
        config: Optional[CameraConfig] = None,
    ) -> None:
        if config is not None:
            width, height, fps = config.width, config.height, config.fps

        self._width = width
        self._height = height
        self._fps = fps

        # Stream toggles
        self._enable_color = enable_color
        self._enable_depth = enable_depth
        self._enable_infrared = enable_infrared
        self._enable_imu = enable_imu
        self._align_depth = align_depth and enable_depth
        self._projector_on = projector_on

        # IMU rates
        if imu_accel_rate not in self.VALID_ACCEL_RATES:
            raise ValueError(
                f"accel_rate must be one of {self.VALID_ACCEL_RATES}, got {imu_accel_rate}"
            )
        if imu_gyro_rate not in self.VALID_GYRO_RATES:
            raise ValueError(
                f"gyro_rate must be one of {self.VALID_GYRO_RATES}, got {imu_gyro_rate}"
            )
        self._imu_accel_rate = imu_accel_rate
        self._imu_gyro_rate = imu_gyro_rate

        # Internal state
        self._pipeline: Optional[rs.pipeline] = None
        self._align: Optional[rs.align] = None
        self._profile: Optional[rs.pipeline_profile] = None
        self._device_name: str = ""
        self._serial: str = ""

        # Cached intrinsics
        self._color_intrinsics: Optional[rs.intrinsics] = None
        self._depth_intrinsics: Optional[rs.intrinsics] = None
        self._infrared_intrinsics: Optional[rs.intrinsics] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, warmup_frames: int = 30) -> None:
        """Start the camera pipeline.

        Args:
            warmup_frames: Frames to discard while auto-exposure settles.
        """
        if self._pipeline is not None:
            return

        self._pipeline = rs.pipeline()
        cfg = rs.config()

        # --- Color stream ---
        if self._enable_color:
            cfg.enable_stream(
                rs.stream.color,
                self._width, self._height, rs.format.bgr8, self._fps,
            )

        # --- Depth stream ---
        if self._enable_depth:
            cfg.enable_stream(
                rs.stream.depth,
                self._width, self._height, rs.format.z16, self._fps,
            )

        # --- Infrared stereo streams (for cuVSLAM) ---
        if self._enable_infrared:
            cfg.enable_stream(
                rs.stream.infrared, 1,
                self._width, self._height, rs.format.y8, self._fps,
            )
            cfg.enable_stream(
                rs.stream.infrared, 2,
                self._width, self._height, rs.format.y8, self._fps,
            )

        # --- IMU streams (BMI055 Accel + Gyro) ---
        if self._enable_imu:
            cfg.enable_stream(
                rs.stream.accel,
                rs.format.motion_xyz32f, self._imu_accel_rate,
            )
            cfg.enable_stream(
                rs.stream.gyro,
                rs.format.motion_xyz32f, self._imu_gyro_rate,
            )

        self._profile = self._pipeline.start(cfg)

        # --- Post-start setup ---

        # Aligner
        if self._align_depth:
            self._align = rs.align(rs.stream.color)

        # Projector
        self._apply_projector()

        # Device info
        device = self._profile.get_device()
        self._device_name = device.get_info(rs.camera_info.name)
        self._serial = device.get_info(rs.camera_info.serial_number)

        # Warmup
        for _ in range(warmup_frames):
            self._pipeline.wait_for_frames(5000)

    def stop(self) -> None:
        """Stop the camera pipeline."""
        if self._pipeline is not None:
            try:
                self._pipeline.stop()
            except Exception:
                pass
            self._pipeline = None
            self._align = None
            self._profile = None

    def __enter__(self) -> "RealsenseCamera":
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def device_name(self) -> str:
        return self._device_name

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def is_running(self) -> bool:
        return self._pipeline is not None

    @property
    def has_imu(self) -> bool:
        return self._enable_imu

    @property
    def has_infrared(self) -> bool:
        return self._enable_infrared

    # ------------------------------------------------------------------
    # Projector control
    # ------------------------------------------------------------------

    @property
    def projector_on(self) -> bool:
        """Is the IR projector (emitter) currently on?"""
        return self._projector_on

    @projector_on.setter
    def projector_on(self, value: bool) -> None:
        self._projector_on = value
        if self._pipeline is not None:
            self._apply_projector()

    def _apply_projector(self) -> None:
        """Write projector setting to the device."""
        if self._profile is None:
            return
        device = self._profile.get_device()
        sensor = device.first_depth_sensor()
        if sensor.supports(rs.option.emitter_enabled):
            sensor.set_option(rs.option.emitter_enabled, 1 if self._projector_on else 0)

    def set_projector(self, on: bool) -> None:
        """Enable or disable the IR projector.

        cuVSLAM requires projector OFF for clean stereo IR images.
        """
        self.projector_on = on

    # ------------------------------------------------------------------
    # Intrinsics
    # ------------------------------------------------------------------

    @property
    def color_intrinsics(self) -> rs.intrinsics:
        if self._color_intrinsics is not None:
            return self._color_intrinsics
        if self._profile is None:
            raise RuntimeError("Camera not started")
        stream = self._profile.get_stream(rs.stream.color)
        self._color_intrinsics = stream.as_video_stream_profile().intrinsics
        return self._color_intrinsics

    @property
    def depth_intrinsics(self) -> rs.intrinsics:
        if self._align_depth:
            return self.color_intrinsics
        if self._depth_intrinsics is not None:
            return self._depth_intrinsics
        if self._profile is None:
            raise RuntimeError("Camera not started")
        stream = self._profile.get_stream(rs.stream.depth)
        self._depth_intrinsics = stream.as_video_stream_profile().intrinsics
        return self._depth_intrinsics

    @property
    def infrared_intrinsics(self) -> rs.intrinsics:
        """Intrinsics of the left infrared camera (infra1).

        cuVSLAM uses this for stereo projection.
        """
        if self._infrared_intrinsics is not None:
            return self._infrared_intrinsics
        if self._profile is None:
            raise RuntimeError("Camera not started")
        stream = self._profile.get_stream(rs.stream.infrared, 1)
        self._infrared_intrinsics = stream.as_video_stream_profile().intrinsics
        return self._infrared_intrinsics

    def intrinsics_dict(self) -> Dict[str, Any]:
        """Return color intrinsics as a plain dict for serialization."""
        i = self.color_intrinsics
        return {
            "width": i.width, "height": i.height,
            "fx": i.fx, "fy": i.fy,
            "ppx": i.ppx, "ppy": i.ppy,
            "model": str(i.model), "coeffs": list(i.coeffs),
        }

    def cuvslam_intrinsics(self) -> Dict[str, Any]:
        """Return infrared stereo intrinsics for cuVSLAM config.

        Returns a dict with left camera intrinsics and baseline info
        that cuVSLAM's camera_info expects.
        """
        il = self.infrared_intrinsics
        if self._profile is None:
            raise RuntimeError("Camera not started")
        # Get stereo extrinsics (right relative to left)
        left_stream = self._profile.get_stream(rs.stream.infrared, 1)
        right_stream = self._profile.get_stream(rs.stream.infrared, 2)
        extrinsics = left_stream.get_extrinsics_to(right_stream)
        baseline = abs(extrinsics.translation[0])  # meters, horizontal baseline

        return {
            "width": il.width, "height": il.height,
            "fx": il.fx, "fy": il.fy,
            "ppx": il.ppx, "ppy": il.ppy,
            "model": str(il.model), "coeffs": list(il.coeffs),
            "baseline_m": baseline,
        }

    # ------------------------------------------------------------------
    # Frame acquisition — color + depth
    # ------------------------------------------------------------------

    def wait_for_frames(self, timeout_ms: int = 5000) -> rs.composite_frame:
        """Return raw frameset from the pipeline."""
        if self._pipeline is None:
            raise RuntimeError("Camera not started. Call start() first.")
        return self._pipeline.wait_for_frames(timeout_ms)

    def get_frames(
        self, timeout_ms: int = 5000
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """Get aligned color + depth images.

        Returns:
            (color, depth). color: (H,W,3) uint8 BGR. depth: (H,W) uint16 mm.
        """
        frames = self.wait_for_frames(timeout_ms)

        if self._align is not None:
            frames = self._align.process(frames)

        color_frame = frames.get_color_frame()
        if not color_frame:
            raise RuntimeError("No color frame received")

        color_img = np.asanyarray(color_frame.get_data())
        depth_img: Optional[np.ndarray] = None
        if self._enable_depth:
            df = frames.get_depth_frame()
            if df:
                depth_img = np.asanyarray(df.get_data())

        return color_img, depth_img

    def get_color_image(self, timeout_ms: int = 5000) -> np.ndarray:
        color, _ = self.get_frames(timeout_ms)
        return color

    def get_depth_image(self, timeout_ms: int = 5000) -> Optional[np.ndarray]:
        _, depth = self.get_frames(timeout_ms)
        return depth

    # ------------------------------------------------------------------
    # Frame acquisition — Infrared stereo (cuVSLAM input)
    # ------------------------------------------------------------------

    def get_infrared_frames(
        self, timeout_ms: int = 5000
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Get left (infra1) and right (infra2) infrared images.

        These are the primary input for cuVSLAM stereo tracking.

        Returns:
            (left_ir, right_ir). Both (H,W) uint8 grayscale.
        """
        frames = self.wait_for_frames(timeout_ms)

        left_frame = frames.get_infrared_frame(1)
        right_frame = frames.get_infrared_frame(2)

        if left_frame is None or right_frame is None:
            raise RuntimeError("Infrared frames not available. Did you set enable_infrared=True?")

        left_img = np.asanyarray(left_frame.get_data())
        right_img = np.asanyarray(right_frame.get_data())
        return left_img, right_img

    # ------------------------------------------------------------------
    # IMU (BMI055 Accel + Gyro)
    # ------------------------------------------------------------------

    def get_imu_data(self, timeout_ms: int = 5000) -> IMUSample:
        """Read one combined accel + gyro sample.

        Blocks until both accel and gyro frames are available.

        Returns:
            IMUSample with accel (m/s^2) and gyro (rad/s).
        """
        frames = self.wait_for_frames(timeout_ms)

        accel_frame = frames.first_or_default(rs.stream.accel)
        gyro_frame = frames.first_or_default(rs.stream.gyro)

        if accel_frame is None or gyro_frame is None:
            raise RuntimeError("IMU frames not available. Did you set enable_imu=True?")

        a = accel_frame.as_motion_frame().get_motion_data()
        g = gyro_frame.as_motion_frame().get_motion_data()

        return IMUSample(
            accel_x=a.x, accel_y=a.y, accel_z=a.z,
            gyro_x=g.x, gyro_y=g.y, gyro_z=g.z,
            timestamp_ms=accel_frame.get_timestamp(),
        )

    def get_imu_samples(
        self, count: int, timeout_ms: int = 5000
    ) -> List[IMUSample]:
        """Collect multiple IMU samples.

        Example — read 1 second of data at 200 Hz:
            samples = cam.get_imu_samples(200)
            # Access as numpy arrays:
            accel_z = np.array([s.accel_z for s in samples])
        """
        samples: List[IMUSample] = []
        for _ in range(count):
            samples.append(self.get_imu_data(timeout_ms))
        return samples

    def get_imu_batch(
        self, duration_sec: float = 0.1, timeout_ms: int = 5000
    ) -> List[IMUSample]:
        """Collect IMU samples for a given duration.

        Args:
            duration_sec: How long to collect for.
        """
        import time
        samples: List[IMUSample] = []
        t0 = time.monotonic()
        while time.monotonic() - t0 < duration_sec:
            samples.append(self.get_imu_data(timeout_ms))
        return samples

    # ------------------------------------------------------------------
    # Depth queries (single point + batch)
    # ------------------------------------------------------------------

    def get_distance(self, x: int, y: int, timeout_ms: int = 5000) -> float:
        frames = self.wait_for_frames(timeout_ms)
        if self._align is not None:
            frames = self._align.process(frames)
        df = frames.get_depth_frame()
        if df is None:
            return 0.0
        return float(df.get_distance(x, y))

    def deproject(
        self, x: int, y: int, timeout_ms: int = 5000
    ) -> Tuple[float, float, float]:
        frames = self.wait_for_frames(timeout_ms)
        if self._align is not None:
            frames = self._align.process(frames)
        df = frames.get_depth_frame()
        if df is None:
            return (0.0, 0.0, 0.0)
        d = df.get_distance(x, y)
        if d <= 0:
            return (0.0, 0.0, 0.0)
        pt = rs.rs2_deproject_pixel_to_point(self.depth_intrinsics, [x, y], d)
        return (pt[0], pt[1], pt[2])

    def deproject_points(
        self, pixels: np.ndarray, timeout_ms: int = 5000
    ) -> np.ndarray:
        frames = self.wait_for_frames(timeout_ms)
        if self._align is not None:
            frames = self._align.process(frames)
        df = frames.get_depth_frame()
        if df is None:
            return np.zeros((len(pixels), 3), dtype=np.float32)
        intrin = self.depth_intrinsics
        points = np.zeros((len(pixels), 3), dtype=np.float32)
        for i, (x, y) in enumerate(pixels):
            d = df.get_distance(int(x), int(y))
            if d > 0:
                pt = rs.rs2_deproject_pixel_to_point(intrin, [int(x), int(y)], d)
                points[i] = pt
        return points

    def get_depth_frame_object(self, timeout_ms: int = 5000) -> Optional[rs.depth_frame]:
        frames = self.wait_for_frames(timeout_ms)
        if self._align is not None:
            frames = self._align.process(frames)
        return frames.get_depth_frame()
