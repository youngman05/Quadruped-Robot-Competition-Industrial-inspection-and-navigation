# Unified Static Transform Configuration Handover

## Purpose

Project-owned static sensor and actuator mounting extrinsics have one source
of truth. The intent is to prevent every node from carrying a different
matrix, RPY sign convention, or frame direction.

The current source of truth is:

```text
configs/
  transforms/
    static_extrinsics.yaml          # Editable static extrinsics
    static_extrinsics.schema.json   # Required fields and value shapes
    README.md                       # Frame ownership and coordinate convention
  calibration/
    yolo_xyz_test_points.yaml       # Test-point truth and acceptance template
  yolo/
    detection_v1.schema.json        # Docker camera_link UDP packet
    host_detection_v1.schema.json   # Host camera_link JSON packet
```

`static_extrinsics.yaml` stores only static transforms owned by this project.
Its mandatory direction is:

```text
p_parent = R_parent_child * p_child + t_parent_child
```

Lengths are metres and quaternions use ROS `xyzw` order. Do not maintain a
separate RPY value or 4x4 matrix as editable truth; derive either from the
translation and quaternion when needed.

## Frame Ownership

| Transform or frame | Owner | Configuration rule |
| --- | --- | --- |
| `base_link` | Lite3 robot description | Do not redefine its origin in this project config. |
| `base_link -> camera_link` | D455 physical mount | Store here and publish as a static transform. |
| `base_link -> arm_base_link` | Arm physical mount | Add only after measuring the arm mount. |
| `camera_link -> camera_*_optical_frame` | `realsense2_camera` | Never duplicate in this config or publish a competing TF. |
| Arm joints to end effector | Arm URDF and joint states | Dynamic TF, not static configuration. |
| `odom -> base_link`, `map -> odom` | SLAM/localization | Dynamic TF, not static configuration. |

The current camera entry describes `base_link -> camera_link`: D455 center is
80 mm forward and 493 mm above the Lite3 torso reference, with the supplied
positive 30 degree downward pitch. The Host bridge preserves Docker detections
in `camera_link`; a downstream consumer queries this TF only when it needs
`base_link`.

## Runtime Flow

```text
static_extrinsics.yaml
  -> launch/static_transforms.launch.py
  -> tf2_ros/static_transform_publisher (/tf_static)

Docker /d455_object_yolo_3d
  -> UDP 127.0.0.1:19002, frame_id=camera_link
  -> Host yolo_udp_bridge
  -> camera_link ROS detections and PoseArray topics
```

Use `launch/yolo_udp_bridge.launch.py` for the Host bridge alone. It starts
the static TF publisher and the bridge. When started from
`competition.launch.py`, the parent launch publishes static TF once and passes
`publish_static_transforms:=false` to child launches so no duplicate static TF
publisher exists.

The bridge accepts only the Docker UDP v1 packet and rejects stale or malformed
packets. It does not query TF; that lets a downstream consumer use freshness
as a safety signal and choose an explicit coordinate transform when needed.

## Current Calibration Status

The existing `base_link -> camera_link` metadata intentionally remains:

```yaml
status: provisional
source: "Nominal ..."
measurement:
  calibrated_at: null
```

This is correct for the present evidence level. The transform values are an
engineering initial installation estimate supplied for integration, but this
repository does not contain the original calibration fixture definition, raw
measurements, samples, operator record, or residual-error report. Changing
the entry to `calibrated`, replacing `Nominal`, or filling `calibrated_at`
without those records would make an unsupported accuracy claim. Do not change
these metadata fields during the current implementation work.

The configured uncertainty values are planning bounds, not measured error
statistics. Avoid using them as an avoidance safety margin until calibration
data exists.

## Required Evidence Before Marking Calibrated

After the D455 XYZ test is complete, retain the following alongside the run:

1. Exact `base_link` physical origin and axes used for all tape measurements.
2. D455 center offset and roll/pitch/yaw measurement method and instruments.
3. Target definition: class, visible planar-face reference point, dimensions,
   and each `base_link` ground-truth position.
4. Raw UDP JSONL or CSV samples, timestamped and linked to the test-point file.
5. Per-axis bias, standard deviation, P95 and maximum 3-D error over the
   declared distance range.
6. The operator, UTC timestamp, software/config revision, and test conditions.

Only then update `status` to `calibrated`, replace `source` with the calibration
method and run identifier, fill `calibrated_at`, and replace planning bounds
with measured uncertainty. If richer provenance is needed, extend the schema
and YAML together; do not add undocumented fields to YAML because the schema
disallows them.

## Deployment Constraint

The Xavier Foxy environment has an observed cross-process DDS reliability
problem: the bridge receives UDP and publishes ROS detections, but a separate
`ros2 topic echo` process may not receive the output. The ROS topics are the
intended interface, but a production avoidance consumer must not rely on this
DDS path until it passes a real Host-to-Host delivery test. Co-locating the
consumer with the bridge or using another explicit Host transport remains the
fallback.
