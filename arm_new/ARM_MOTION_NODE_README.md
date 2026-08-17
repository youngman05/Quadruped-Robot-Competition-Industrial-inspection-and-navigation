# Arm Motion Node

`arm_motion_node` is the only production ArmPi ROS 2 node. It does not
subscribe to YOLO, images, or navigation topics. The task manager owns target
selection and sends an I1-confirmed point to the node.

## Services

| Service | Type | Purpose |
| --- | --- | --- |
| `/arm/execute_grasp_fixed` | `arm_new_interfaces/srv/ExecuteGraspFixed` | Plan and execute the horizontal face-approach grasp. |
| `/arm/execute_place_fixed` | `std_srvs/srv/Trigger` | Plan and execute the calibrated fixed placement. |
| `/arm/stand_up` | `std_srvs/srv/Trigger` | Move IDs 2 through 6 to the calibrated initial position without changing the gripper. |
| `/arm/lie_down` | `std_srvs/srv/Trigger` | Move IDs 6 through 2 to the calibrated lying position without changing the gripper. |
| `/arm/preflight` | `std_srvs/srv/Trigger` | Check configuration, TF, serial port, servo IDs, and current pulses without moving the arm. |

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
`(0.42, 0.00, z_final)`. It validates the configured x/y tolerance and z range,
then reuses the planning sequence from `scripts/face_approach_grab.py`:

```text
pre_grasp -> segmented approach -> close_gripper -> lift
```

Before the approach, ID1 opens to `grasp_open_gripper_pulse=900`. The final
`close_gripper` target is `gripper_close_pulse=10`. Both steps read the current
ID1 feedback and send intermediate targets whose change is at most
`gripper_ramp_step_pulse` before reaching their configured target. The wrist
ID2 target in the initial mixed step is still sent once with its original
duration.

It always uses `include_home=false`; the final lift pose is the transport pose.

The placement service has no request payload because the dog is already at a
calibrated A/B/C/D base pose. It derives the grasp-end lift pose from
`place_reference_grasp_arm` in ArmPi API axes, returns to that pose, descends
`place_descent_m` with physical wrist joint `theta3` (servo ID3) fixed, then
opens the gripper:

```text
place_pose_1 -> place_descend_2cm -> open_gripper
```

The final `open_gripper` step also reads the current ID1 pulse and approaches
`400` with the same bounded pulse increments. If current ID1 feedback cannot be
read, the service fails instead of sending one direct target jump.

With the current `100` pulse increment, example ramps are:

```text
grasp open from 500: 500 -> 600 -> 700 -> 800 -> 900
grasp close:         900 -> 800 -> ... -> 100 -> 10
place open:           10 -> 110 -> 210 -> 310 -> 400
```

It never starts a standalone hardware script as a subprocess, so there is no terminal prompt.

The posture services execute one joint at a time and never command servo ID1:

```text
stand_up: ID2=504 -> ID3=256 -> ID4=755 -> ID5=636 -> ID6=519
lie_down: ID6=280 -> ID5=863 -> ID4=434 -> ID3=447 -> ID2=512
```

Both services publish their complete planned sequence on `/arm/posture_actions`.

## Safety Semantics

- A second service request is rejected while one arm action is active.
- Real motion requires both `enable_motion=true` and
  `transform_calibrated=true`.
- With either flag false, grasp, place, and posture services still publish a plan but
  return `success=false`; task_manager must not treat this as a completed job.
- `grasp_reference_configured` and `place_target_configured` must be true
  before their corresponding service can execute.
- `/arm/preflight` checks `base_link -> arm_base_link` through TF, scans servo
  IDs 1 through 6, and returns their current pulses without sending a move command.
- With `gripper_ramp_step_pulse` enabled, every motion step containing ID1 is
  executed from runtime feedback with bounded pulse increments. This covers
  grasp preparation, grasp closing, and placement opening.
- The serial executor closing its port does not itself command torque-off.
  Holding torque after a grasp must be verified on the real arm before use.

## Parameters

The defaults in `config/arm_motion_params.yaml` are intentionally safe.
Calibration must provide:

1. The project-owned `base_link -> arm_base_link` transform in
   `configs/transforms/static_extrinsics.yaml`.
2. The I1 x/y reference, tolerance, and valid grasp z range in ROS
   `arm_base_link` axes.
3. `place_reference_grasp_arm` in ArmPi API axes at a dog pose that has been
   calibrated for each A/B/C/D placement target.
4. `transform_calibrated=true`, `grasp_reference_configured=true`, and
   `place_target_configured=true` only after the above measurements pass.

`gripper_ramp_step_pulse` controls the largest requested ID1 change between
successive commands during grasp and placement. Its current value is `100`.

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
values but leave `enable_motion: false`. A call to any execution service
must return `success: false` and a JSON message with `state: planned`.

```bash
ros2 service call /arm/execute_grasp_fixed \
  arm_new_interfaces/srv/ExecuteGraspFixed \
  '{target_arm_base: {x: 0.42, y: 0.00, z: 0.15}}'

ros2 service call /arm/execute_place_fixed std_srvs/srv/Trigger '{}'

ros2 service call /arm/stand_up std_srvs/srv/Trigger '{}'

ros2 service call /arm/lie_down std_srvs/srv/Trigger '{}'
```

Set `enable_motion: true` only after successful TF, preflight, and dry-run
checks on the Xavier host.

For the supervised hardware test, pass the small local override file. The
launch file loads the production defaults first, then applies this override:

```bash
ros2 launch arm_new_ros arm_motion.launch.py \
  params_file:=configs/test/arm_pick_hardware_test.local.yaml
```
