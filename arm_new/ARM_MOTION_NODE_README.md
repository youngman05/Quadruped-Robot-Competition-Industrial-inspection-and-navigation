# Arm Motion Node

`arm_motion_node` is the only production ArmPi ROS 2 node. It does not
subscribe to YOLO, images, or navigation topics. The task manager owns target
selection and sends an I1-confirmed point to the node.

## Services

| Service | Type | Purpose |
| --- | --- | --- |
| `/arm/execute_grasp_fixed` | `arm_new_interfaces/srv/ExecuteGraspFixed` | Plan and execute the horizontal face-approach grasp. |
| `/arm/execute_place_fixed` | `std_srvs/srv/Trigger` | Plan and execute the calibrated fixed placement. |
| `/arm/preflight` | `std_srvs/srv/Trigger` | Check configuration, TF, serial port, and servos without moving the arm. |

`ExecuteGraspFixed.srv` is:

```text
geometry_msgs/Point target_arm_base
---
bool success
string message
```

`target_arm_base` is always in the ROS `arm_base_link` frame: `+X` forward,
`+Y` left, and `+Z` up. The node converts it to the ArmPi API frame internally:

```text
p_arm_api = [-y_arm_base_link, x_arm_base_link, z_arm_base_link]
```

The grasp service accepts the I1 reference target, normally
`(0.40, 0.00, z_final)`. It validates the configured x/y tolerance and z range,
then reuses the planning sequence from `scripts/face_approach_grab.py`:

```text
pre_grasp -> segmented approach -> close_gripper -> lift
```

It always uses `include_home=false`; the final lift pose is the transport pose.

The placement service has no request payload because the dog is already at a
calibrated A/B/C/D base pose. It reads `place_target_arm` in ArmPi API axes
from the parameter file and reuses `scripts/direct_place.py` planning:

```text
place_target -> open_gripper
```

It never starts either script as a subprocess, so there is no terminal prompt.

## Safety Semantics

- A second service request is rejected while one arm action is active.
- Real motion requires both `enable_motion=true` and
  `transform_calibrated=true`.
- With either flag false, grasp and place services still publish a plan but
  return `success=false`; task_manager must not treat this as a completed job.
- `grasp_reference_configured` and `place_target_configured` must be true
  before their corresponding service can execute.
- `/arm/preflight` checks `base_link -> arm_base_link` through TF and scans
  servo IDs 1 through 6, but sends no move command.
- The serial executor closing its port does not itself command torque-off.
  Holding torque after a grasp must be verified on the real arm before use.

## Parameters

The defaults in `config/arm_motion_params.yaml` are intentionally safe.
Calibration must provide:

1. The project-owned `base_link -> arm_base_link` transform in
   `configs/transforms/static_extrinsics.yaml`.
2. The I1 x/y reference, tolerance, and valid grasp z range in ROS
   `arm_base_link` axes.
3. `place_target_arm` in ArmPi API axes at a dog pose that has been calibrated
   for each A/B/C/D placement target.
4. `transform_calibrated=true`, `grasp_reference_configured=true`, and
   `place_target_configured=true` only after the above measurements pass.

## Jetson Build And Dry Run

```bash
cd /home/superwfx666/worktrees/quadruped-vision-yolo-refactor
colcon build --packages-up-to quadruped_robot_competition arm_new_ros
source /opt/ros/foxy/setup.bash
source install/setup.bash
ros2 launch arm_new_ros arm_motion.launch.py
```

In a second terminal, first call the non-motion preflight service:

```bash
ros2 service call /arm/preflight std_srvs/srv/Trigger '{}'
```

For dry-run planning, use a copied parameter file with calibrated target
values but leave `enable_motion: false`. A call to either execution service
must return `success: false` and a JSON message with `state: planned`.

```bash
ros2 service call /arm/execute_grasp_fixed \
  arm_new_interfaces/srv/ExecuteGraspFixed \
  '{target_arm_base: {x: 0.40, y: 0.00, z: 0.06}}'

ros2 service call /arm/execute_place_fixed std_srvs/srv/Trigger '{}'
```

Set `enable_motion: true` only after successful TF, preflight, and dry-run
checks on the Xavier host.
