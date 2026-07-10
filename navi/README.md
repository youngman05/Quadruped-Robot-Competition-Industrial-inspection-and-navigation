# Navigation Stack

This branch uses the official ROS 2 Navigation2 stack on the Jetson Foxy host.

## Runtime Chain

```text
D455 IR stereo + IMU
  -> Isaac ROS Visual SLAM in the Humble Docker container
  -> final_bridge.py on the Foxy host
  -> /odom + odom -> base_link TF
  -> Nav2 map_server + NavFnPlanner(use_astar=true) + DWB controller
  -> /cmd_vel
  -> Lite3 transfer driver or optional cmd_vel_bridge
```

The custom Python A* / Pure Pursuit navigator has been removed from this
integration branch. Nav2 is responsible for planning, costmaps, lifecycle, and
controller execution.

## Key Files

```text
configs/navigation/nav2_params.yaml
  Foxy-compatible Nav2 parameters. The first profile uses NavFn A* + DWB and
  static costmaps so lifecycle can be validated before enabling depth obstacles.

launch/navigation.launch.py
  Starts map_server, planner_server, controller_server, recoveries_server,
  bt_navigator, and lifecycle_manager.

launch/competition.launch.py
  Starts task_manager, localization helper nodes, optional cmd_vel_bridge, and
  includes navigation.launch.py when enable_navigation:=true.

src/nodes/navigation/navigation_client.py
  TaskManager wrapper around the Nav2 NavigateToPose action.

navi/map/
  Competition map data and generated PGM/YAML files for phase 1 and phase 2.

src/nodes/decision/task_manager.py
  Competition state machine. It now drives Nav2 goals instead of calling a
  custom Navigator class.
```

## First Validation Target

Before moving the robot, validate this dry-run chain:

```text
/odom fresh
/tf has map -> odom -> base_link
Nav2 lifecycle nodes are active
/map is published
NavigateToPose accepts a goal
/plan and /cmd_vel are produced
```

`enable_cmd_vel_bridge` defaults to `false`, so launching Nav2 does not send
UDP commands to Lite3 unless explicitly enabled or the Lite3 transfer driver is
started separately.

## Depth Obstacles

The first DWB profile keeps dynamic depth obstacles disabled until
`/camera/depth/points` is verified on the Jetson. After that, add a PointCloud2
source to the local/global costmaps and retest lifecycle activation before any
field run.
