# Static Extrinsics

`static_extrinsics.yaml` is the single source of truth for static transforms
owned by this project. It uses the following direction everywhere:

```text
p_parent = R_parent_child * p_child + t_parent_child
```

All lengths are metres. Quaternions use ROS `xyzw` order. The configured
`base_link -> camera_link` transform maps a D455 result in `camera_link` to
the Lite3 torso/body frame.

Coordinate frames:

| Frame | Axes | Owner |
| --- | --- | --- |
| `base_link` | X forward, Y left, Z up | Lite3 robot description |
| `camera_link` | X forward, Y left, Z up | D455 mechanical mounting |
| `camera_color_optical_frame` | X right, Y down, Z forward | RealSense driver |
| `camera_depth_optical_frame` | X right, Y down, Z forward | RealSense driver |
| `arm_base_link` | ROS REP-103: X forward, Y left, Z up | Project static extrinsics |

Do not add RealSense internal optical transforms, arm joint transforms, or
`map`/`odom` transforms to this file. Those are owned by the RealSense driver,
the arm URDF, and localization respectively.

`arm_base_link` has the same physical origin as the `arm_new` API frame `arm`,
but it deliberately uses ROS axes. The API frame is right-handed with X right,
Y forward, Z up, whereas `arm_base_link` is X forward, Y left, Z up. Therefore,
for coincident origins:

```text
p_arm_base_link = [y_arm, -x_arm, z_arm]
```

`arm` is an API-only frame and is not published as TF. The YAML now contains a
user-provided `base_link -> arm_base_link` pose for TF integration. It remains
`provisional` until its measurement uncertainty and known-point validation are
recorded. Do not replace a missing or unknown pose with an identity transform:
every published static transform is consumed as physical truth.

The static-transform launcher reads this YAML and publishes every entry whose
`publish` value is `true`. Nodes must obtain inter-frame poses from TF, not by
embedding an additional matrix. `arm_motion_node` queries
`camera_link -> arm_base_link` and performs the documented final conversion to
the API-only `arm` axes immediately before planning.

The current camera transform is marked `calibrated` in the YAML. Its positive
30 degree pitch maps the D455 mechanical X axis downward in `base_link`. The
4x4 matrix is derived at runtime from the translation and quaternion; it must
not be maintained separately.

For the configuration structure, TF publication ownership, calibration status,
and evidence required before changing the metadata to `calibrated`, see
[static transform handover](../../docs/static_transform_config_handover.md).
