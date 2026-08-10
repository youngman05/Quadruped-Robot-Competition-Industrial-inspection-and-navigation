"""Pure helpers for field waypoint calibration and route configuration."""

import json
import math
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path


CONFIG_VERSION = 1
WAYPOINT_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")

DEFAULT_CALIBRATION_ORDER = (
    "start",
    "obstacle_cross_target",
    "pos1_left_clear",
    "pos1_middle",
    "pos2a_upper_right",
    "upper_corner_clear",
    "pos1_middle_turned",
    "lower_corner_clear",
    "pos2b_lower_right",
    "grab_area_approach",
    "placement_A_approach",
    "placement_B_approach",
    "placement_C_approach",
    "placement_D_approach",
)

DEFAULT_INSPECTION_ROUTE = (
    "obstacle_cross_target",
    "pos1_left_clear",
    "pos1_middle",
    "upper_corner_clear",
    "pos2a_upper_right",
    "upper_corner_clear",
    "pos1_middle_turned",
    "lower_corner_clear",
    "pos2b_lower_right",
)

DEFAULT_FULL_ROUTE = DEFAULT_INSPECTION_ROUTE + (
    "grab_area_approach",
    "placement_A_approach",
    "placement_B_approach",
    "placement_C_approach",
    "placement_D_approach",
)

DEFAULT_ACTIONS = {
    "pos1_middle": "observe_upper_gauge",
    "pos2a_upper_right": "observe_upper_side",
    "pos1_middle_turned": "observe_lower_gauge",
    "pos2b_lower_right": "observe_lower_side",
    "grab_area_approach": "grab",
    "placement_A_approach": "place_A",
    "placement_B_approach": "place_B",
    "placement_C_approach": "place_C",
    "placement_D_approach": "place_D",
}


class WaypointCalibrationError(ValueError):
    """Raised when calibration data or a waypoint document is invalid."""


def normalize_angle(value):
    return math.atan2(math.sin(value), math.cos(value))


def utc_timestamp():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def validate_waypoint_name(name):
    if not isinstance(name, str) or not WAYPOINT_NAME_PATTERN.fullmatch(name):
        raise WaypointCalibrationError(
            "waypoint names must match %s" % WAYPOINT_NAME_PATTERN.pattern
        )
    return name


