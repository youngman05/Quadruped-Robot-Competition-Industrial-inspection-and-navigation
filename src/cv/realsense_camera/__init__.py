"""Intel RealSense D455 camera wrapper.

Main entry point:
    from cv.realsense_camera import RealsenseCamera

cuVSLAM usage:
    cam = RealsenseCamera.for_cuvslam()
    left_ir, right_ir = cam.get_infrared_frames()
    imu = cam.get_imu_data()

Gauge detection:
    cam = RealsenseCamera.for_gauge()
    color, _ = cam.get_frames()
"""

from .camera import CameraConfig, IMUSample, RealsenseCamera
from .filters import (
    PRESET_BALANCED,
    PRESET_LIGHT,
    PRESET_MAX,
    PRESET_NONE,
    apply_filters,
    create_filter_chain,
)

__all__ = [
    "CameraConfig",
    "IMUSample",
    "RealsenseCamera",
    # Filters
    "apply_filters",
    "create_filter_chain",
    "PRESET_BALANCED",
    "PRESET_LIGHT",
    "PRESET_MAX",
    "PRESET_NONE",
]
