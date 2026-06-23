"""Post-processing filter presets for depth frames.

Typical usage:
    from cv.realsense_camera import RealsenseCamera, apply_filters

    with RealsenseCamera() as cam:
        raw_depth = cam.get_depth_frame_object()
        filtered = apply_filters(raw_depth, "smooth")
"""

from __future__ import annotations

from typing import Optional

import pyrealsense2 as rs

# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

#: Lightweight: spatial smoothing only. Low CPU, good for real-time.
PRESET_LIGHT = "light"

#: Balanced: spatial + temporal. Good quality with moderate CPU cost.
PRESET_BALANCED = "balanced"

#: Maximum quality: full filter chain (decimate → disparity → spatial →
#: temporal → disparity → hole fill). Higher latency.
PRESET_MAX = "max"

#: No filters: pass through raw depth.
PRESET_NONE = "none"

_PRESETS = {
    PRESET_LIGHT: {
        "spatial": {"magnitude": 2, "alpha": 0.5, "delta": 20, "holes_fill": 1},
    },
    PRESET_BALANCED: {
        "spatial": {"magnitude": 2, "alpha": 0.5, "delta": 20, "holes_fill": 1},
        "temporal": {"alpha": 0.4, "delta": 20, "persistence": 1},
    },
    PRESET_MAX: {
        "decimation": {"magnitude": 1},
        "spatial": {"magnitude": 2, "alpha": 0.5, "delta": 20, "holes_fill": 2},
        "temporal": {"alpha": 0.4, "delta": 20, "persistence": 1},
        "hole_filling": {"mode": 2},
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_filter_chain(
    preset: str = PRESET_BALANCED,
) -> list:
    """Build a list of pyrealsense2 filter objects from a named preset.

    Args:
        preset: One of 'light', 'balanced', 'max', 'none'.

    Returns:
        List of (name, filter_obj) tuples ready to be applied in sequence.
    """
    if preset == PRESET_NONE:
        return []

    cfg = _PRESETS.get(preset)
    if cfg is None:
        raise ValueError(
            f"Unknown preset '{preset}'. Choose from: "
            f"{', '.join(_PRESETS.keys())}"
        )

    chain: list = []

    # Decimation first (reduce resolution)
    if "decimation" in cfg:
        f = rs.decimation_filter()
        f.set_option(rs.option.filter_magnitude, cfg["decimation"]["magnitude"])
        chain.append(("decimation", f))
        # After decimation, switch to disparity domain for better spatial/temporal
        chain.append(("depth_to_disparity", rs.disparity_transform(True)))

    # Spatial
    if "spatial" in cfg:
        s = rs.spatial_filter()
        s.set_option(rs.option.filter_magnitude, cfg["spatial"]["magnitude"])
        s.set_option(rs.option.filter_smooth_alpha, cfg["spatial"]["alpha"])
        s.set_option(rs.option.filter_smooth_delta, cfg["spatial"]["delta"])
        s.set_option(rs.option.holes_fill, cfg["spatial"]["holes_fill"])
        chain.append(("spatial", s))

    # Temporal
    if "temporal" in cfg:
        t = rs.temporal_filter()
        t.set_option(rs.option.filter_smooth_alpha, cfg["temporal"]["alpha"])
        t.set_option(rs.option.filter_smooth_delta, cfg["temporal"]["delta"])
        if "persistence" in cfg["temporal"]:
            t.set_option(
                rs.option.holes_fill, cfg["temporal"]["persistence"]
            )
        chain.append(("temporal", t))

    # Back to depth domain
    if "decimation" in cfg:
        chain.append(("disparity_to_depth", rs.disparity_transform(False)))

    # Hole filling (last)
    if "hole_filling" in cfg:
        h = rs.hole_filling_filter()
        h.set_option(rs.option.holes_fill, cfg["hole_filling"]["mode"])
        chain.append(("hole_filling", h))

    return chain


def apply_filters(
    depth_frame: rs.depth_frame,
    preset: str = PRESET_BALANCED,
    chain: Optional[list] = None,
) -> rs.depth_frame:
    """Apply post-processing filters to a depth frame.

    Args:
        depth_frame: Raw depth frame from RealsenseCamera.get_depth_frame_object().
        preset: Name of a built-in preset ('light', 'balanced', 'max', 'none').
        chain: Optional pre-built filter chain from create_filter_chain().
               Takes precedence over preset.

    Returns:
        Filtered depth frame (or original if preset='none').

    Example:
        with RealsenseCamera() as cam:
            raw = cam.get_depth_frame_object()
            smooth = apply_filters(raw, "balanced")
            image = np.asanyarray(smooth.get_data())
    """
    if chain is None:
        chain = create_filter_chain(preset)

    result = depth_frame
    for _name, filt in chain:
        result = filt.process(result)
    return result
