# AprilTag-guided pickup

## Runtime path

```text
D455 color + CameraInfo (Docker)
  -> tag36h11 IDs 0..3 pose estimation
  -> one UDP packet per image
  -> Host /apriltag/detections_base (base_link)
  -> nearest configured red Tag selection and ID lock
  -> taught per-ID I2 alignment: yaw -> x -> y
  -> /arm/execute_grasp_fixed
```

The four tags are fixed to the box below the four fixed block slots. Tag IDs
are unique. Color mapping is configured by the operator when the tags are
attached; YOLO is not part of pickup target selection.

## Interfaces

Docker sends all tags detected in one image in one JSON UDP packet:

```json
{
  "schema_version": 1,
  "sequence": 42,
  "stamp": {"sec": 1, "nanosec": 2},
  "frame_id": "camera_link",
  "detections": [
    {
      "tag_id": 0,
      "position_m": [0.1, 0.2, 0.8],
      "orientation_xyzw": [0.0, 0.0, 0.0, 1.0],
      "reprojection_error_px": 0.3
    }
  ],
  "detection_ms": 4.2
}
```

The Host bridge loads the calibrated `base_link -> camera_link` transform from
`configs/transforms/static_extrinsics.yaml`, transforms every pose directly,
and publishes JSON `std_msgs/String` on `/apriltag/detections_base`. This does
not depend on runtime TF discovery. `base_link` uses +X forward, +Y left, +Z
up. Quaternion order is always XYZW.

The printed `tag36h11` black square is 100 mm, so the Docker detector uses
`tag_size_m=0.100`. The surrounding white quiet zone is not part of tag size.

On Xavier, start the existing D455 container and AprilTag process with:

```bash
cd ~/worktrees/quadruped-vision-yolo-refactor
bash scripts/start_d455_apriltag.sh
```

The default container is the already validated `d455_yolo_repro_20260811`.
The script reuses its camera topics and does not start another RealSense node.
It copies the detector into the container's writable `/tmp/d455_apriltag`
directory because the repository bind mount is read-only, and records the
process PID so repeated starts replace only the previous AprilTag process.

The bridge deliberately applies the fixed calibrated extrinsic itself. On the
Xavier Foxy/Fast DDS environment its Python TF buffer did not reliably discover
the static transform, so runtime TF is not a gate in this perception path.

## Target and I2

`configs/calibration/pick_i2_apriltag.yaml` stores:

- `pick_red_tag_ids`: the IDs attached below red blocks;
- one `taught` flag and `[x, y, yaw]` I2 pose for each ID;
- the fixed target required by the existing `ExecuteGraspFixed` request.

I2 means the target Tag pose in `base_link` when the dog is at that slot's
grasp stance. It is not a map pose and is taught after implementation.

At the coarse I0 stance, the executor selects the nearest visible red Tag by
`hypot(tag.x, tag.y)` and locks its ID. It does not switch targets during
alignment. If that ID has no taught I2, it stops with `I2_NOT_TAUGHT`.
After a successful grasp, that fixed slot ID is remembered for the current
route and excluded from later selections because its Tag remains on the box.

Alignment is discrete: yaw pulse, zero command and settle, fresh frame; then x;
then y. The full cycle repeats when confirmation finds an axis out of range.
Acceptance is three new settled frames satisfying:

```text
abs(x error) <= 0.03 m
abs(y error) <= 0.03 m
abs(yaw error) <= 3 deg
```

The I0-to-I2 timeout is 80 seconds. Missing target frames stop the base and are
waited out within that timeout. After I2 confirmation, the task directly calls
the existing `/arm/execute_grasp_fixed` service. No Tag-to-TCP transform or
YOLO-derived arm target is computed by the task node.

## Teaching I2

Manually put the dog at the grasp stance for one slot and keep it still. With
the Docker detector and Host bridge running:

```bash
cd ~/worktrees/quadruped-vision-yolo-refactor
source /opt/ros/foxy/setup.bash
python3 scripts/calibration/teach_pick_i2_apriltag.py 0 --samples 30
```

Repeat for IDs 1, 2, and 3. The script only reads Tag detections and updates
the selected ID in `pick_i2_apriltag.yaml`; it does not move the dog or arm.

## Cumulative acceptance

| Acceptance | `segment_name` | Expected stop |
|---|---|---|
| Step 0 | `pick_until_i0` | Nav2 reports success at coarse I0 |
| Step 1 only | `pick_i0_to_i2` | Dog starts at I0 and stops at selected Tag I2 |
| Steps 0-1 | `pick_until_i2` | Nav2 I0 then selected Tag I2 confirmation |
| Steps 0-3 | `pick_one` | I2 confirmation then grasp service succeeds |

Host launch for an I0-to-I2 supervised run:

```bash
ros2 launch quadruped_robot_competition competition.launch.py \
  enable_apriltag_udp_bridge:=true \
  enable_competition_manager:=true \
  route_mode:=segment \
  segment_name:=pick_i0_to_i2 \
  enable_route_execution:=true
```

Then start only after checking live Tag output and clearing the motion area:

```bash
ros2 service call /task/start_route std_srvs/srv/Trigger '{}'
```

For perception-only acceptance, keep the competition manager stopped and run:

```bash
cd ~/worktrees/quadruped-vision-yolo-refactor
bash scripts/start_d455_apriltag.sh
bash scripts/start_apriltag_host_bridge.sh
python3 scripts/probe_apriltag_bridge.py --frames 10 --timeout 15
```

The probe is read-only. It prints each visible Tag ID, `base_link` XYZ, yaw,
and inter-frame interval; it does not start the manager or publish motion.