def estimate_stable_pose(
    samples,
    min_samples=20,
    max_xy_deviation=0.04,
    max_yaw_deviation=0.06,
):
    """Estimate a stable planar pose from a stationary TF sample window."""
    if len(samples) < min_samples:
        raise WaypointCalibrationError(
            "only %d valid samples; need at least %d" % (len(samples), min_samples)
        )

    normalized = []
    for sample in samples:
        try:
            x = float(sample["x"])
            y = float(sample["y"])
            yaw = float(sample["yaw"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WaypointCalibrationError("sample is missing finite x/y/yaw") from exc
        if not all(math.isfinite(value) for value in (x, y, yaw)):
            raise WaypointCalibrationError("sample contains non-finite x/y/yaw")
        normalized.append((x, y, normalize_angle(yaw)))

    x_center = statistics.median(item[0] for item in normalized)
    y_center = statistics.median(item[1] for item in normalized)
    sin_mean = sum(math.sin(item[2]) for item in normalized) / len(normalized)
    cos_mean = sum(math.cos(item[2]) for item in normalized) / len(normalized)
    if math.hypot(sin_mean, cos_mean) < 1e-6:
        raise WaypointCalibrationError("yaw samples do not have a stable circular mean")
    yaw_center = math.atan2(sin_mean, cos_mean)

    xy_deviation = max(
        math.hypot(item[0] - x_center, item[1] - y_center)
        for item in normalized
    )
    yaw_deviation = max(
        abs(normalize_angle(item[2] - yaw_center)) for item in normalized
    )
    if xy_deviation > max_xy_deviation:
        raise WaypointCalibrationError(
            "XY is unstable: %.4fm exceeds %.4fm"
            % (xy_deviation, max_xy_deviation)
        )
    if yaw_deviation > max_yaw_deviation:
        raise WaypointCalibrationError(
            "yaw is unstable: %.4frad exceeds %.4frad"
            % (yaw_deviation, max_yaw_deviation)
        )

    return {
        "x": x_center,
        "y": y_center,
        "yaw": yaw_center,
        "yaw_deg": math.degrees(yaw_center),
        "sample_count": len(normalized),
        "max_xy_deviation": xy_deviation,
        "max_yaw_deviation": yaw_deviation,
        "max_yaw_deviation_deg": math.degrees(yaw_deviation),
    }


def new_waypoint_document(frame_id="map", map_id=""):
    return {
        "version": CONFIG_VERSION,
        "frame_id": frame_id,
        "map_id": map_id,
        "calibration": {
            "status": "in_progress",
            "updated_at": utc_timestamp(),
        },
        "waypoints": {},
        "routes": {
            "inspection_interleaved": list(DEFAULT_INSPECTION_ROUTE),
            "full_interleaved": list(DEFAULT_FULL_ROUTE),
        },
    }


def _load_structured_text(text, path):
    try:
        return json.loads(text)
    except json.JSONDecodeError as json_error:
        try:
            import yaml
        except ImportError as exc:
            raise WaypointCalibrationError(
                "%s is not JSON-compatible YAML and PyYAML is unavailable: %s"
                % (path, json_error)
            ) from exc
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise WaypointCalibrationError("invalid waypoint YAML: %s" % exc) from exc


def validate_document(document):
    if not isinstance(document, dict):
        raise WaypointCalibrationError("waypoint document must be an object")
    if document.get("version") != CONFIG_VERSION:
        raise WaypointCalibrationError(
            "unsupported waypoint document version: %r" % document.get("version")
        )
    frame_id = document.get("frame_id")
    if not isinstance(frame_id, str) or not frame_id.strip():
        raise WaypointCalibrationError("frame_id must be a non-empty string")
    if not isinstance(document.get("waypoints"), dict):
        raise WaypointCalibrationError("waypoints must be an object")
    if not isinstance(document.get("routes"), dict):
        raise WaypointCalibrationError("routes must be an object")
    for name in document["waypoints"]:
        validate_waypoint_name(name)
    for route_name, names in document["routes"].items():
        validate_waypoint_name(route_name)
        if not isinstance(names, list) or not names:
            raise WaypointCalibrationError(
                "route %s must be a non-empty waypoint-name list" % route_name
            )
        for name in names:
            validate_waypoint_name(name)
    return document


def load_waypoint_document(path):
    path = Path(path).expanduser()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise WaypointCalibrationError("cannot read %s: %s" % (path, exc)) from exc
    return validate_document(_load_structured_text(text, path))


def write_waypoint_document(path, document):
    path = Path(path).expanduser()
    validate_document(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def upsert_waypoint(document, name, estimate, action=None, captured_at=None):
    validate_document(document)
    validate_waypoint_name(name)
    required = (
        "x",
        "y",
        "yaw",
        "yaw_deg",
        "sample_count",
        "max_xy_deviation",
        "max_yaw_deviation",
        "max_yaw_deviation_deg",
    )
    if not all(key in estimate for key in required):
        raise WaypointCalibrationError("estimate is missing required stability fields")
    waypoint = {
        "x": float(estimate["x"]),
        "y": float(estimate["y"]),
        "yaw": float(estimate["yaw"]),
        "yaw_deg": float(estimate["yaw_deg"]),
        "action": action or DEFAULT_ACTIONS.get(name, "transit"),
        "captured_at": captured_at or utc_timestamp(),
        "sample_count": int(estimate["sample_count"]),
        "stability": {
            "max_xy_deviation": float(estimate["max_xy_deviation"]),
            "max_yaw_deviation": float(estimate["max_yaw_deviation"]),
            "max_yaw_deviation_deg": float(estimate["max_yaw_deviation_deg"]),
        },
    }
    document["waypoints"][name] = waypoint
    calibration = document.setdefault("calibration", {})
    calibration["status"] = "in_progress"
    calibration["updated_at"] = utc_timestamp()
    return waypoint


def waypoint_pose(waypoint, name):
    if not isinstance(waypoint, dict):
        raise WaypointCalibrationError("waypoint %s must be an object" % name)
    try:
        x = float(waypoint["x"])
        y = float(waypoint["y"])
    except (KeyError, TypeError, ValueError) as exc:
        raise WaypointCalibrationError("waypoint %s needs numeric x/y" % name) from exc

    has_yaw = "yaw" in waypoint
    has_yaw_deg = "yaw_deg" in waypoint
    if not has_yaw and not has_yaw_deg:
        raise WaypointCalibrationError("waypoint %s needs yaw or yaw_deg" % name)
    try:
        yaw = float(waypoint["yaw"]) if has_yaw else math.radians(float(waypoint["yaw_deg"]))
    except (TypeError, ValueError) as exc:
        raise WaypointCalibrationError("waypoint %s has invalid yaw" % name) from exc
    if not all(math.isfinite(value) for value in (x, y, yaw)):
        raise WaypointCalibrationError("waypoint %s has non-finite pose" % name)
    if has_yaw and has_yaw_deg:
        yaw_from_deg = math.radians(float(waypoint["yaw_deg"]))
        if abs(normalize_angle(yaw - yaw_from_deg)) > 1e-4:
            raise WaypointCalibrationError(
                "waypoint %s yaw and yaw_deg disagree" % name
            )
    return x, y, normalize_angle(yaw)


def resolve_waypoint_route(document, route_name, expected_frame="map"):
    validate_document(document)
    validate_waypoint_name(route_name)
    if document["frame_id"] != expected_frame:
        raise WaypointCalibrationError(
            "waypoint frame %s does not match requested frame %s"
            % (document["frame_id"], expected_frame)
        )
    try:
        names = document["routes"][route_name]
    except KeyError as exc:
        raise WaypointCalibrationError("unknown waypoint route: %s" % route_name) from exc

    goals = []
    for name in names:
        try:
            waypoint = document["waypoints"][name]
        except KeyError as exc:
            raise WaypointCalibrationError(
                "route %s references uncalibrated waypoint %s" % (route_name, name)
            ) from exc
        x, y, yaw = waypoint_pose(waypoint, name)
        goals.append(
            {
                "kind": "nav2",
                "label": name,
                "x": x,
                "y": y,
                "yaw": yaw,
                "action": waypoint.get("action", "transit"),
                "source": "waypoint_file",
                "route": route_name,
            }
        )
    return goals


def describe_waypoint_route(document, route_name, expected_frame="map"):
    goals = resolve_waypoint_route(document, route_name, expected_frame=expected_frame)
    steps = []
    for index, goal in enumerate(goals, start=1):
        step = dict(goal)
        step["index"] = index
        steps.append(step)
    return {
        "waypoint_route": route_name,
        "frame_id": document["frame_id"],
        "map_id": document.get("map_id", ""),
        "steps": steps,
    }
