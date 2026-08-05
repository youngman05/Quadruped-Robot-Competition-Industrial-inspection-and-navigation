# Static Extrinsics

`static_extrinsics.yaml` is the single source of truth for static transforms
owned by this project. It uses the following direction everywhere:

```text
p_parent = R_parent_child * p_child + t_parent_child
```

All lengths are metres. Quaternions use ROS `xyzw` order. The configured
`base_link -> camera_link` transform is available to downstream consumers that
need to convert a D455 result from `camera_link` to the Lite3 torso/body frame.
The Host UDP bridge itself publishes `camera_link` unchanged.

Coordinate frames:

| Frame | Axes | Owner |
| --- | --- | --- |
| `base_link` | X forward, Y left, Z up | Lite3 robot description |
| `camera_link` | X forward, Y left, Z up | D455 mechanical mounting |
| `camera_color_optical_frame` | X right, Y down, Z forward | RealSense driver |
| `camera_depth_optical_frame` | X right, Y down, Z forward | RealSense driver |
| `arm_base_link` | Defined when the arm mount is measured | Project static extrinsics |

Do not add RealSense internal optical transforms, arm joint transforms, or
`map`/`odom` transforms to this file. Those are owned by the RealSense driver,
the arm URDF, and localization respectively.

The current camera transform is an engineering initial value, not a calibrated
result. Its positive 30 degree pitch maps the D455 mechanical X axis downward
in `base_link`. The 4x4 matrix is derived at runtime from the translation and
quaternion; it must not be maintained separately.

For the configuration structure, TF publication ownership, calibration status,
and evidence required before changing the metadata to `calibrated`, see
[static transform handover](../../docs/static_transform_config_handover.md).
