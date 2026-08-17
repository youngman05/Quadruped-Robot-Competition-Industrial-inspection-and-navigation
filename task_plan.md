# Task Plan: Quadruped Robot Competition L1 Session Memory

## Current Update - 2026-08-17 Phase 153 latest rerun mid-mission stop diagnosis
Diagnose the latest supervised rerun that stopped mid-mission, using preserved Jetson logs only. Separate an autonomous TaskManager/Nav2/odometry terminal event from the explicit later cleanup and compare the failure chain with the earlier post-obstacle incident.

### Phase 153: latest rerun mid-mission stop diagnosis
- **Status:** complete
- [x] Establish the newest run's startup, milestone, terminal, and explicit cleanup timestamps.
- [x] Correlate TaskManager, Depth relay, cuVSLAM, final bridge, and Nav2 evidence around the first terminal event.
- [x] Identify whether it reproduces the earlier stale-odom abort or has a distinct cause; report evidence and uncertainty.

### Phase 153 Result
- The new container was created and passed cuVSLAM/cone startup acceptance. It was not a reused stale container, and its source/image provenance is `19eee2e` / `aafbc91a`.
- The first `obstacle_cross_target` goal started at `1786937522.202`; TaskManager aborted at `1786937530.183` before the obstacle was crossed, with `runtime odometry became unavailable or stale`. There was no `DISABLED` request or live RealSense Depth Module restart in this interval.
- Nav2 did not fail the goal. TaskManager cancelled it after its own safety predicate. The bridge had sent non-zero commands and reported no UDP send error before the abort; the robot's stop was the expected fail-safe cascade.
- The incident coincided with systemic deadline/backlog evidence: controller loop misses throughout the goal, a stale cone UDP source timestamp at `1786937529.823`, persistent 66-133 ms cuVSLAM image gaps against a 40 ms threshold, and bridge stale/drained backlog. This establishes runtime scheduling/DDS overload as the likely trigger for the missing `/odom` delivery.
- The exact point of the >1-second gap cannot be reconstructed because the bridge comparison CSV stores only the textual stamp source. The logs do not distinguish definitively between a temporary cuVSLAM output gap, host UDP/DDS delay, and TaskManager callback starvation; they do exclude permanent tracker loss, a QoS incompatibility, and an autonomous Nav2 failure.

### Phase 154: synchronize L1 PWF records to Jetson formal worktree
- **Status:** complete
- [x] Transfer `task_plan.md`, `progress.md`, and `findings.md` to `/home/superwfx666/worktrees/quadruped-pick-place-formal-16ad08c`.
- [x] Verify each transferred file with SHA-256.
- [x] Preserve the remote worktree's business-code and runtime state.

### Phase 155: formal startup source-dirty NO-GO diagnosis
- **Status:** complete
- [x] Read the exact formal-startup Git cleanliness predicate.
- [x] Separate untracked PWF files from tracked source modifications.
- [x] Identify the modified tracked files without modifying or discarding them.

### Phase 155 Result
- The formal launcher intentionally uses `git status --porcelain --untracked-files=no`; `task_plan.md`, `progress.md`, and `findings.md` are untracked and cannot trigger this gate.
- The gate correctly found pre-existing tracked modifications to 18 files, including the TaskManager, pick/place configuration, arm implementation, tests, calibration gate, README, and L6 runbook. It also found separate untracked arm documentation/source files.
- The latest formal launch did not reach mission startup. `startup_no_go()` cleaned the current runtime container after reporting the dirty source tree. Preserving, committing, or discarding the tracked modifications requires explicit user direction.

### Phase 153 Constraints
- Read-only SSH diagnosis. Do not launch or stop processes, modify files/parameters, publish ROS traffic, send navigation goals, or command Lite3/arm/serial/actuators.

## Current Update - 2026-08-17 Phase 151 post-obstacle live stop diagnosis
Diagnose the current Jetson run stopping after the obstacle without changing runtime state. Correlate the obstacle milestone with TaskManager terminal status, depth/resource transitions, odometry freshness, Nav2 results, and the command bridge.

### Phase 151: post-obstacle live stop diagnosis
- **Status:** complete
- [x] Capture the latest startup/task logs and identify the exact obstacle-crossing and stop timestamps.
- [x] Cross-check live processes, ROS graph endpoints, TaskManager/depth/cone status, `/odom`, and `/cmd_vel` around the incident.
- [x] Distinguish the root cause from downstream zero-command behavior and report evidence plus residual uncertainty.

### Phase 151 Result
- `obstacle_cross_target` succeeded; the next waypoint was never sent because TaskManager aborted when `/odom` exceeded the 1.0-second runtime freshness limit.
- The repaired physical `enable_depth=true` policy avoided the prior RealSense module restart, but permanent Depth consumers still imposed high CPU/DDS load. The live relay also exited on a CameraInfo/frame width mismatch; this was downstream of the stale-odom abort, not the TaskManager abort predicate.
- The exact live cuVSLAM container and competition stack were subsequently cleaned under the user's explicit rerun request; no system services were stopped.

### Phase 152: Jetson competition-stack cleanup for rerun
- **Status:** complete
- [x] Run the repository `stop_all.sh` cleanup on the formal Jetson worktree.
- [x] Stop the exact running cuVSLAM container to prevent stale-container reuse.
- [x] Verify no competition container or related ROS/bridge/Depth/YOLO/cone process remains.

### Phase 151 Constraints
- Read-only SSH diagnosis only; do not stop/restart/deploy, set parameters, publish goals/Twist, invoke services, or command Lite3/arm/serial/actuators.
- Treat `/cmd_vel` zero as insufficient proof of physical stop; inspect publisher ownership and downstream bridge evidence.

## Current Update - 2026-08-17 Phase 150 publish and Jetson sync
Publish the completed D455 physical Depth continuity repair and synchronize the existing clean Jetson formal worktree to the exact GitHub commit without starting runtime.

### Phase 150: publish and Jetson sync
- **Status:** complete
- [x] Normalize the accidental verbose local commit message and push the exact repair commit.
- [x] Fetch and detach the existing Jetson formal worktree at the exact published commit.
- [x] Run focused Jetson source verification and confirm local/GitHub/Jetson provenance plus clean status.

### Phase 150 Result
- Published exact commit `19eee2eb80706b308a67483277aff5829b113d00` (`Keep D455 depth stream enabled across modes`) to `origin/codex/pick-place-selective-port`.
- Updated only `/home/superwfx666/worktrees/quadruped-pick-place-formal-16ad08c` from detached `b5ef00d` to the exact published commit; final tracked status is clean.
- Jetson Python compilation and focused source contracts passed `3/3 + 2/2`.
- Local HEAD, local remote-tracking ref, live GitHub ref, and Jetson HEAD all match the exact commit.
- The pre-existing cone UDP exporter and `cuvslam_gui_20260817-093922` container remained running and untouched; they continue using their already-loaded old runtime code until the next operator-controlled restart.

### Phase 150 Constraints
- Update only `/home/superwfx666/worktrees/quadruped-pick-place-formal-16ad08c` after confirming it is clean.
- Do not start, stop, or restart competition, ROS, Docker, camera, navigation, Lite3, arm, serial, or actuator runtime.

### Phase 150 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| First remote SHA gate used an incorrectly hand-completed long SHA and rejected the fetched commit before checkout | 1 | Confirmed the Jetson remained at `b5ef00d`, read the exact SHA from local Git and GitHub, then injected that value programmatically; synchronization passed |

## Current Update - 2026-08-17 Phase 149 keep D455 Depth physically enabled
Keep the D455 Depth/IR/IMU module continuous across mission depth modes. Stop high-load Depth consumers outside their required modes without setting RealSense `enable_depth=false`.

### Phase 149: keep D455 Depth physically enabled
- **Status:** complete
- [x] Confirm the dynamic `enable_depth=false` transition is the shared Stereo/Depth Module restart trigger.
- [x] Fix the Docker depth controller so `enable_depth` remains `true` in every mode while pointcloud/decimation remain avoidance-only.
- [x] Update focused contract coverage and run local verification.

### Phase 149 Result
- `depth_relay_docker.py` now always requests RealSense `enable_depth=true` for parameter-mode transitions.
- Logical Depth consumption remains mode-gated: `DISABLED` does not relay raw Depth frames, `MANIPULATION` retains J1 Depth, and pointcloud/decimation remain enabled only in `AVOIDANCE`.
- The formal competition launcher already exports `CUVSLAM_ENABLE_DEPTH=true`, so fresh competition containers start with the physical Depth stream enabled.
- Focused depth/cone/pick-place/startup verification passed `89/89 + 5/5`; Python compilation and `git diff --check` passed.

### Phase 149 Constraints
- Preserve logical mode gating: `DISABLED` must not write/relay raw Depth frames, while `MANIPULATION` may provide J1 Depth.
- Do not deploy, restart, or modify the live Jetson stack in this phase.

### Phase 149 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| `brv` is unavailable in the current PowerShell environment | 1 | Use the existing PWF incident history as local evidence and continue with the scoped repair |
| Default Python 3.14 has no `pytest` module | 1 | Used the standard-library `unittest` runner because the selected suites are `unittest`-based |
| Three test modules initially could not import `nodes` | 1 | Re-ran the same suite with repository `src` on `PYTHONPATH`; all 89 tests passed |

## Current Update - 2026-08-17 Phase 148 reused-container cone UDP startup NO-GO
Diagnose why the `10:08:58` formal restart reused the running cuVSLAM container, then reported no cone UDP datagram and cleaned the Host formal stack.

### Phase 148: reused-container cone UDP startup NO-GO
- **Status:** complete
- [x] Identify the exact failed startup snapshot and the last successful gate.
- [x] Inspect the reused container's live RealSense mode and cone exporter process.
- [x] Trace the NO-GO cleanup path and distinguish old `/tmp/competition.log` output from the new startup.

### Phase 148 Result
- Startup `20260817_100858` reused the already-running container `cuvslam_gui_20260817-093922` instead of creating a fresh AVOIDANCE-mode container.
- That container was left by the previous aborted mission with live `/camera/camera enable_depth=false`; the cone UDP exporter process was still running but had no Depth input.
- cuVSLAM tracking remained available through IR1/IR2, so `cuvslam_tracking_ready=true` passed. The next gate received no healthy UDP datagram on port `19002` and issued `NO-GO`.
- Reuse validation checks only container count, image identity, and cuVSLAM tracking. It does not restore or verify `enable_depth`, pointcloud, decimation, or the AVOIDANCE resource mode before probing cone UDP.
- `startup_no_go()` intentionally calls `scripts/stop_all.sh` whenever `STARTUP_RUNTIME_TOUCHED=true`, producing the observed `清理已启动的正式栈...` message. It did not stop the pre-existing cuVSLAM container because that container was not created by this startup attempt.

### Phase 148 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| PowerShell did not expand a Bash-style `scripts/*.py` path passed to `rg` | 1 | Read the exact script directly and searched explicit paths |
| `/tmp/competition.log` appeared as a sparse binary file because startup truncated it while the old launch still held its previous write offset | 1 | Used the timestamped startup snapshot and preserved cuVSLAM log as the authoritative new-start evidence |
| A bounded follow-up ROS CLI topic probe did not complete cleanly after the container ROS context had been interrupted | 1 | Relied on authoritative live `enable_depth=false`, the running cone exporter command line, the startup snapshot, and the operator-provided exact UDP probe failure |

## Current Update - 2026-08-17 Phase 147 stable depth-transition commit comparison
Compare the last field run that crossed the obstacle and completed all four inspections against current commit `b5ef00d`. Determine whether the latest commit changed the `DISABLED` transition, IR1/IR2/IMU ownership, or the runtime odometry abort path.

### Phase 147: stable depth-transition commit comparison
- **Status:** complete
- [x] Identify the current and prior field commits and verify the local remote-tracking provenance.
- [x] Compare the obstacle milestone and RealSense resource controller across the two commits.
- [x] Correlate the prior successful transition evidence with the current restart timing.
- [x] State whether the regression is code-delta-driven or a latent timing/driver hazard.

### Phase 147 Result
- The prior field version `0a49132` crossed the obstacle and completed four inspections; current `b5ef00d` is its only successor commit.
- The two versions have identical Git blobs for `scripts/depth_relay_docker.py`, `scripts/start_competition.sh`, and `launch/competition.launch.py`. The post-obstacle `DISABLED` milestone and generic one-second runtime odometry abort are also unchanged.
- `b5ef00d` changes only later pickup/placement depth timing and cone-layer no-op acknowledgement; it does not cause the immediate post-obstacle resource transition.
- The code requests only `enable_depth=false`, but the current RealSense driver stops/restarts the shared Stereo/Depth Module during dynamic reconfiguration. This transiently removes IR1/IR2; no incident evidence shows the separate IMU Motion Module was stopped.
- The prior run likely completed the same restart before the generic one-second odometry freshness guard expired. The current run took about 1.58 seconds to reopen IR, so the one-second guard latched `ABORT` before the intended two-second post-disable recovery gate could succeed. This is a latent driver/timing hazard inherited from the older depth-control design, not a regression introduced by `b5ef00d`.

### Phase 147 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Live `git ls-remote` could not reach GitHub because the configured local proxy endpoint `127.0.0.1` was unavailable | 1 | Verified that local `HEAD` and the existing `origin/codex/pick-place-selective-port` remote-tracking ref both resolve to `b5ef00d`; do not claim a fresh network fetch |
| The first `git log -S` search for the obstacle milestone was malformed by PowerShell quoting | 1 | Re-ran the history search with `git log -G 'obstacle_cross_target'` and identified the introducing commit |

## Current Update - 2026-08-17 Phase 146 post-obstacle odometry abort diagnosis
Diagnose the live field stop immediately after `obstacle_cross_target` using read-only SSH evidence. Determine whether navigation, the Lite3 command bridge, depth-mode switching, or the cuVSLAM odometry chain prevented the next waypoint, without changing or restarting the running stack.

### Phase 146: post-obstacle odometry abort diagnosis
- **Status:** complete
- [x] Correlate the first waypoint result, depth-mode request, TaskManager terminal transition, and zero-command behavior.
- [x] Inspect the RealSense/cuVSLAM/exporter/final_bridge chain across the exact incident window.
- [x] Read the live TaskManager timeout parameters and source ordering for runtime safety versus post-disable recovery.
- [x] Prove the odometry chain recovered after the transient interruption while TaskManager remained terminal.

### Phase 146 Result
- `obstacle_cross_target` succeeded at `09:42:22.278`; no second waypoint was sent because TaskManager entered permanent `ABORT` at `09:42:26.430` with `runtime odometry became unavailable or stale`.
- The `DISABLED` request at `09:42:25.233` set RealSense `enable_depth=false`. The driver then stopped the entire D455 `Depth Module`, interrupting IR1/IR2 as well as Depth; IR reopened at `09:42:26.893` (epoch `1786930946.893`), and cuVSLAM reported `Visual tracking is lost` at `09:42:27.016` before recovering.
- Effective TaskManager parameters are `odom_timeout_sec=1.0` and `host_odom_disable_timeout_sec=2.0`. `_runtime_base_safety_ok()` runs before the phase tick and aborts after the generic 1-second stale threshold, so `_host_odom_ready_after_depth_transition()` never receives its intended 2-second recovery window.
- The odometry chain recovered without intervention: the live controller status now reports `mode=DISABLED`, `healthy=true`, and fresh IR1/IR2/IMU/cuVSLAM samples; `/tmp/final_bridge_odom_compare.csv` grew by 61 rows in 2.20 seconds. The bridge and Lite3 UDP path remained healthy and continuously submitted zero after abort.

### Phase 146 Constraints
- Read-only diagnosis only: do not stop, restart, deploy, modify the Jetson, or issue navigation, velocity, arm, serial, or actuator commands.
- Do not represent a live publisher or recovered `/odom` as mission recovery; TaskManager remains terminal until a separately authorized restart.

### Phase 146 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| The JavaScript orchestration isolate did not expose `TextEncoder`, so the first Base64 transport setup failed locally | 1 | Switched to PowerShell/.NET UTF-8 Base64 transport; the failed attempt never reached the Jetson |
| ROS 2 Foxy `ros2 topic echo` does not support `--once`, and the terminal status topics are volatile | 1 | Used authoritative launch logs and live bridge-file growth instead; no runtime command or state change was issued |

## Current Update - 2026-08-16 Phase 145 depth-mode timing repair
Repair the supervised L6 stall after the fourth inspection by enforcing the intended camera-resource timeline: Depth is used only for cone avoidance and J1 placement alignment, while inspection, coarse pickup navigation, and RGB AprilTag/I2 pickup remain in `DISABLED` depth mode.

### Phase 145: depth-mode timing repair
- **Status:** complete
- [x] Correlate the live stall with the premature `MANIPULATION` request and cone-layer transition timeout.
- [x] Verify that `DISABLED` changes only the D455 Depth stream; RGB, IR stereo, and IMU remain separate resources.
- [x] Move `MANIPULATION` to post-arrival placement alignment and restore `DISABLED` before each pickup transit.
- [x] Make unchanged disabled cone-layer state acknowledge without waiting for a nonexistent revision.
- [x] Add focused two-round/resource-timing regressions and run local verification.

### Phase 145 Final Evidence
- Default policy now keeps Depth disabled before `grab_area_approach`, enables it only after `placement_[A-D]_approach` succeeds, and restores disabled mode before the next pickup transit.
- TaskManager resets the pickup depth milestone on every round; pickup transitions are fail-closed, while a placement Depth failure disables J1 only and preserves RGB AprilTag/I2.
- Cone safety remains fail-closed for real enabled-state changes, but accepts a no-op disabled-to-disabled transition only after parameter readback and matching local/global applied status.
- Focused changed-file tests passed `61/61`; expanded depth/cone/inspection/policy/pickup tests passed `156/156`. Python compilation and `git diff --check` passed.
- Two unrelated optional suites could not import local-only dependencies: `PyYAML` and `cv2`. No product assertion failed in those attempts.
- Published commit `b5ef00dbe8abfc5a5678c1c50ef9205ba1d5349d` and synchronized the clean Jetson formal worktree `/home/superwfx666/worktrees/quadruped-pick-place-formal-16ad08c` to the exact same detached HEAD.
- Jetson focused verification passed `61/61`; package-only `colcon build` succeeded, and the installed policy produced `AVOIDANCE,DISABLED,NONE,NONE,NONE,MANIPULATION,DISABLED`.
- Final provenance matched local, GitHub, and Jetson. The Jetson worktree remained clean with zero related competition processes and zero running containers.

### Phase 145 Constraints
- Do not stop, deploy, restart, or command the currently running Jetson competition stack without explicit operator authorization.
- Keep cone safety fail-closed; navigation may resume only after the requested depth mode and safety gate are end-to-end ready.
- A J1 Depth failure may disable placement vision only; it must not disable RGB AprilTag/I2 pickup.

## Current Update - 2026-08-16 Phase 144 installed initial-pose import failure
Fix the supervised L6 runtime stall where `initial_pose_publisher` exits from the installed ROS package, leaving no `map -> odom` transform and keeping Nav2/TaskManager at zero velocity. Replace the source-tree-only import with the installed start-prior artifact, rebuild only the affected package, and stop before another operator-controlled L6 launch.

### Phase 144: installed initial-pose import failure
- **Status:** complete
- [x] Correlate zero cmd_vel with TaskManager/Nav2 lifecycle logs and the initial-pose traceback.
- [x] Implement an install-space-safe start-prior loader with focused tests.
- [x] Publish/sync the exact commit and rebuild only `quadruped_robot_competition` on the Jetson.
- [x] Prove the installed node starts and publishes `map -> odom` without launching the competition route.

### Phase 144 Constraints
- Stop the currently stalled formal stack before deployment; do not issue navigation goals, nonzero cmd_vel, arm services, serial commands, or actuator commands.
- Preserve the accepted start transform `(x=4.65, y=0.75, yaw=pi)` and use the installed `cuvslam_start_prior.yaml` artifact as its source.
- Run only focused tests, package-only build, and a bounded standalone initial-pose/TF smoke.
- Keep the operator L6 entrypoint and external manipulation presets unchanged.

### Phase 144 Evidence
- `initial_pose_publisher` died with `ModuleNotFoundError: No module named 'navi_map_data'` from the installed site-packages path.
- `planner_server` then repeatedly reported that frame `map` did not exist; TaskManager waited for `planner_server`, and cmd_vel diagnostics remained exactly zero.
- `navi/map/navi_map_data.py` is not installed by `setup.py`; the existing `Path(__file__).parents[3]` logic therefore points inside the install prefix instead of the source worktree.
- `configs/navigation/cuvslam_start_prior.yaml` is already installed and encodes the identical accepted ROS transform `(4.65, 0.75, pi)`.

### Phase 144 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| The first remote stop command was corrupted by PowerShell expansion of the embedded Docker command and never executed remotely | 1 | Reissued the established stop flow through UTF-8 Base64 transport; all formal processes and the cuVSLAM container stopped |
| The standalone TF smoke expected an RPY text line, but Foxy `tf2_echo` emitted the equivalent quaternion format and the final grep returned status 1 | 1 | Read the captured TF directly and confirmed quaternion `[0,0,1,0]` equals yaw `pi`; no runtime defect remained |
| Terminating the outer `ros2 run` PID did not terminate its installed Python child after the smoke | 1 | Stopped only the standalone `initial_pose_publisher` child by its exact installed executable path and confirmed no smoke process remained |

### Phase 144 Final Evidence
- Published and deployed commit `0a49132baddd2fa72c5db69a16242113b96525bd`.
- Jetson package-only `colcon build --packages-select quadruped_robot_competition` passed.
- Focused verification passed `3/3 + 16/16 + 32/32` tests.
- The installed node logged start pose `(4.65, 0.75)` with yaw `3.141593` and published `map -> odom`; `tf2_echo` observed translation `[4.650, 0.750, 0.000]` and quaternion `[0.000, 0.000, 1.000, 0.000]`.
- The stalled formal stack and bounded smoke were stopped. No navigation goal, nonzero cmd_vel, arm service, serial command, or actuator command was issued during repair.

## Current Update - 2026-08-16 Phase 143 cuVSLAM Docker creation timeout
Diagnose and fix the supervised L6 startup failure `Docker startup timed out` with the smallest targeted change. Eliminate the uninformative 180-second wait when the background cuVSLAM launcher exits before creating a running container, preserve the underlying launcher error, and stop before another full L6 launch.

### Phase 143: cuVSLAM Docker creation timeout
- **Status:** complete
- [x] Correlate the failed startup snapshot with the launcher container-wait predicate and current Docker inventory.
- [x] Read the preserved background launcher log and identify the exact pre-container failure.
- [x] Implement the narrowest startup/runtime correction and focused regression coverage.
- [x] Sync the exact fix to the existing Jetson formal worktree and run only a bounded no-motion/container-start verification.

### Phase 143 Constraints
- Do not launch the full L6 wrapper, Nav2, TaskManager mission execution, Lite3 preparation, cmd_vel bridge, arm motion, serial, or actuator paths.
- Prioritize the failing launcher path; skip full repository regression and previously passed AprilTag verification unless directly affected.
- Do not wait the full container timeout when the background wrapper process has already exited; surface its log before cleanup.
- Preserve unrelated user changes and the external competition presets.

### Phase 143 Evidence
- The `20260816_130248` snapshot reaches `[1/6] Docker cuVSLAM` and records no runtime cuVSLAM container identity.
- `docker ps -a` contains no container from the failed timestamp, so the failure occurred before a cuVSLAM container remained running; it is not yet evidence of slow cuVSLAM tracking initialization.
- The current launcher polls only `docker ps` for 60 x 3 seconds and never checks whether `start_cuvslam_rviz_gui.sh` has already exited.
- A separate container named `d455_yolo_repro_20260811` is currently running on the Jetson and may conflict with camera ownership; the preserved `/tmp/cuvslam_start.log` is authoritative.

### Phase 143 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| The first remote D455 validator command was truncated by PowerShell/SSH quote expansion before Python ran | 1 | Switched to UTF-8 Base64 transport for the bounded remote script |
| The first Base64 validator invocation assumed the first candidate path, but this worktree stores the validator under `scripts/camera/` | 1 | Located the exact remote file and reran the same validator successfully |
| Jetson Python 3.8 could not import the test files as `tests.*` modules because `tests/` is not a package there | 1 | Executed the same two test files directly; all 48 tests passed |

### Phase 143 Final Evidence
- Root cause was the stale `d455_yolo_repro_20260811` container running `realsense2_camera_node` against D455 serial `235422300321`; `/tmp/cuvslam_start.log` reported `VIDIOC_S_FMT errno=16 Device or resource busy`.
- Stopped only that old test container and retained it in exited state. The exact D455 input validator then passed IR stereo/depth, IMU, and cuVSLAM camera-preset checks.
- Published commit `51a0c22855b76eff5645f02c1ed3087c71877d71` and synchronized the existing Jetson formal worktree to that exact detached HEAD.
- Local and Jetson focused verification passed `48/48`; Jetson `bash -n scripts/start_competition.sh` passed and the worktree is clean.
- The operator entrypoint remains `scripts/start_l6_pick_place_test_16ad08c.sh`; no L6 runtime was launched during the repair.

## Current Update - 2026-08-16 Phase 142 AprilTag OpenCV compatibility release
Fix the Docker AprilTag startup failure and advance the exact formal deployment to the point immediately before a new supervised L6 startup test. Implement compatibility, verification, diagnostic preservation, publication, Jetson synchronization, image rebuild, and isolated no-motion proof without launching the formal L6 stack.

### Phase 142: AprilTag OpenCV compatibility release
- **Status:** complete
- [x] Probe the accepted image's exact OpenCV ArUco API surface without camera or ROS stack startup.
- [x] Implement and test OpenCV 4.2/newer compatibility, runtime verification, and pre-cleanup log preservation.
- [x] Run the user-requested focused regression plus Python/Shell/static validation.
- [x] Commit/push the exact change and update the existing Jetson formal worktree in place.
- [x] Rebuild the immutable pick/place image and verify AprilTag startup in isolation without hardware access.
- [x] Audit source/image/config/runtime residue and stop before the next L6 startup command.

### Phase 142 Constraints
- Do not run `start_l6_pick_place_test_16ad08c.sh`, `start_l6_pick_place.sh`, or `start_competition.sh` in L6 mode.
- Do not start Nav2, TaskManager mission execution, Lite3 motion preparation, cmd_vel bridge, arm motion, serial, or actuator paths.
- Docker probes/build verification may run only without camera/device mounts and without the formal competition stack.
- Preserve the external I2/J1 competition preset values unless verification proves they are invalid.
- Verification claims must distinguish L0/L1/L2/L4 from the unexecuted L6 field test.

### Phase 142 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| The first isolated Docker API probe was corrupted by PowerShell/SSH quote escaping and Python stopped with `SyntaxError` before importing OpenCV | 1 | Replaced attribute-name string literals with `dir(cv2.aruco)`; the second isolated probe completed without hardware access |
| The first Jetson source-sync script used CRLF transport, so the old Git parsed `--short\r` as an unknown option after checkout succeeded | 1 | Confirmed exact HEAD and clean status with a separate LF-free read-only command |
| BuildKit treated `FROM sha256:<config-id>` as a remote Docker Hub image name and timed out without changing the accepted tag | 1 | Tag the exact old local image with a temporary base name and build the two-layer compatibility image from that local tag |
| The rebuilt image passed build-stage/full verifier and node smoke, but cleanup of the temporary old-image tag failed because a historical stopped container still references the old image | 1 | Retain the harmless local base tag; the new production tag/ID and all verification results are unaffected |
| The first final-preflight script compared against an incorrectly expanded full SHA after successfully switching the Jetson to `d16f245` | 1 | Read the authoritative local full SHA and rerun the preflight; no runtime component had started |

### Phase 142 Evidence
- Final local/GitHub/Jetson source commit: `d16f24575b8429a0b28794f7e916f9c713ad1507`.
- Final locked image: `sha256:aafbc91a7e7169fe3b6b87f7dd1caf639fbc0ff3c9fbfef6150b1b8b09fa5966`.
- Focused L1 evidence: `37/37` tests, Python compilation, five Shell syntax checks, and `git diff --check` passed.
- Isolated L2 evidence: build-stage and NVIDIA runtime verifier both reported `apriltag=ok`; an 8-second no-camera node smoke printed `AprilTag IDs [0, 1] ... UDP 19003`.
- Final no-runtime preflight reported `GO: pick/place preflight passed; competition runtime was not touched`, then confirmed clean worktree and no running cuVSLAM/verifier container.
- The next unexecuted action is the supervised L6 startup test.

## Current Update - 2026-08-16 Phase 141 Docker AprilTag readiness diagnosis
Diagnose the supervised L6 startup NO-GO `Docker AprilTag pose node did not become ready` from the operator-provided startup transcript. Keep the investigation read-only and distinguish a node launch failure, a readiness-probe mismatch, and missing camera input before proposing any correction.

### Phase 141: Docker AprilTag readiness diagnosis
- **Status:** complete
- [x] Trace the AprilTag Docker launch command and exact readiness condition.
- [x] Correlate the condition with the available startup snapshot and repository contracts.
- [x] Report the most likely cause, evidence needed from the Jetson, and bounded next diagnostic commands.

### Phase 141 Constraints
- Diagnose only; do not modify product code, external Jetson presets, Docker images, or runtime configuration.
- Do not launch ROS, Docker, Nav2, camera, arm, Lite3, serial, or actuator paths.
- Treat the operator transcript as field evidence, but do not claim a root cause that requires missing container or node logs.

### Phase 141 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| ByteRover long-term-memory query was unavailable because neither the `brv` CLI nor ByteRover MCP tools are exposed in this session | 1 | Continue with repository PWF history and read-only source inspection; do not treat the missing memory service as a product fault |
| The first combined PWF patch used an outdated final `progress.md` line as its anchor and was rejected atomically | 1 | Re-read the exact append-only tail and apply a corrected bounded patch; no file was changed by the rejected attempt |
| The first Docker build-file lookup assumed `docker/d455_perception/Dockerfile`, but that path does not exist | 1 | Locate the actual build context with `rg` before inspecting image assembly; no file changed |
| The first PTY EOF character was delivered as input to the remote Bash script, so the following `exit` was parsed as an invalid `$'\\004exit'` command after all read-only audit output had completed | 1 | Send a clean second `exit`; the SSH session closed and no remote state changed |

### Phase 141 Diagnosis
- Leading root cause: accepted image system OpenCV `4.2.0` exposes `cv2.aruco`, so `verify_runtime.py` passes, but the live detector calls the newer `cv2.aruco.DetectorParameters()` / `cv2.aruco.ArucoDetector` API and exits before its `AprilTag IDs` ready marker.
- The exact field run used source `73718f99d4b3a2ce768ef1fda24f0129032383a8`, image `sha256:f7384634ab69256558415a074d4ad53774f2399390ddcdc7135f2c33415fb5a0`, Tag IDs `[0,1]`, and Tag size `0.1`; these configured values passed the fixed-preset gate.
- Required correction: add an OpenCV 4.2-compatible detector path, make the image verifier instantiate the AprilTag detector/API surface, and preserve/tail the Docker AprilTag log before cleanup. This phase did not implement the correction.

## Current Update - 2026-08-16 Phase 140 temporary J1 enablement
Enable the Jetson external competition preset's placement vision alignment with the operator-selected temporary target distance `0.2 m`, so the one-click L6 flow enters J1. Preserve the value as uncalibrated temporary configuration and do not launch the stack or issue hardware commands.

### Phase 140: Temporary J1 enablement
- **Status:** complete
- [x] Confirm the exact clean Jetson source/config/runtime baseline.
- [x] Back up and update only the external competition preset to enable J1 at `0.2 m`.
- [x] Run the offline calibration gate and verify the one-click wrapper consumes the updated preset.

### Phase 140 Constraints
- Treat `place_target_distance_m: 0.2` as an operator-selected temporary value, not field calibration evidence.
- Keep I2 enabled with the original static extrinsic, original ID0/ID1 taught target, and `0.100 m` Tag size.
- Do not launch the one-click script, ROS, Docker, Nav2, camera, arm, Lite3, serial, or actuator paths.
- Do not run dedicated safety tests.

## Current Update - 2026-08-16 Phase 139 restore taught I2 contract
Restore the original project static extrinsic for AprilTag camera-to-base conversion and make the Jetson competition preset enable I2 by default using the original ID0/ID1 taught pose and 0.100 m Tag size. Keep J1 disabled because no placement target distance was authorized.

### Phase 139: Restore taught I2 contract
- **Status:** complete
- [x] Restore/install `configs/transforms/static_extrinsics.yaml` and make the AprilTag bridge default to it instead of navigation extrinsics.
- [x] Update focused bridge/package contracts and the L6 runbook without adding safety tests.
- [x] Commit/push, update the existing Jetson formal worktree, and rebuild only the affected ROS package.
- [x] Update the Jetson external competition preset to I2 enabled with original ID0/ID1 taught values and run the offline calibration gate.

### Phase 139 Constraints
- Use the original static transform `base_link -> camera_link` translation `[0.231724440, 0.077561412, 0.503275873]` and quaternion `[0.000900958, 0.240529563, -0.013474058, 0.970547870]`.
- Use original I2 target `[0.806210719, 0.018127014, 3.109325721]` for pickup IDs 0 and 1, with Tag size `0.100 m`.
- Keep `enable_place_vision_alignment: false` and `place_target_distance_m: 0.0`.
- Do not launch ROS/Docker/Nav2, start cameras, invoke arm services, prepare Lite3 motion, or issue actuator commands.
- Do not add or run dedicated safety tests.

### Phase 139 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| The local JavaScript orchestration isolate does not expose `btoa`, so Base64 transport construction failed before SSH was invoked | 1 | Use PowerShell/.NET UTF-8 Base64 conversion for the same bounded remote audit; no Jetson command ran |
| Jetson source switched successfully to `73718f9`, but ROS Foxy `setup.bash` referenced an unset `AMENT_TRACE_SETUP_FILES` under remote `set -u`, stopping before `colcon build` | 1 | Retain the exact synchronized HEAD, disable nounset only while sourcing the ROS environment, then run the same package-only build |
| The final read-only audit assumed transform values were top-level YAML keys and stopped with `KeyError: translation` | 1 | Select the `base_link -> camera_link` entry from `static_transforms` and read its `translation_m` / `rotation_xyzw`; no Jetson state changed |
| The corrected final audit printed all required transform/I2 values, then a whole-path `grep` failed because the Python path expression spans several source lines | 1 | Check the filename token and the wrapper's external YAML path independently, then finish the same read-only residue audit |

## Current Update - 2026-08-16 Phase 138 latest-worktree one-click L6
Make the existing one-click L6 wrapper run from its own current Git worktree and load the relocated grab waypoint. Update the formal waypoint release metadata so the startup gate accepts the operator-authorized route while retaining an explicit record that the new grab pose has no field outcome yet. Publish and update the existing Jetson formal worktree in place.

### Phase 138: Latest-worktree one-click L6
- **Status:** complete
- [x] Remove the wrapper's hard dependency on the `16ad08c` path/SHA and bind source/config provenance to its current worktree.
- [x] Make the relocated formal route startup-eligible without claiming field-result evidence for the new grab pose.
- [x] Update focused contracts and the Chinese runbook, then run only static/unit verification.
- [x] Commit/push and update the existing Jetson formal worktree in place from GitHub; do not launch the stack.

### Phase 138 Constraints
- Keep the existing filename `scripts/start_l6_pick_place_test_16ad08c.sh` for operator command compatibility, even though its contents become worktree-relative.
- Do not run dedicated safety tests, ROS, Docker, Nav2, camera, arm, serial, Lite3, or actuator actions.
- Do not create another Jetson Git worktree.
- Preserve the immutable image ID and the two external `competition_v1` YAML paths.

### Phase 138 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| The focused wrapper contract treated `&&` in worktree path resolution as the forbidden background-job substring ` &` | 1 | Rewrote the same path resolution as sequential command substitutions, retained the existing no-background-process contract, and passed the rerun |
| The first remote post-switch audit used `pgrep | wc -l` under `set -o pipefail`, so zero matches stopped the script before the final Docker count | 1 | The source switch and all prior checks had already succeeded; reran a read-only final audit with `pgrep ... || true`, then confirmed zero processes and zero containers |

## Current Update - 2026-08-16 Phase 137 GitHub-to-Jetson waypoint sync
Publish only the completed Phase 136 grab-approach relocation files to the current GitHub branch, then fetch the exact commit onto the Jetson without overwriting the frozen `16ad08c` worktree. Do not run safety tests, ROS, Nav2, Docker, or hardware actions.

### Phase 137: GitHub-to-Jetson waypoint sync
- **Status:** complete
- [x] Confirm the local branch/upstream and isolate the five Phase 136 files from unrelated user changes.
- [x] Commit and push the exact waypoint relocation change to `origin/codex/pick-place-selective-port`.
- [x] Fetch the exact GitHub commit on the Jetson into a new clean worktree and verify source/config identity only.

### Phase 137 Constraints
- Preserve the existing Jetson worktree `/home/superwfx666/worktrees/quadruped-pick-place-formal-16ad08c` unchanged.
- Do not include `docs/pick_place_l6_runbook_zh.md`, `tests/test_pick_place_integration_contract.py`, or `scripts/start_l6_pick_place_test_16ad08c.sh` in this commit.
- Do not start ROS, Docker, Nav2, camera, arm, serial, Lite3, or any actuator path.
- Do not add or run dedicated safety tests.

### Phase 137 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Tailscale SSH returned `502 Bad Gateway` before a remote session was established | 1 | Confirmed Tailscale ping and TCP/22 reachability, then used bounded ordinary SSH over the same Tailscale IP; no remote command had executed during the failed attempt |
| Jetson `git fetch origin <branch>` updated only `FETCH_HEAD`, while its stale remote-tracking ref still pointed to `26a2c28` | 1 | Verified local GitHub and Jetson `FETCH_HEAD` all matched exact `676ef89c...`, then fetched with an explicit branch-to-remote-tracking refspec before creating the worktree |

## Current Update - 2026-08-16 Phase 136 grab approach relocation
Relocate the grab-area Nav2 base-link approach from the left side to the platform's upper center using the operator-approved pose `(4.25, 3.05, -pi/2)`. Keep the route fail-closed until the new pose is accepted on the physical field. Per the user's latest instruction, do not add or run dedicated safety tests.

### Phase 136: Grab approach relocation
- **Status:** complete
- [x] Update the formal route, preview route, built-in navigation fallback, and standalone Nav2 probe to the same grab approach pose.
- [x] Downgrade formal waypoint calibration provenance so the changed pose cannot be mistaken for field-validated evidence.
- [x] Run only basic JSON/Python/whitespace consistency checks; do not add or run dedicated safety tests.

### Phase 136 Constraints
- Preserve the user's existing modifications in `docs/pick_place_l6_runbook_zh.md`, `tests/test_pick_place_integration_contract.py`, and `scripts/start_l6_pick_place_test_16ad08c.sh`.
- Do not connect to the Jetson, start a ROS graph or container, publish `/cmd_vel`, send a Nav2 goal, invoke an arm service, or issue any actuator command.
- Treat `(4.25, 3.05, -pi/2)` as an operator-approved offline candidate until supervised field acceptance restores `calibration.status: complete`.
- Keep the two PGM/map hashes unchanged; this task changes only the waypoint pose and its provenance.
- Do not add footprint, inflation-layer, collision, swept-path, or hardware safety tests for this change.

## Current Update - 2026-08-16 Phase 135 minimal supervised L6 launcher
Create one clean operator-facing entrypoint that launches the exact formal L6 route and manipulation flow without adding a monitoring process or duplicating the product launcher's internal status checks. Preserve explicit motion authorization, exact commit/image/config provenance, terminal ownership, signal forwarding, and the established stop path. Perform only offline/static verification in this session.

### Phase 135: Minimal supervised L6 launcher
- **Status:** complete
- [x] Audit the existing L6 wrapper/launch chain and identify the narrowest supported invocation that runs the complete route.
- [x] Add one minimal operator entrypoint with fixed formal defaults and explicit acknowledgement of the two physical pickup Tag IDs.
- [x] Add or update focused static contract coverage and operator documentation only where required by the new entrypoint.
- [x] Run Shell syntax, focused regression, complete relevant regression, whitespace, and ROS 2 validators without starting ROS, Docker, navigation, arm services, or actuators.
- [x] Report the exact onsite invocation and the remaining L6-only evidence boundary.

### Phase 135 Constraints
- Do not connect to the Jetson, start a container or ROS graph, send a navigation goal, publish `/cmd_vel`, invoke an arm motion service, open the servo bus, or issue any actuator command.
- Do not create an external watchdog, supervisor, polling loop, process monitor, or duplicate ROS graph/parameter/waypoint readiness checks.
- Do not bypass the existing product startup gate, arm authorization contract, cleanup trap, command arbiter, safety gate, or hard-fault behavior.
- Treat `pick_red_tag_ids: [0, 1]` as candidate configuration until the operator explicitly confirms both physical pickup identities onsite.
- Verification in this session is limited to L0/L1 and, if a build-only check is available locally, L2. Do not claim L6 success.

### Phase 135 Evidence
- [x] `scripts/start_l6_pick_place_test_16ad08c.sh` is a single `exec env` handoff, pinned to `/home/superwfx666/worktrees/quadruped-pick-place-formal-16ad08c`, the external `competition_v1` YAML files, exact source SHA `16ad08c6fc4b2368535919b88eed08af2e2f7590`, and accepted image ID `sha256:f7384634ab69256558415a074d4ad53774f2399390ddcdc7135f2c33415fb5a0`.
- [x] The wrapper sets the existing `PURE_L6_START=true` branch and submits the same `--pick-place-l6 --dog --cmd-vel-bridge --prepare-lite3-motion` arguments as the formal L6 entrypoint; the branch returns before post-launch ROS graph/QoS/parameter/health polling while TaskManager is already armed.
- [x] Static contract rejects monitor/recorder/process-management primitives (`nohup`, background jobs, loops, `sleep`, `timeout`, `ros2`, `docker`, `pgrep`, `wait`) in the new wrapper and requires one exec handoff plus all fixed deployment values.
- [x] Final offline verification passed: repository `tests/` `432/432`, `arm_new/tests/` `9/9`, Python compilation, six Shell syntax checks, `git diff --check`, and ROS 2 validators. No ROS graph, Docker/container, navigation goal, arm service, serial bus, actuator command, or Jetson connection was started.
- [x] The full route is still L6-only evidence: field operator must physically confirm the two pickup Tag identities, copy the one helper script into the pinned Jetson worktree, establish supervised area/physical stop readiness, and invoke it. The new script itself intentionally bypasses post-launch acceptance, so it is not a replacement for the accepted L4 evidence.

## Current Update - 2026-08-16 Phase 134 L6 preflight readiness audit
Audit the exact launch chain, calibration gates, deployed Jetson provenance, runtime configuration, and no-actuation bringup evidence required before supervised L6 field operation. Complete every safe offline or hardware-powered/no-actuation check that can be proven now, but stop before any route execution, camera ownership change, navigation command, arm-service motion, or actuator command.

### Phase 134: L6 preflight readiness audit
- **Status:** complete
- [x] Derive an evidence-backed readiness matrix from the launch scripts, calibration gate, configs, tests, runbooks, and ROS 2 safety/provenance requirements.
- [x] Audit the Jetson's exact deployed commit, worktree cleanliness, ROS install overlay, image identity, configuration copies, preserved calibration artifacts, and inactive runtime state.
- [x] Fix and validate any software, packaging, deployment, or fail-closed configuration defect that can be resolved without inventing field calibration values or enabling motion.
- [x] Replace the overbuilt approval-bundle design with a competition-oriented fixed arm preset, optional I2/J1 alignment, and fail-soft manipulation outcomes.
- [x] Enforce a conservative arm sequence time guard so the base cannot depart while an already-issued servo sequence may still be executing.
- [x] Re-run the focused and full local regression after closing the exact two-task, dual-tag, manipulation-navigation-skip, and `full_interleaved` gaps found during final review.
- [x] Freeze exactly two distinct A/B/C/D placement tasks after the fourth inspection for every 0-4 abnormal-detection count, with confidence/configured fallback selection and no stop on count mismatch.
- [x] Require exactly two configured pickup Tag IDs, exclude the Tag selected in round one from round two, and keep I2 failure/timeout/disablement fail-soft.
- [x] Convert final Nav2 failure at the per-round grab or placement approach into an uncertain skipped manipulation attempt that advances to the next frozen task; preserve hard ABORT for localization, odometry, command ownership, and startup faults.
- [x] Prove the pick/place launch path loads `waypoints_real.yaml` route `full_interleaved` while TaskManager still dynamically sends grab -> zone 1 -> grab -> zone 2.
- [x] Add a dedicated no-motion start entrypoint that exposes the ROS graph while keeping Lite3/cmd_vel bridge disabled, arm motion unauthorized, and TaskManager unarmed.
- [x] Review and publish a new exact commit, then replace the formal Jetson worktree with a fresh clean worktree at that commit before any complete preflight.
- [x] Run only explicitly bounded L0-L4 checks whose no-actuation boundary is independently reviewable, then stop and verify that containers, ROS nodes, camera owners, Nav2, arm services, and control processes leave no residue.
- [x] Supply external `competition_v1` site YAML files using the historically exercised fixed-arm preset and candidate pickup Tags `[0, 1]`, retain onsite confirmation of the actual two Tag IDs as the only required parameter edit, and pass the dedicated no-motion graph/service/parameter/waypoint plus `stop_all.sh` residue audit.
- [x] Re-run focused and complete local regression for the no-motion parameter-read correction, amend the single competition commit, force-push with lease, redeploy that exact SHA to a fresh formal Jetson worktree, fresh-build the four ROS packages, and repeat the bounded preflight/no-motion graph/residue audit.
- [x] Classify every remaining gate as satisfied, blocked on authentic field calibration, or requiring supervised L5/L6 evidence; do not claim field readiness while any hard gate lacks evidence.

### Phase 134 Constraints
- No L6 route execution, camera stream start, navigation goal, `/cmd_vel` command, arm motion service, manipulator enablement, calibration-value guessing, or actuator command.
- Preserve fail-closed defaults unless authentic accepted calibration and the corresponding supervised acceptance evidence are both present.
- Report verification levels explicitly. L0-L4 evidence cannot be promoted to L5/L6 language.
- Any Jetson runtime probe must be bounded, use the exact pushed commit/image, and end with a residue audit covering containers, ROS, camera, Nav2, arm, and control processes.
- Competition scoring policy: optional perception/alignment failures and arm outcome uncertainty degrade and continue; navigation, localization, startup ownership, and control-conflict faults remain hard ABORT conditions.

### Phase 134 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| The ROS 2 skill was first looked up under the nonexistent `.agents` path in the prior session | 1 | Loaded it from `C:\\Users\\111\\.codex\\skills\\ros2-engineering-skills\\SKILL.md` and use that root for all referenced documents |
| PowerShell 5.1 rejected a `foreach` statement whose output was piped directly to `Format-Table` | 1 | Collect the loop output in an array first, then format the completed array; no repository state changed |
| The first local Phase 134 Shell syntax attempt could not find `bash` in the Windows PATH | 1 | Located Git for Windows at `C:\\Program Files\\Git\\bin\\bash.exe`; use that executable for `bash -n` without changing product files |
| System Python 3.14 full `unittest discover` lacked `cv2` and `yaml`, producing five import errors | 1 | Reused the preserved test dependency directory with the bundled Codex Python 3.12 runtime; the formal `tests/` suite passed |
| Repository-root `pytest` collected camera, ROS, odometry, and live YOLO scripts as tests and stopped on seven hardware/environment imports | 1 | Restricted formal regression to the repository's `tests/` directory, matching the established baseline; no hardware script was executed |
| The first Jetson verifier preflight embedded Bash command substitutions in a PowerShell double-quoted SSH argument, so local PowerShell tried to execute `uname` before SSH | 1 | No remote command ran; switch to Base64 transport so the Jetson Bash script is preserved byte-for-byte |
| The Base64-preserved read-only verifier preflight could not establish ordinary SSH within the 10-second connection bound | 2 | No remote command ran; use the authenticated `tailscale ssh` transport that previously worked for this Jetson |
| The formal-reference search explicitly included a nonexistent repository `AGENTS.md` path | 1 | Retained the valid `scripts`, `docs`, `tests`, and `README.md` results; omit missing optional files from later searches |
| The Jetson's older Git printed the unsupported `--path-format=absolute` token while resolving common directories | 1 | The following line still exposed the usable common directory; use plain `--git-common-dir` plus `realpath` for the authoritative follow-up |
| The first formal-worktree creation wrapper exited during the zero-match process count because `grep` returned 1 under `set -o pipefail` | 1 | It stopped before `ls-remote`, fetch, or worktree creation; replace grep pipelines with `awk` counters that return success for zero matches |
| The first launch-argument verification searched for script-level flags `pick_place_l6` and `pick_place_preflight_only` in ROS launch arguments | 1 | `--show-args` succeeded and left no residue; validate the actual launch arguments that those script flags drive instead |
| A coordination step accidentally submitted an empty `apply_patch` | 1 | The patch tool rejected it before any file changed; continue with explicit non-empty PWF or product patches only |
| The first PWF audit-update patch used one finding line that did not exactly match the file | 1 | The multi-file patch failed atomically; reread the tails and apply smaller exact-context patches |
| The formal calibration audit found that global AprilTag IDs were incorrectly treated as I2 pickup targets and that offline calibration acceptance required `enable_motion=true` | 1 | Keep Phase 134 open; introduce explicit tag roles and separate calibration acceptance from per-run motion authorization before generating field evidence |
| Reissuing `/goal` found that the thread already had the same unfinished active goal | 1 | Kept the existing goal unchanged and resumed Phase 134 from the uncommitted 15-file competition-policy checkpoint |
| A Windows `rg` call used an invalid wildcard path for the pickup core | 1 | Located the actual `src/nodes/decision/pick_alignment_core.py` file directly and continued with explicit literal paths |
| The first focused regression passed pickup pose objects as the `frame()` sequence argument | 1 | Corrected the new two-round Tag test to pass sequence `1` before the poses; product code was unaffected |
| Bundled Codex Python 3.12 could not import PyYAML for the calibration-gate tests | 1 | Keep repository clean and provide test-only dependencies from a task-specific temporary directory before rerunning |
| The resumed session first referenced a stale bundled-Python path for PWF catch-up | 1 | Located system Python 3.14, reran `session-catchup.py`, and confirmed there was no unsynchronized context; no repository state changed |
| A PowerShell 5.1 file-statistics loop piped `foreach` output directly and hit the known empty-pipe parser error | 1 | Collected rows in an array before formatting; all three PWF files were then measured successfully |
| The final push reported a GitHub ref-lock race because the remote branch had already advanced from `f31993c` to the new exact commit during the request | 1 | `git ls-remote` proved the remote already points to `26a2c28a52ccec9c1b54eeead6aff0e215e28b03`; performed a narrow fetch to synchronize the local remote-tracking ref and did not retry the write |
| The first two resumed Jetson Base64 wrappers embedded PowerShell syntax that the JavaScript tool orchestrator could not parse | 1-2 | Both failed locally before any SSH process or remote command existed; replaced PowerShell backtick newline handling with a character-code LF conversion, after which the same bounded audit succeeded |
| The first Jetson build wrapper used Bash `${...}` array syntax that was interpreted by the local JavaScript template, and the next pre-build run sourced Foxy under `set -u` | 1-2 | The first failed locally before SSH; the second exited remotely before `colcon` and before creating build/install/log. Replaced arrays with explicit base paths and temporarily disabled nounset only while sourcing ROS setup, then the single actual build completed |
| The first Jetson static-verification connection hit a transient Tailscale 502, and the retry incorrectly expected the route's 14 sequence entries to remain 14 unique dictionary keys | 1-2 | Ping restored direct connectivity. Inspection showed `upper_corner_clear` intentionally appears twice, so the resolved sequence is 14 while the label-keyed waypoint mapping is 13; correct the verifier to assert both facts separately and require all five grab/place labels |
| The expected-failure no-motion wrapper audit searched stderr for a gate message that the launcher writes to stdout | 1 | Read the bounded evidence files directly, confirmed the expected `competition_v1` rejection, and independently proved zero containers/processes/ports plus clean Git; no retry or runtime start was needed |
| The resumed preset audit first referenced the historical `configs/ros/task_manager_params.yaml` path, which no longer exists in the finalized branch | 1 | Located the current source at `configs/manipulation/pick_place.yaml`; no repository or runtime state changed |
| The first Jetson external-preset deployment double-escaped Bash variables inside a PowerShell here-string, creating literal `"$task"`, `"$arm"`, and empty `"$cfg"` paths and preventing the gate from running | 1 | Verified all three exact absolute paths were newly created under `/home/superwfx666`, removed only those objects, confirmed zero runtime residue, and switched the retry to fixed absolute paths with placeholder substitution |
| The first exact-config no-motion graph wrapper imposed a 240 s outer timeout that expired after all nodes appeared but before the product script's own bounded lifecycle/parameter acceptance completed | 1 | `stop_all.sh` succeeded and all container/process/port/worktree residue checks were zero. Snapshot evidence shows cuVSLAM, depth, Cone UDP, Nav2, TaskManager, arm, and whz had started; retry once with a 420 s outer budget while retaining every product-level timeout and no-motion gate |
| The 420 s no-motion wrapper also expired during steadily progressing live-parameter validation, five seconds after the last successful snapshot write | 2 | Snapshot proves all Nav2 lifecycle nodes active, `/cmd_vel` has zero robot subscribers, Cone QoS is correct, and validation was advancing through controller parameters. Derive a 720 s wrapper from the code's verifier/Docker/lifecycle/per-CLI upper bounds; do not change product timeouts or skip checks |
| The 720 s run reached the real arm preflight and rejected the route because the configured z-range midpoint `0.20` is outside the current pose-constrained IK and no servos were online | 3 | Keep the fixed preset at its historical tested z `0.15` instead of an untested range midpoint. Change no-motion preflight to skip servo discovery only while `enable_motion=false`; retain mandatory online-servo preflight when explicit motion authorization enables the arm. Amend the existing single product commit and redeploy exact final SHA |
| The resumed configuration-gate regression could not import PyYAML from either system Python 3.14 or the bundled Codex Python 3.12 | 1 | Pause before publication; restore a task-specific temporary test dependency directory, rerun the complete local regression, and keep repository/runtime environments unmodified |
| A tool-orchestration probe used PowerShell array syntax directly in the JavaScript wrapper | 1 | The wrapper failed before launching any command; switched to a JavaScript array of explicit `exec_command` calls and left repository state unchanged |
| PowerShell parsed unquoted Git revision `@{upstream}` as a hash literal | 1 | The read-only command failed before Git ran; quoted `'@{upstream}'` and confirmed local HEAD, upstream, and GitHub all still resolve exact `26a2c28a52ccec9c1b54eeead6aff0e215e28b03` |
| The first Jetson audit wrapper assumed the JavaScript isolate exposed `TextEncoder` | 1 | It failed locally before SSH; encoded the ASCII-only remote script with an explicit Base64 routine and completed the audit without remote side effects |
| The first final Jetson build supplied only the repository root to `colcon --base-paths`, so the three nested packages were reported unknown | 1 | Only the root package built and no runtime started. Audited the partial state, removed the exact newly created worktree, recreated it cleanly, and supplied four explicit package roots; all four packages then built successfully |
| The first build failure trap placed state-changing commands inside a block piped to `tee`, so parent-shell cleanup flags stayed unset | 1 | Independently audited the exact partial worktree and backup, then replaced the logger with `exec > >(tee ...)` so the retry trap retained shell state and could restore/remove exact targets on failure |
| A Windows `rg` query used `scripts/*.sh`, which is not a valid literal path argument in this PowerShell invocation | 1 | The read-only query failed without state change; used the already-read explicit launcher files and direct source line inspection instead |
| Tailscale SSH disconnected during the final no-motion acceptance and the Jetson then became unreachable/offline | 1 | Do not restart the stack. Wait for the existing host to return, immediately inspect the remote EXIT-trap evidence and force a bounded `stop_all.sh` plus residue audit before deciding whether any acceptance step needs repetition |
| The interrupted final no-motion run was initially treated as an unexplained abnormal reboot | 1 | User confirmed the Jetson lost external power. Reclassify the interruption as an external-power event, not evidence of OOM, thermal shutdown, kernel panic, or product failure; rerun the same bounded no-motion acceptance after power restoration |
| The post-power-loss no-motion retry reached the full graph but a single `ros2 param get /cone_scan_safety_gate health_timeout_sec` exited nonzero after all prior parameter reads succeeded | 1 | Source and live node logs prove the parameter exists at `0.20`; add three bounded read retries with process-liveness checks, preserve NO-GO after exhaustion, rerun the full regression, and amend the single competition commit before redeployment |
| The first detached supervisor used `ls -1t ... | head -1` under `pipefail`, so its evidence-copy path exited with SIGPIPE 141 after the product had already returned NO-GO | 1 | The supervisor's EXIT trap still completed `stop_all.sh` and proved zero residue. Replace `head` with non-SIGPIPE selection in the next evidence wrapper; this did not affect the product failure or cleanup |
| The first standalone `arm_new/tests/` rerun omitted the repository's `arm_new` directory from `PYTHONPATH` | 1 | No product code ran or changed; reran with the established isolated dependency path plus `src` and `arm_new`, and all `9/9` tests passed |
| The final no-motion supervisor reported four failures after the product returned `START_RC=0` | 1 | Proved all four were harness false negatives: one damaged UTF-8 regex, one negative launch argument containing `cmd_vel_bridge`, and two irrelevant Unix executable-bit checks for scripts whose contract is explicit `bash`; wrote ASCII-only adjudication evidence without restarting runtime |
| The final read-only package-prefix audit sourced the Foxy colcon setup while `set -u` was active and stopped on undefined `COLCON_TRACE` | 1 | Re-ran only the remaining read-only checks with nounset disabled during environment sourcing; all four installed package prefixes resolved under the exact formal worktree |

### Phase 134 Evidence
- [x] Final source provenance is exact commit `16ad08c6fc4b2368535919b88eed08af2e2f7590` on local HEAD, upstream tracking, GitHub, and the clean detached Jetson worktree `/home/superwfx666/worktrees/quadruped-pick-place-formal-16ad08c`.
- [x] Final local publication gate passed formal startup `21/21`, complete repository `431/431`, arm `9/9`, compileall, four Shell syntax checks, `git diff --check`, and ROS 2 validators.
- [x] Jetson fresh build completed exactly four packages in 53.6 seconds; no-action preflight returned `PREFLIGHT_RC=0` and `FINAL_STATUS=PASS`. Evidence: `/home/superwfx666/competition_logs/deployment/20260816T015530Z_formal_pick_place_16ad08c` and `/home/superwfx666/competition_logs/deployment/20260816T015734Z_preflight_16ad08c`.
- [x] Final no-motion entrypoint returned `START_RC=0`; TaskManager remained unarmed, arm motion unauthorized, `/cmd_vel` had zero subscribers, required nodes/services/lifecycle states/parameters and all grab/place waypoints passed, and cleanup left zero running containers, related processes, target ports, or Git changes. ASCII adjudication SHA-256 `b7da1260f6abc81924b6b0fa3eeabd81b805be36f8e6bca401be0eb6dd262659` is stored under `/home/superwfx666/competition_logs/deployment/20260816T021155Z_no_motion_graph_16ad08c`.
- [x] The accepted GPU image remains exact `sha256:f7384634ab69256558415a074d4ad53774f2399390ddcdc7135f2c33415fb5a0`; no image rebuild occurred and no navigation or arm-motion command was issued.
- [x] Re-ran the exact accepted image's full no-camera verifier on the Jetson with `--runtime nvidia --network none`, explicit GPU device `0`, a 180-second bound, a unique container name, and exact cleanup. The verifier passed and the post-run residue audit was empty.
- [x] Reviewed, locally validated, committed, and pushed the fail-closed preflight hardening as exact commit `f31993c7e3dab77ef63a0e6861e3698264d5969a`; formal Jetson deployment and rebuild remain pending.
- [x] Created `/home/superwfx666/worktrees/quadruped-pick-place-formal-f31993c` from the separate clean formal Git repository after an exact remote-ref gate; it is detached, tracked/untracked clean, and resolves exact `f31993c7e3dab77ef63a0e6861e3698264d5969a`.
- [x] Built exactly `quadruped_robot_competition`, `whz`, `arm_new_interfaces`, and `arm_new_ros` in the fresh formal worktree; all four prefixes and expected console entry points resolve inside its install, with zero post-build runtime residue.
- [x] Verified five installed artifacts byte-for-byte, parsed the formal launch arguments without starting nodes, and validated the installed seven-class Host protocol with seven accepted packets plus five malformed rejections.
- [x] Invoked the formal wrapper with explicit `UNAPPROVED` sentinels and both approval flags false; it returned the expected calibration NO-GO rc `2` before logs/runtime mutation, and the before/after residue audit remained zero.
- [x] Implemented the uncommitted competition-oriented `competition_v1` fixed-preset path, optional I2/J1 alignment fallbacks, fail-soft manipulation outcomes, separate motion authorization, and the conservative post-dispatch arm guard.
- [x] Passed the final focused regression (`39/39`), full bounded `tests/` regression (`412` tests plus `294` subtests), Python compilation, three Shell syntax checks, `git diff --check`, and the ROS 2 skill validators.
- [x] Stopped at the local L0/L1 evidence boundary with 15 product/test/document files modified and uncommitted; no push, Jetson connection, deployment, ROS/camera/container/serial startup, navigation command, arm service call, or actuator action occurred in this implementation pass.
- [x] Final publication regression passed the focused `80/80`, complete `tests/` `429/429`, and `arm_new/tests/` `9/9` suites, Python compilation, four Shell syntax checks, `git diff --check`, and ROS 2 skill validators with zero issues or skipped checks.
- [x] Published exact `26a2c28a52ccec9c1b54eeead6aff0e215e28b03`, deployed it to a new clean detached Jetson worktree, built all four packages, verified installed provenance/launch/waypoints/entrypoints/default fail-closed behavior, and retained zero runtime residue. Successful no-motion graph bringup is blocked only by missing authentic site preset YAML values.
- [x] Revalidated the three-file no-motion arm-preflight correction locally: focused competition/arm suites `90/90`, complete repository suite `430/430`, Python compilation, four Shell syntax checks, `git diff --check`, and ROS 2 validators all passed with zero skipped checks.
- [x] Revalidated the bounded startup-parameter retry correction locally: formal startup contracts `21/21`, complete repository suite `431/431`, `arm_new/tests/` `9/9`, compileall, four Shell syntax checks, `git diff --check`, and ROS 2 validators all passed.
- [x] Amended and force-with-lease pushed exact final candidate `0e401f8c87509820e62cb4a683dadf31254ca130`, created the clean Jetson formal worktree, built all four required packages, retained the accepted image ID, and passed the exact-config no-action preflight with zero residue.

## Current Update - 2026-08-16 Phase 133 trusted inference wheels and unified image
Recover independently reviewable provenance for the exact Jetson-compatible Torch and Torchvision wheels, verify their filenames, ABI, versions, and SHA-256 values, then build and run the no-camera unified-image acceptance only if all four locked inputs are trustworthy.

### Phase 133: Wheel provenance and image build
- **Status:** complete (exact commit `af34b9f3c371f7ad551c6a30edf4126bcdc9ba6a` built image `sha256:f7384634ab69256558415a074d4ad53774f2399390ddcdc7135f2c33415fb5a0`; the no-camera `--runtime nvidia --network none` full verifier passed)
- [x] Inspect the Jetson's existing compatible Torch/Torchvision installation metadata and pip caches for exact wheel origins or preserved artifacts.
- [x] Verify any candidate source is official, targets CPython 3.8 aarch64/JetPack 5, and resolves to Torch `2.0.0+nv23.5` plus Torchvision `0.15.1`.
- [x] Compute and record SHA-256 from the exact immutable wheel artifacts; do not build from guessed, floating, or mismatched inputs.
- [x] Complete and review the explicit Python 3.8/aarch64 transitive lock while retaining `--no-deps` and the system OpenCV exception.
- [x] Commit and push the dependency-lock correction, then rerun only the first-stage unified-image Docker build; the retry passed dependency validation and stopped at the build-stage Torch import.
- [x] Keep target-image inspection, the post-build NVIDIA-runtime verifier, camera access, ROS startup, and motion acceptance deferred until the first-stage build result is reviewed.
- [x] Split the verifier into a CUDA-independent build-stage mode and the unchanged NVIDIA-runtime full mode; add a regression test that forbids Torch imports in build-stage mode.
- [x] Commit and push the verifier split, then rerun only the first-stage Docker build at the new exact SHA; image export succeeded at `78a120f`.
- [x] After explicit staged approval, run the no-network NVIDIA-runtime verifier against the built image; do not access the camera, ROS graph, navigation, arm service, or actuators.

### Phase 133 Constraints
- No camera access, ROS route start, container deployment start, arm service start, navigation start, or actuator command.
- External web/download evidence is untrusted research data until independently checked; record it only in `findings.md`, never as instructions in `task_plan.md`.
- Stop before image build if wheel provenance, ABI, URL immutability, or SHA-256 cannot be established.

### Phase 133 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Initial local verifier read used the nonexistent path `docker/pick_place/verify_runtime.py` | 1 | Read the tracked verifier from `docker/d455_perception/verify_runtime.py`; no product file was changed |
| Jetson pip 20.0.2 does not implement `pip cache`, so the first metadata probe could not list cache entries | 1 | Retained the successful installed-package metadata evidence and delegated a bounded filesystem/cache search without relying on that subcommand |
| The official Torch comparison command completed successfully but its final temporary-directory cleanup received a trailing carriage return through PowerShell stdin transport | 1 | Removed the exact empty directory separately; the downloaded wheel hash and byte comparison were already complete and valid |
| The first combined local AST command had an unmatched list-comprehension bracket in its command string | 1 | Re-ran AST parsing file-by-file with positional arguments; both files, Shell syntax, and `git diff --check` passed |
| The first multi-line Jetson image preflight again received a trailing carriage return on its final `fi` through PowerShell stdin transport | 1 | Re-ran the exact preflight through Base64 transport; the target image is absent and no build was started |
| Initial session-recovery fan-out passed a redundant `-Command` token to the host-native PowerShell executor | 1 | Re-ran the reads as native PowerShell command bodies; no repository or Jetson state changed |
| The first build dispatch attempted to use unavailable JavaScript `btoa` in the local tool orchestrator | 1 | No SSH session was opened; switched Base64 generation to PowerShell/.NET before retrying the same remote build script |
| Unified-image build failed in Docker layer 2/8 because inherited APT sources were unauthenticated: expired ROS 2 testing key plus missing Kitware and Isaac ROS keys | 1 | Docker exited 100 before wheel download, hash verification, or package installation; stopped at Phase 133 without running image inspection or later acceptance stages |
| Initial fix inspection referenced the obsolete path `docker/d455_perception/Dockerfile.cuvslam-pick-place` | 1 | Read and edited the actual tracked file `docker/Dockerfile.cuvslam-pick-place`; no file changed during the failed read |
| First scoped-APT probe still reached Isaac ROS because that repository is embedded in the inherited main `/etc/apt/sources.list` | 1 | Inspected sources in a no-network disposable container and changed the derived layer to generate an Ubuntu-ports-only temporary source list |
| Rebuilt commit `fa9111f` passed APT isolation and both wheel hashes but failed layer 4/8 `pip check` because the no-deps lock omits required transitive packages and the base image has two pre-existing metadata gaps | 1 | Stopped before image export, runtime verifier, or later acceptance; dependency closure requires a separate explicitly authorized fix |
| First `4c86ebf` build dispatch used an interpolating PowerShell here-string, so local PowerShell expanded Bash `$()` expressions before SSH | 1 | Jetson audit confirmed the new worktree and image are absent and no container is running; retry with a single-quoted PowerShell here-string that preserves the remote Bash script byte-for-byte |
| Rebuilt commit `4c86ebf` passed the 43-package `--no-deps` install and strict `pip check`, then failed layer 8/8 because importing NVIDIA Torch during plain `docker build` cannot find runtime-mounted `libcurand.so.10` and `libcublas.so` | 1 | Stopped before image export or any `docker run`; the next correction must keep Torch/model/NMS verification exclusively in the post-build `--runtime nvidia` stage and make the build-stage check independent of CUDA library mounts |
| The first full `docker run --rm --runtime nvidia --network none` verifier at image `sha256:21d4dbf...de06a` still could not import Torch because `libcurand.so.10` and `libcublas.so` were absent from the container runtime path | 1 | Container exited 1 and was removed; inspect NVIDIA runtime library injection and image compatibility before changing or retrying the verifier |
| The first all-ELF dependency scan expanded an inner `awk $1` in the wrong shell, and the first host package-provider probe exited on a symlink path not owned directly by dpkg | 1 | Re-ran the scan without positional-shell expansion and resolved library symlinks with `readlink -f`; no repository or persistent runtime state changed |
| The long official-package download call returned before completion without preserving its exec session ID, and one follow-up wait command had mismatched nested quotes | 1 | Confirmed the single existing `apt-get download` PID, waited on that exact process without starting a duplicate, and verified all five completed artifacts by SHA-256 |
| The disposable container with all five CUDA runtime packages installed passed Torch/Torchvision imports but the verifier imported `d455_yolo_3d_node.py` solely for constants and failed because direct Python execution had no sourced `rclpy` environment | 1 | Extract producer identity constants into `d455_yolo_protocol.py`; both the ROS node and verifier now import the pure module, and runtime calls explicitly require GPU device `0` |
| The first ROS-free integrated verifier reached the model-class gate and found the locked model has seven classes including `yellow`, while the six-class producer/consumer contract rejected it | 1 | Directly loaded the exact model mapping on Jetson, upgraded the schema to `competition-ad-yellow-red-green-v1`, accepted `yellow`, and locked the complete `class_id -> class_name` mapping |
| One direct SSH Python command was parsed by local PowerShell, and a standalone placement test used system Python without OpenCV | 1 | Re-ran the model mapping probe through Base64 transport and used the established bundled Python 3.12 dependency environment for the authoritative full regression |
| The first formal build dispatch timed out establishing SSH before any remote command ran | 1 | Bounded ping/SSH checks showed transient Tailscale latency; the next dispatch connected normally and completed the exact build/verifier workflow |

## Current Update - 2026-08-16 Phase 132 Jetson ROS build and image readiness
Verify the pushed selective-port commit on the Jetson, establish a clean and exact source checkout, confirm ROS 2 package discovery, and complete a no-runtime colcon build. Audit the unified-image wheel and acceptance requirements in parallel, but do not start perception, camera, navigation, arm, or robot motion.

### Phase 132: Jetson package discovery and build
- **Status:** complete (exact commit `4e103bfe379e349336b0a7ce0b464fdfc929ff27` passed clean four-package Foxy discovery, isolated build, prefix, import, entry-point, and launch-argument checks; unified image remains a separate credential-gated phase)
- [x] Audit Jetson connectivity, storage, ROS distro, repository/worktree state, and inactive camera/motion ownership without changing runtime state.
- [x] Establish or select a clean checkout of exact commit `80bf2549947b44b7470b31e787da6eb2a505214e` without merging any vision branch or disturbing preserved dirty worktrees.
- [x] Run `colcon list` and confirm the root package plus `arm_new_interfaces` and `arm_new_ros` are discoverable using explicit nested-package base paths.
- [x] Run a bounded ROS/colcon build with no launch, camera access, or actuator interaction; capture exact package-level failures if any.
- [x] Audit `build_l6_pick_place_image.sh` inputs and verifier coverage, and determine whether the pinned Torch/Torchvision wheel URLs and SHA-256 values are available.

### Phase 132 Constraints
- No branch merge, cherry-pick, force push, dirty-worktree cleanup, deployment start, Docker runtime start, camera access, ROS route launch, or actuator command.
- Preserve the existing vision worktree and any locally valuable ignored artifacts.
- Report verification levels explicitly: package discovery/build is L2 evidence only and does not imply hardware readiness.

### Phase 132 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Foxy `setup.bash` referenced unset `AMENT_TRACE_SETUP_FILES` while the wrapper had `set -u`, so discovery stopped before `colcon list` | 1 | Source Foxy with nounset disabled, then restore strict mode before running discovery/build commands |
| PowerShell stdin transport appended `\r` to the final explicit colcon base path, so `arm_new_ros` appeared undiscoverable | 1 | Strip carriage returns from every remote script before piping it to Jetson SSH; package metadata itself was present |
| Initial install smoke imported the distribution name `quadruped_robot_competition`, but the root distribution intentionally installs `nodes.*` modules instead of that Python module | 1 | Validate the installed console entry points and import their actual target modules rather than assuming distribution name equals module name |
| Current bundled Codex Python runtime does not include pytest, so the first targeted test command stopped before collection | 1 | Reuse the preserved Phase 130/131 temporary test dependency directory and complete PYTHONPATH rather than installing into the workspace or system runtime |
| Initial wheel-name fix used `packaging.utils.parse_wheel_filename`, but Jetson ships packaging 20.3 where that API does not exist | 1 | Use pip 20.0.2's own `pip._internal.models.wheel.Wheel` parser, verified directly on Jetson with representative aarch64 wheel names |

### Phase 132 Review Findings
- The first isolated Foxy build completed all three requested packages in 56.6 seconds. A formal deploy build must also include `whz`, because `competition.launch.py` resolves it directly; the root manifest currently omits that runtime dependency.
- `cone_inflated_voxel_layer` belongs to its existing pinned overlay and requires the separately pinned NonPersistentVoxelLayer source at `/home/superwfx666/cone_l2_plugin_ws_2_2_1`; it should not be treated as part of the pure Foxy formal install.
- The unified image cannot yet be built: trusted wheel URL/SHA values are absent, and the Dockerfile currently renames wheels to invalid filenames before `pip install`. It also attempts the CUDA-required verifier during `docker build`, before NVIDIA runtime is guaranteed.

## Current Update - 2026-08-16 Phase 131 selective-port review and publication
Review the complete uncommitted selective-port diff, correct any verified defects, repeat the formal local validation and artifact gates, then create and push one reviewed commit on `codex/pick-place-selective-port`. Do not merge, deploy, build the Jetson image, start runtime processes, access the camera, or move actuators.

### Phase 131: Diff review, validation, commit, and push
- **Status:** complete (reviewed commit `80bf2549947b44b7470b31e787da6eb2a505214e` pushed to `origin/codex/pick-place-selective-port`; merge, deployment, Jetson build, and robot runtime remain pending)
- [x] Review every tracked and untracked product change, prioritizing `task_manager.py`, `start_competition.sh`, `competition.launch.py`, and `stop_all.sh`.
- [x] Confirm the forbidden-file, generated-artifact, navigation/Lite3, temporary-extrinsics, model-hash, and preserved-start-script boundaries.
- [x] Apply only necessary review fixes and repeat static, shell, formal regression, and Git whitespace validation.
- [x] Stage an explicit allowlist, inspect the complete staged change, create one local commit, and push only `codex/pick-place-selective-port`.

### Phase 131 Constraints
- No whole-branch merge, cherry-pick, Git cleanup, force push, PR merge, Jetson deployment/build, runtime start/stop, camera access, or actuator interaction.
- Stop before commit if review or validation finds an unresolved safety or packaging defect.
- Preserve the accepted model SHA-256 and the byte-identical `scripts/start_l6.sh` SHA-256.

### Phase 131 Review Findings
- The full-route preset did not start the in-container color relay required by `PlacementObservationBuilder`; it now does so without creating another D455 owner.
- Cached AprilTag, YOLO, and canonical depth observations previously lacked a consumer-side freshness cutoff; all three now expire after the configured manipulation perception timeout.
- Image verification previously loaded the model but did not exercise CUDA NMS, GPU warmup, or the source UDP schema; the unified-image verifier now performs all three without opening the D455.

### Phase 131 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Initial targeted pytest command referenced a bundled Python path that no longer exists | 1 | Loaded the current Codex workspace dependency paths and used the active bundled Python 3.12 runtime |
| First formal pytest retry omitted the repository `arm_new` directory from `PYTHONPATH`, causing two collection import errors | 1 | Reused the complete Phase 130 dependency path including `src` and `arm_new`; the formal suite then passed |

## Current Update - 2026-08-16 Phase 130 selective pick-place port
Implement the approved pick/place capability on the isolated integration branch by importing only audited paths and manually adapting them to the proven DWB architecture. Do not merge or cherry-pick the vision branches, preserve `scripts/start_l6.sh`, and retain one D455-owning Humble container.

### Phase 130: Selective import and DWB integration
- **Status:** complete (selective software port and local validation complete; branch remains uncommitted/unmerged and field calibration/deployment gates remain pending)
- [x] Recover and verify approved source files, including the missing placement-alignment core, without whole-branch operations.
- [x] Import only AprilTag, Foxy UDP bridge, alignment, arm-service, YOLO, model, focused-test, and required metadata paths.
- [x] Adapt the imports to DWB extrinsics, canonical depth snapshots, versioned YOLO schema, `/cmd_vel_precision`, and fail-closed TaskManager service futures.
- [x] Add the one-container pick/place preset and deterministic cleanup while retaining the inspection-only L6 entrypoint unchanged.
- [x] Run static, unit, package, and focused integration validation; record field-calibration gates separately.

### Phase 130 Result
- The selective port is complete in `codex/pick-place-selective-port`; no whole-branch merge, cherry-pick, clean, commit, push, deployment, runtime start/stop, or actuator action was performed.
- `scripts/start_l6.sh` remains byte-identical to the proven baseline with SHA-256 `2c44515757b962e17778e5b7bdb3189b454dda32b5675c79d94dd563f10919d1`.
- The approved model is present at the exact requested path and matches SHA-256 `3ed76de727a87be8d64cc3b259bf2b0ec39daaaa3fac1f3f97af249824abc648`.
- Local formal regression passed `404` tests plus `244` subtests; shell syntax, Python AST, and `git diff --check` also passed. Unbounded pytest still has seven expected hardware/environment collection errors.
- The safe stopping boundary is before commit/merge and before Jetson image/build/runtime validation. AprilTag convention, four distinct I2 values, grasp/release coordinates, place distance, and staged hardware acceptance remain mandatory.

### Phase 130 Constraints
- No `git merge`, `git cherry-pick`, `git clean`, second D455 container, remote deployment, runtime start/stop, or actuator interaction.
- Exclude the parallel competition manager, legacy/diagnostic grasp and placement entrypoints, remote navigation/Lite3/velocity changes, temporary extrinsics, generated output, captures, and calibration-run artifacts.
- Cone UDP stays on `19002`; AprilTag and YOLO use `19003` and `19004`. Only the existing arbiter/cone gate may publish `/cmd_vel`.
- The model must match SHA-256 `3ed76de727a87be8d64cc3b259bf2b0ec39daaaa3fac1f3f97af249824abc648`.

### Phase 130 Source Boundary
- Import from `origin/vision-change` only by explicit path. `placement_alignment_core.py` is absent from all local Git refs and needs recovery from the preserved Jetson worktree or a faithful, separately reviewed reconstruction.
- The existing `Stonefield/nav2-foxy-dwb-integration` baseline is untouched; all work remains in `codex/pick-place-selective-port` until validation is complete.

### Phase 130 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Initial combined PWF patch contained an empty `progress.md` hunk and was rejected atomically | 1 | Split the plan insertion and progress append into separate valid patches; no file changed during the failed attempt |
| Local default and bundled Python runtimes lacked OpenCV/PyYAML, and the default runtime also lacked Ultralytics | 1 | Installed test-only dependencies into a system temporary directory; inspected the model class table with the standard-library ZIP/pickle opcode parser instead of executing the checkpoint |
| Imported AprilTag tests expected IPPE multi-candidate history logic that the recovered core did not contain | 1 | Implemented candidate selection, rotation continuity, and bounded pose-history expiry; all focused core tests then passed |
| Initial all-in-one competition launch patch missed the exact base-to-camera condition context and was rejected atomically | 1 | Split the launch integration into small context-accurate patches; no file changed during the failed attempt |
| Plain `bash -n` was unavailable because Git Bash was not on the Windows PowerShell `PATH` | 1 | Located the installed `C:\\Program Files\\Git\\bin\\bash.exe` and used that explicit executable for shell validation |
| Default Python 3.14 could not use the preserved CPython 3.12 OpenCV/NumPy test dependencies, and initially had no pytest | 1 | Used the bundled Python 3.12.13 runtime and installed pytest only into the existing system temporary test-dependency directory |
| Unbounded `pytest -q` collected hardware/manual scripts requiring live odometry, D455, Torch, ROS2, and legacy module paths | 1 | Restricted the formal software regression to repository `tests/` and `arm_new/tests/`; hardware validation remains a Jetson/field acceptance stage |
| Recursive PowerShell cache cleanup was rejected by the host safety policy before execution | 1 | Switched to verified file-by-file deletion followed by non-recursive removal of empty directories |

## Current Update - 2026-08-16 Phase 129 isolated pick-place worktree creation
Create a new pick/place integration branch and sibling worktree from the L6-proven DWB commit, then copy the complete ignored L1 PWF files into the new worktree without changing current DWB product code.

### Phase 129: Branch, worktree, and L1 context bootstrap
- **Status:** complete (new branch/worktree created at the exact proven baseline and all three ignored PWF files copied with matching SHA-256; no product code or runtime changed)
- [x] Verify source branch/HEAD, clean product state, target absence, branch absence, and PWF source files.
- [x] Create `codex/pick-place-selective-port` at exact baseline `998a4322c517c466317e5cbeb200a463731fff51` in a sibling worktree.
- [x] Copy `task_plan.md`, `progress.md`, and `findings.md` byte-for-byte into the new worktree.
- [x] Verify target branch, HEAD, worktree registration, ignore behavior, PWF hashes, and source isolation.

### Phase 129 Constraints
- Do not switch the current DWB worktree away from `Stonefield/nav2-foxy-dwb-integration`.
- Do not modify product source, build, launch, stop, deploy, or access robot runtime.
- Keep the current and new PWF copies independent after the initial verified bootstrap.

### Phase 129 Result
- New worktree: `C:\Users\111\Desktop\比赛\quadruped-robot-competition-pick-place`.
- New branch: `codex/pick-place-selective-port` at `998a4322c517c466317e5cbeb200a463731fff51`.
- The source DWB worktree remains on `Stonefield/nav2-foxy-dwb-integration` at the same commit.
- All three PWF files are present and ignored in the new worktree; their source/target lengths and SHA-256 hashes matched immediately after copying.

### Phase 129 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| First PowerShell copy-and-hash command used a pipeline directly after `foreach` and failed during parsing with `An empty pipe element is not allowed` | 1 | Confirmed no target file had been written, then collected results in an explicit array before formatting; all three copies and hashes passed |

## Current Update - 2026-08-16 Phase 128 selective-port merge feasibility recheck
Recheck whether the audited Jetson grasp/place assets can be integrated into the L6-proven DWB branch without a whole-branch merge or a second D455 owner. Keep the assessment read-only for product code and preserve `scripts/start_l6.sh`.

### Phase 128: Local Git evidence and source-availability check
- **Status:** complete (selective port remains feasible; whole-branch merge/cherry-pick remains unsafe; no product code, runtime, branch, or remote state changed)
- [x] Reconfirm the clean DWB baseline and exact TaskManager placeholder boundaries.
- [x] Inventory required assets available in local Git refs versus assets only present in the dirty Jetson worktree.
- [x] Check whole-branch conflict/pollution scope and candidate commit granularity.
- [x] Reconfirm required manual adaptations for extrinsics, depth, YOLO schema, precision velocity, arm feedback, and cleanup.

### Phase 128 Result
- Implement on a new integration branch with path-level imports and manual adapters; do not merge the remote branch and do not cherry-pick the 126-file AprilTag commit wholesale.
- Local Git contains committed AprilTag, pick alignment, arm service, YOLO bridge/pipeline, model, and focused tests, but `placement_alignment_core.py` is absent from every inspected remote-tracking ref and must be recovered from the preserved Jetson worktree.
- The committed A-D model is available with the required SHA-256 `3ed76de727a87be8d64cc3b259bf2b0ec39daaaa3fac1f3f97af249824abc648` and is therefore not a source-recovery blocker.
- The committed AprilTag bridge points at the legacy static-extrinsics config, the committed YOLO validator hard-codes the red/green/obstacle ID map, and the pick tuning differs across two remote refs; all require deliberate reconciliation with the DWB contracts.
- The Jetson was offline during this recheck, so no new remote source snapshot was taken. This blocks a complete import, but not preparation of the integration branch or the committed-source subset.

### Phase 128 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Piping binary Git blob data through PowerShell into OpenSSL produced a false SHA-256 because the pipeline converted the byte stream | 1 | Recomputed directly from raw `git cat-file` bytes via Python subprocess; both the requested branch path and current `whz` copy match the required hash |

## Current Update - 2026-08-15 Phase 127 vision-to-DWB merge-plan delivery
Close the requested read-only assessment of which grasp/place/fine-alignment assets from the Jetson vision worktree belong in the proven DWB branch, how to integrate them with one D455-owning container, and whether the resulting design is feasible. Do not implement, merge, build, launch, stop, restart, or move the robot.

### Phase 127: Requirement-by-requirement merge-plan closeout
- **Status:** complete (current DWB source rechecked and prior authenticated Jetson evidence converted into an exact selective-port plan; no product or remote state changed)
- [x] Reconfirm the current DWB branch, TaskManager placeholder boundaries, depth milestones, velocity ownership, container entrypoint, and cleanup behavior.
- [x] Classify the remote AprilTag, pick/place alignment, arm-service, YOLO/model, calibration, launch, runtime, and generated content.
- [x] Define the single-container D455 architecture, unique UDP ports, transform/depth/class contracts, and fail-closed TaskManager wiring.
- [x] Define implementation order and staged acceptance gates, including dependency and calibration blockers.

### Phase 127 Result
- Feasible as a selective port; infeasible as a whole-branch merge or as two D455 containers.
- Preserve `scripts/start_l6.sh` as the proven inspection route and add a separate full pick/place preset.
- Keep the existing DWB TaskManager as the only mission owner; reuse bounded alignment executors and the arm service package, but exclude the parallel competition manager and direct `/cmd_vel` wiring.
- Derive one unified image from `isaac_ros_cuvslam_runtime:humble-rs-cone`, make it the sole RealSense owner, and run AprilTag/optional YOLO inside that container with Foxy UDP bridges on `19003/19004`; cone remains on `19002`.
- Production enablement remains gated by a locked JetPack-compatible YOLO environment, one accepted AprilTag ID/size convention, four distinct I2 poses, calibrated A-D/release targets, and successful isolated pick/place segment evidence.

### Phase 127 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| One local PowerShell path-extraction pipeline ended with an empty pipe element | 1 | Re-ran with an explicit collection variable and sorted the collected paths; no remote command or file mutation occurred |
| Fresh Jetson liveness checks remained unreachable despite the operator recovery report | 1 | Used the completed authenticated Phase 124-126 evidence for the requested merge design and clearly retained the live-state freshness boundary; no remote command arrived |

## Current Update - 2026-08-15 Phase 126 Jetson vision worktree Git hygiene audit
Determine how to make `/home/superwfx666/worktrees/quadruped-vision-yolo-refactor` clean and aligned with GitHub without committing, pushing, deleting, resetting, or changing the active runtime.

### Phase 126: Read-only Git synchronization assessment
- **Status:** complete (live Git refs, tracked diffs, untracked inventory, and dry-run cleanup scope audited; no remote state changed)
- [x] Reconfirm branch, HEAD, upstream, remotes, shared-worktree layout, and live GitHub refs.
- [x] Count and classify tracked, untracked, and ignored content without fetching or modifying refs.
- [x] Identify destructive cleanup hazards and define non-destructive synchronization options.
- [x] Stop before commit, push, reset, clean, stash, fetch, branch switch, or file deletion.

### Phase 126 Post-audit connectivity note
- At `2026-08-15 22:57 +08:00`, a fresh read-only liveness check did not reach the Jetson: Tailscale SSH returned `502 Bad Gateway`, and Tailscale ping, TCP port 22, and ordinary SSH timed out.
- The completed Git/source audit remains valid from the earlier authenticated session. A new live-state recheck is pending only until the Jetson is continuously reachable; no failed attempt changed remote state.

### Phase 126 Result
- The current branch `feature/vision-change-jetson-test` is local-only and has no upstream or same-named GitHub branch, so synchronization requires selecting an existing GitHub branch as the canonical target.
- The worktree contains 34 unstaged tracked modifications (`+1221/-294`) and 142 individual untracked files (about 38.5 MB); the earlier count of 66 was collapsed status entries, not the full file count.
- Untracked content includes substantial source, tests, calibration, AprilTag assets, and documentation. Blanket `git clean -fd` would destroy useful work, while `git clean -fdx` would additionally delete the ignored A-D model and local hardware configuration.
- Recommended path: preserve this checkout as a source snapshot and create a separate clean worktree tracking the chosen GitHub branch. In-place reset/clean is acceptable only after an external patch/archive/manifest backup and an explicit target-branch decision.

### Phase 126 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| First remote audit wrapper conflicted with JavaScript template interpolation before SSH | 1 | Rebuilt the transport as an ASCII Base64 script; no remote command ran in the failed attempt |
| Jetson SSH/Tailscale became intermittent during two follow-up reads | 2 | Used the completed live Git audit plus the same-day preserved source/runtime inventory; no mutation was attempted |

## Current Update - 2026-08-15 Phase 124 Jetson vision worktree integration audit
Read-only audit `/home/superwfx666/worktrees/quadruped-vision-yolo-refactor` after operator-completed authentication. Determine which grasp, placement, and visual fine-alignment assets should be integrated into the current DWB branch, with one Docker container as the sole D455 owner. Do not modify either checkout, merge, build, launch, stop, or restart any runtime.

### Phase 124: Remote source/runtime evidence and integration matrix
- **Status:** complete (read-only source/runtime audit completed; no merge, build, launch, stop, or remote write performed)
- [x] Reconfirm remote branch, HEAD, dirty state, and active D455/runtime ownership.
- [x] Audit current DWB RGB-D milestone behavior and the vision worktree's grasp/place/alignment contracts.
- [x] Classify files as direct additions, manual ports, calibration-gated assets, or excluded content.
- [x] Produce a staged single-container implementation and validation sequence without performing mutations.

### Phase 124 Constraints
- Remote inspection is read-only; preserve the dirty vision worktree and all active processes/containers.
- Do not merge, build, deploy, launch, stop, restart, publish velocity, initialize Lite3, or access the actuator path.
- Treat the operator-reported `scripts/start_l6.sh` pass as the current DWB baseline and preserve that inspection-only mode while designing the later full route.

### Phase 124 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Remote Jetson does not have `rg` installed for bounded log search | 1 | Use scoped `find` plus `grep` for any remaining evidence search; no remote state changed |
| Remote read-only image-layer Python here-doc consumed its terminator and ended with `NameError: PY` after printing the requested values | 1 | Retain the already printed 63-layer comparison; do not repeat because no additional image fact is needed and no remote state changed |
| One bounded remote `sed` path retained a carriage return and one `head` pipeline parsed an invalid option | 1 | The affected legacy-place/host-YOLO excerpts were nonessential; use the already recovered executor and Docker-node interfaces instead, with no remote state change |

### Phase 124 Result
- Preserve the proven inspection L6 preset unchanged and add a separate full-route preset.
- Import the isolated AprilTag/alignment/arm/model source and tests deliberately; adapt depth metadata, YOLO class/UDP contracts, TaskManager feedback, and precision velocity wiring by hand.
- Do not merge the dirty vision branch or run its parallel competition manager.
- Calibration and segment-level field evidence remain mandatory before a full pick/place L6 run.

## Current Update - 2026-08-15 Phase 125 executable merge-plan closeout
Close the remaining image-dependency, unified-startup, cleanup, and staged-acceptance gaps for the read-only vision-worktree audit. Do not implement, merge, build, launch, stop, or restart any product runtime.

### Phase 125: Single-container implementation and validation plan
- **Status:** complete (final read-only dependency/runtime checks completed; no product source or remote state changed)
- [x] Inspect the YOLO image history and installed Python dependency versions.
- [x] Validate whether the in-container Humble 3-D YOLO entrypoint is currently runnable.
- [x] Define the single-D455-owner startup and fail-closed cleanup order.
- [x] Define direct-add, manual-port, calibration-gated, and excluded file groups.
- [x] Define staged acceptance from local tests through full-route L6.

### Phase 125 Result
- The dirty vision worktree remains a source quarry, not a mergeable branch.
- The current in-container 3-D YOLO path is not production-ready: image `torchvision 0.19.1` requires `torch 2.4.1`, but the Jetson image has NVIDIA `torch 1.13.0a0`; the default import fails before the NMS fallback can be installed.
- The read-only host mount contains a compatible `torch 2.0.0 + torchvision 0.15.1` pair, but `run_yolo_3d_node.sh` does not add `/opt/host-python` to `PYTHONPATH`. A derived cone image must explicitly pin and validate one compatible dependency set before YOLO is enabled.
- Preserve the existing inspection-only `start_l6.sh`; implement pick/place through a separate preset, one container, three non-conflicting UDP ports, current DWB extrinsics, `/cmd_vel_precision`, and explicit TaskManager/arm-service feedback.
- Calibration remains the field blocker: AprilTag ID/size convention, four distinct I2 poses, A-D placement poses, and release target must be measured and accepted before segment-motion or full-route tests.

## Current Update - 2026-08-15 Phase 123 operator-confirmed full L6 pass
The operator confirms that one subsequent field run launched with `bash scripts/start_l6.sh` completed the full L6 workflow successfully. This closes the outstanding practical full-run acceptance boundary for the pure-start entrypoint.

### Phase 123: Pure-start full-route field acceptance
- **Status:** complete (operator-reported full L6 pass using `scripts/start_l6.sh`; no independent log or rosbag audit was performed in this session)
- [x] Execute the delivered pure-start L6 entrypoint on the robot.
- [x] Complete the full L6 run successfully.
- [x] Correct the project status from "awaiting a full-route field test" to "operator-confirmed field pass."

### Phase 123 Evidence Boundary
- Source: direct operator report on 2026-08-15.
- This establishes the practical field result; audit-grade timing, waypoint, inspection, and telemetry details remain unverified unless the corresponding runtime artifacts are inspected separately.

## Current Update - 2026-08-15 Phase 122 pure-start L6 mode
Make the operator `start_l6.sh` path start the required L6 runtime and then return without running post-launch ROS CLI acceptance checks. Keep all other `start_competition.sh` modes unchanged.

### Phase 122: Pure-start operator path
- **Status:** complete (implemented, committed, pushed, and cleanly deployed at `998a432`; no runtime was started)
- [x] Make `start_l6.sh` explicitly select pure-start mode.
- [x] Start the pure L6 TaskManager armed so its existing internal readiness gate owns mission start.
- [x] Return immediately after the competition launch PID is created, before TaskManager polling, node/topic inspection, CPU output, and runtime acceptance.
- [x] Preserve the default delayed-arm acceptance path for all non-pure starts.
- [x] Pass local `310/310`, Jetson Bash syntax, and Jetson focused `20/20` validation; deploy with a clean strict fast-forward.

### Phase 122 Constraints
- Do not add retries, longer CLI timeouts, rosbag, supervisor, phase monitor, or other post-launch checks to the pure path.
- Do not change the route, map, timeout budgets, retry policy, Nav2/DWB/costmap/perception tuning, or TaskManager internal readiness gate.
- Do not start the L6 runtime during implementation or deployment; the operator runs it manually.

### Phase 122 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Local Windows has no `bash` command | 1 | Parsed both modified scripts with Jetson `bash -n -s`; both passed without writing or executing them |
| First full unittest command omitted `PYTHONPATH=src` and produced 10 import-collection errors | 1 | Re-ran with the repository source path; all `310/310` tests passed |
| Two local Base64 attempts used unavailable JavaScript APIs before SSH, then the first delivered deploy script used an unverified full commit suffix | 3 | No worktree update occurred; used PowerShell Base64 transport, read the exact local/remote hashes, and then completed a strict fast-forward to the verified commit |
| First PWF append used an imprecise historical sentence as its patch anchor | 1 | The patch was atomic and changed nothing; re-anchored on the existing Phase 121 headings and appended the same records |

## Current Update - 2026-08-15 Phase 121 clean operator-run L6 entrypoint
Replace the external rosbag/supervisor workflow with one minimal operator-run L6 script. The entrypoint must invoke only the existing formal startup chain, keep its fail-closed acceptance and delayed mission arming, and start no recorder or supervisory process.

### Phase 121: Clean one-click L6 script
- **Status:** complete (committed, pushed, and cleanly deployed at `82cb83f`; the operator entrypoint starts only the existing formal L6 chain and was not executed)
- [x] Add a single no-argument L6 entrypoint with the formal map and `180/120/300 s` timeout contract.
- [x] Prove the entrypoint contains no rosbag, supervisor, nohup, or auxiliary monitoring path.
- [x] Update the operator documentation and run focused/static regression checks.
- [x] Make the script available in the clean formal Jetson deploy without starting L6.

### Phase 121 Constraints
- Do not start rosbag, a supervisor, nohup/background monitoring, or a new L6 attempt.
- Do not change the calibrated route, map, Nav2/DWB/costmap/perception tuning, retry policy, TaskManager arming gate, or existing startup acceptance gates.
- The user will execute the delivered script manually; this phase must not initialize Lite3 motion or start the competition runtime.

### Phase 121 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Jetson `bash -n /dev/stdin` returned permission denied because Bash attempted to open the device path as a script file | 1 | Re-ran syntax parsing with `bash -n -s`, which reads standard input directly and passed without writing or executing the script |
| The first Jetson focused unittest command imported `tests.test_formal_startup_chain`, but the remote `tests/` directory is not a Python package | 1 | Switched to unittest discovery for the same file; all `19/19` focused tests passed |

## Current Update - 2026-08-15 Phase 120 one-shot formal L6 re-acceptance
Execute exactly one newly authorized supervised formal Cone-to-WHZ L6 run at `86f589d` to validate the QoS-correct recorder, post-acceptance TaskManager arming gate, startup-order gate, and `180/120/300 s` timeout policy in the real duty cycle. Preserve the calibrated nine-goal route, navigation/perception tuning, zero retry counts, and fail-closed cleanup.

### Phase 120: One-shot supervised L6 re-acceptance
- **Status:** complete (exactly one formal attempt ran and was stopped fail-closed after the supervisor misclassified the launcher's normal post-GO exit as `LAUNCHER_EXIT`; the result is invalid/inconclusive rather than an L6 PASS or product ABORT, and no retry was started)
- [x] Complete local L0/L1, Jetson L2, isolated L3 mission-arm, and real-D455 no-actuation L4 validation at exact `86f589d`.
- [x] Reconfirm clean formal deploy, zero competing processes/containers/control ports, and clean Jetson Git state.
- [x] Receive explicit confirmation that the robot is back at the formal start pose.
- [x] Execute exactly one formal L6 attempt with the QoS-correct recorder and no automatic retry.
- [x] Preserve terminal evidence, perform exact teardown, and report route/inspection/motion/rosbag/audit results.

### Phase 120 Constraints
- This authorization permits one run only. Any terminal PASS/ABORT/fault ends the attempt; do not rerun automatically.
- Do not change route, map, DWB, costmaps, localization, perception, timeout budgets, retry counts, or inspection behavior during the run.
- Do not start the actuator-capable command until the operator explicitly confirms the robot is back at the formal start pose.

### Phase 120 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| First local precheck transport embedded a PowerShell backtick in a JavaScript template and failed before command execution | 1 | Removed the backtick construct; no SSH, Jetson, ROS, or actuator state was changed by the failed call |
| First supervisor-generation transport exposed Bash `${STAMP}` to JavaScript interpolation and failed locally before SSH | 1 | Used an unambiguous Bash variable form without JavaScript interpolation; the generated supervisor then passed syntax and focused transformation checks |
| The generic `RealSense.*455` USB-name probe did not match the D455's hub-style `lsusb` name | 1 | Revalidated with exact USB ID `8086:0b5c`, the V4L2 RealSense D455 identity, stable by-id links, and six video nodes |
| One read-only launcher-tail command lost its remote path variable through PowerShell quoting | 1 | Reissued the bounded read through the established standard-input Bash transport; no remote state changed |
| The inherited supervisor treated the normal post-GO `start_competition.sh` exit as a runtime fault | 1 | It stopped the first goal fail-closed and completed exact cleanup; classify this attempt as invalid/inconclusive, preserve evidence, and require a newly authorized run with a supervisor that monitors the competition child/terminal phase instead of launcher lifetime |

## Current Update - 2026-08-15 Phase 119 formal L6 evidence and arming gate
Fix the Phase 118 supervisor-side rosbag QoS incompatibility and prevent TaskManager from advancing before every formal startup acceptance gate has passed. Preserve the calibrated nine-goal route, navigation/perception tuning, zero retry counts, and `180/120/300 s` timeout policy. Validate without actuation, then stop for a new L6 authorization.

### Phase 119: QoS-correct recording and post-acceptance mission arming
- **Status:** complete (commit `86f589d` published/deployed; local L0/L1, Jetson L2, isolated L3 mission-arm, and real-D455 no-actuation L4 validation passed; runtime stopped cleanly)
- [x] Reconstruct both Phase 118 terminal results and identify the second run's `NO_GO` trigger.
- [x] Require the checked-in Foxy rosbag QoS override for `/cone_obstacle/scan` in the next formal supervisor.
- [x] Add a default-compatible `mission_start_armed` parameter and launch the formal L6 TaskManager disarmed.
- [x] Arm TaskManager only after lifecycle, QoS, plugin, health, route, retry, and timeout gates all pass; verify the live parameter transition.
- [x] Add focused regression tests and run the complete local regression suite.
- [x] Commit/publish/deploy the focused fix and complete Jetson L2 plus no-actuation L4 validation.
- [x] Stop with a clean runtime and await a new, separate L6 authorization.

### Phase 119 Constraints
- Do not change route, map, DWB, costmaps, localization, perception, timeout budgets, retry counts, or inspection behavior.
- Do not start TaskManager armed on the formal L6 path, initialize Lite3 motion, send a navigation goal, or publish nonzero velocity during implementation/L2/L4 validation.
- Do not automatically run another L6 after the fix; a new motion authorization and fresh physical safety confirmation are required.

### Phase 119 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| ByteRover CLI is unavailable on this Windows host | 1 | Reused the repository PWF history, including the prior Foxy rosbag BEST_EFFORT finding, and continued under the user's explicit fix request |
| Parallel Tailscale SSH evidence reads triggered an additional browser authentication challenge; direct LAN SSH timed out | 1 | Retained the already recovered Phase 118 evidence summary and successful read-only directory inventory; no remote process or file was changed |
| First full local unittest invocation omitted the repository's required `PYTHONPATH=src`, causing 10 collection-time `ModuleNotFoundError: nodes` errors | 1 | Re-ran with `PYTHONPATH` resolved to the repository `src`; all 308 tests passed |
| First combined evidence read used a nested remote `awk` expression whose quoting was altered by PowerShell | 1 | Switched to bounded `sed`/`grep` reads; recovered the original supervisor, launcher, TaskManager, and rosbag evidence without remote mutation |
| First strict-fast-forward command embedded nested Bash variables directly in a PowerShell double-quoted SSH command and reached the remote shell with a malformed `git -C` path | 1 | Confirmed remote HEAD/worktree/rollback branch were unchanged, then resent a UTF-8 script over standard input; strict fast-forward to `86f589d` succeeded |
| Isolated-domain Foxy CLI parameter discovery did not find the directly started TaskManager and an interrupted SSH session did not trigger its remote trap | 1 | Stopped the exact run-owned PID `24744`, replaced the CLI-daemon-dependent harness with an in-process rclpy graph test, and confirmed zero residue |
| The successful in-process L3 wrapper ended with a transported `exit 0\r` and Foxy printed an ActionClient destruction warning after node shutdown | 1 | Used the persisted `harness_rc=0` plus all runtime assertions as the authoritative result; no product process or ROS entity remained |

## Current Update - 2026-08-15 Phase 118 formal L6 startup-order acceptance
Execute exactly one newly authorized supervised formal Cone-to-WHZ L6 run at `1881fd9` to validate the Phase 117 startup-order gate and the Phase 116 per-waypoint timeout policy in the real duty cycle. Preserve the calibrated nine-goal route, all navigation/perception tuning, zero retry counts, and fail-closed cleanup.

### Phase 118: One-shot supervised L6 acceptance
- **Status:** complete (the first authorized attempt aborted after a D455 obstruction; the separately authorized retry completed 5 navigation goals and 1 inspection before the supervisor reported `NO_GO` from its incompatible rosbag scan subscription; full-route acceptance was not achieved)
- [x] Reconfirm local/Jetson provenance, clean runtime, hardware availability, formal route, and timeout/retry contracts.
- [x] Receive fresh confirmation that the robot is at the formal start, the full route is clear, supervision is continuous, and the hardware e-stop is immediately accessible.
- [x] Execute the authorized formal attempts with rosbag, logs, runtime probes, and no automatic rerun.
- [x] Stop and await the exact launcher, close the bag, issue the established stop path, and audit processes/containers/control ports/Git.
- [x] Analyze startup readiness, navigation/inspection progress, motion evidence, rosbag integrity, and terminal results.

### Phase 118 Constraints
- This authorization permits one run only. Any terminal PASS/ABORT/fault ends the attempt; do not rerun automatically.
- Do not change route, map, DWB, costmaps, localization, perception, timeout budgets, retry counts, or motion preparation behavior during the run.
- Do not start the actuator-capable command until the four physical safety conditions have been freshly confirmed by the operator.

### Phase 118 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| First read-only route probe used a remote Python here-doc whose terminator acquired a transport line-ending mismatch and ended with `NameError: name 'PY' is not defined` after printing partial results | 1 | Re-ran the route validator as a single-line Python command; no ROS process, container, actuator, or Jetson file was changed |
| First formal attempt reached motion but the operator identified an unnoticed obstruction covering the D455 | 1 | Preserved the terminal `ABORT`, performed exact teardown, accepted the operator's physical root-cause statement, and did not investigate unrelated software causes |
| Retry supervisor recorded `/cone_obstacle/scan` with Foxy rosbag's default RELIABLE subscription, conflicting with the BEST_EFFORT publisher and costmap subscribers | 1 | Preserve the valid 5-goal/1-inspection run evidence; require `configs/ros/cone_rosbag_qos.yaml` for the next recorder and add a formal post-acceptance mission arming gate |

## Current Update - 2026-08-15 Phase 117 Nav2-before-mission startup gate
Eliminate the formal Phase 116 L6 startup race where TaskManager requested mission-start `AVOIDANCE` before Nav2 had activated the global costmap. Preserve route, timeout budgets, retry counts, costmap/controller parameters, and fail-closed behavior. Validate through the strongest no-actuation level available, then stop at the L6 authorization boundary.

### Phase 117: Deterministic mission-start readiness ordering
- **Status:** complete (startup-order fix committed/pushed/deployed at `1881fd9`; local L0/L1, Jetson L2, and formal no-actuation L4 passed; stopped before L6 and awaiting a new, separate field-motion authorization)
- [x] Confirm the exact TaskManager, NavigationClient, launch, and cone applied-revision timing contract.
- [x] Add a fail-closed Nav2 readiness gate before the initial depth-mode request, with focused regression tests.
- [x] Run local static/unit regression and ROS 2 skill validators.
- [x] Commit/publish the focused fix and validate the clean formal Jetson deploy without actuation.
- [x] Stop before any L6 motion run and request a new, separate authorization.

### Phase 117 Constraints
- Do not change waypoints, costmaps, inflation, DWB, localization, timeout values, inspection behavior, or retry counts.
- Do not initialize Lite3 motion, send a NavigateToPose goal, publish nonzero velocity, or execute L6 without a new user authorization.

### Phase 117 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| ROS 2 launch validator used the Windows GBK default codec and could not read the UTF-8 Chinese launch file | 1 | Re-ran with `PYTHONUTF8=1`: 0 errors; six pre-existing conditional duplicate-name warnings remain |
| First Jetson strict-fast-forward guard used an incorrectly expanded full hash for short commit `1881fd9` | 1 | Guard stopped before deploy HEAD/worktree changes; read the exact local full hash and retry with that verified value |
| First Phase 117 L2 wrapper contained unescaped Bash `${...}` inside the local JavaScript template | 1 | Local parser stopped before SSH; escape the two Bash expansions and resend, with no Jetson state to recover |
| First Phase 117 L4 evidence path used `$stamp_phase...`, which Bash parsed as one undefined variable and resolved to the parent evidence directory | 1 | Interrupted during Docker startup, terminated exact cuVSLAM wrapper PID `26567`, ran repository cleanup, and confirmed zero process/container/control-port/Git residue; retry with `$(date ...)_phase...` |
| Two resumed-session read-only PowerShell statistics used a `foreach` block directly before a pipeline and raised `EmptyPipeElement` | 1 | Collected objects into an array before `Format-Table`; no repository, Jetson, or runtime state changed |

## Current Update - 2026-08-15 Phase 116 pass-obstacle timeout hardening
Fix only the timeout behavior proven by the formal `48072d9` L6 evidence. Preserve all waypoints, costmaps, DWB/controller settings, localization, depth transitions, retry counts, and inspection behavior. Give each of the three pre-inspection navigation goals an independent deadline while retaining a bounded aggregate phase deadline, then validate locally and on the clean formal Jetson deploy without actuation.

### Phase 116: Per-waypoint timeout plus aggregate phase cap
- **Status:** complete (timeout implementation and L0-L4 validation passed at `44d3962`; the separately authorized formal L6 execution ended fail-closed in `START` before any navigation goal or nonzero velocity because the global cone-layer applied-revision acknowledgement missed the mission-start readiness deadline; full-route L6 acceptance was not achieved)
- [x] Add a 120 s per-waypoint timeout for `PASS_OBSTACLE` and raise only its aggregate phase cap from 120 s to 180 s.
- [x] Add focused timeout-state tests and update launch/startup parameter contracts.
- [x] Run local L0/L1 validation and repository regression tests.
- [x] Commit/publish the focused change and strict-fast-forward the clean formal Jetson deploy.
- [x] Run Jetson L2 build/tests and an isolated no-actuation TaskManager parameter gate.
- [x] Run an L4 no-actuation provenance/parameter/startup gate with the real D455/Nav2 stack.
- [x] Stop before L6 motion; obtain a new, separate authorization for any supervised field run.
- [x] Execute the single authorized formal L6 attempt with no automatic retry; preserve the terminal `ABORT`, zero-motion evidence, rosbag, and four-part cleanup audit.

### Phase 116 Constraints
- Do not change waypoints, costmaps, inflation, DWB, localization, depth milestones, inspection timeout, or retry policy.
- Do not initialize Lite3 motion, send a NavigateToPose goal, publish nonzero velocity, or perform L5/L6 motion without separate authorization.

### Phase 116 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| The first Jetson regression wrapper ran from the wrong test directory without the repository root on `PYTHONPATH`, causing two `scripts` import errors | 1 | Re-ran from the repository root with the established `PYTHONPATH`; Jetson passed all `300/300` tests and the Foxy build |
| The isolated TaskManager wrapper tracked the short-lived `ros2 run` parent PID instead of its Python child | 1 | Verified the exact installed child command, stopped only that PID, stopped the isolated-domain daemon, and confirmed zero process/container/control-port/Git residue |
| PowerShell standard-input transport appended a carriage return to the remote script's final command | 2 | Made a comment the final transmitted line so the CR cannot alter a path or executable command |
| The outer L4 wrapper exited during redundant post-GO ROS CLI capture and therefore did not emit its own initial summary | 1 | The repository's formal startup had already returned rc 0 and persisted its complete GO snapshot; preserved that evidence, verified exact cleanup and source/install identity independently, then rebuilt an explicit summary without rerunning hardware |
| Final read-only line-reference search included the obsolete path `tests/test_task_manager_contract.py` | 1 | Re-ran against the actual `tests/test_task_manager_depth_contract.py`; all expected timeout/reset/startup contracts were present |
| The formal L6 TaskManager requested mission-start `AVOIDANCE` before Nav2 activation completed; the global cone-layer applied revision did not arrive within the readiness deadline | 1 | TaskManager fail-closed in `START`, sent zero goals and zero nonzero velocities; supervisor performed exact teardown, no retry was launched, and the unrelated startup-order issue was left unchanged under the timeout-only scope |
| Two read-only inline SSH/Python commands lost quoting while decoding bag velocity samples | 1 | Did not repeat the inline form; sent the same read-only Python through standard input and verified all 562 `/cmd_vel` samples were exactly zero |
| The final live process audit's inline remote `awk` expression lost quoting | 1 | Replaced it with a read-only Python process scan sent through standard input; live relevant-process count was zero |

## Current Update - 2026-08-14 Phase 115 source-specific cone inflation
Decouple static-map inflation from cone-scan inflation on the pinned Foxy/Nav2 stack. Add a standalone `ament_cmake` costmap plugin derived from the installed NonPersistentVoxelLayer contract, keep the base static inflation at `0.30 / 3.0`, apply `0.60 / 2.0` only to cone observations, make runtime disable acknowledgement reflect applied costmap state, and preserve the existing Python package boundary.

### Phase 115: ConeInflatedVoxelLayer implementation and validation
- **Status:** in_progress (implementation plus L2/L3/L4 are complete; the one authorized formal L6 motion attempt at `48072d9` ended in `ABORT` after waypoints 1-2 succeeded and the shared 120 s pass-obstacle phase timeout expired during waypoint 3; no further motion is authorized)
- [x] Confirm the repository package layout, installed Foxy 2.2.1 costmap/plugin APIs, existing overlay build path, and current Safety Gate contracts.
- [x] Add `ros2_plugins/cone_inflated_voxel_layer` with plugin XML, CMake/package metadata, implementation, and focused C++ unit tests.
- [x] Update production and experimental Nav2 overlays so generic inflation remains `0.30 / 3.0` and cone-local inflation owns `0.60 / 2.0` or `0.75 / 1.5`.
- [x] Add runtime enabled-parameter handling, directional stale-halo cleanup, and local/global applied-state acknowledgement; update Safety Gate to wait for both acknowledgements and remove full-costmap clears only after tests prove cleanup.
- [x] Update `start_competition.sh` provenance/build checks and repository contract tests without changing waypoints, localization, goal tolerances, or mission timeouts.
- [x] Run available L0/L1 validation locally; L2/L3 are unavailable on this Windows host because no Foxy/colcon environment is installed. Leave L4/L6 for separately authorized Jetson/field validation.
- [x] Add `FollowPathCone`, the cone-specific BT XML, and waypoint-to-BT selection so only `obstacle_cross_target` uses the cone DWB profile.
- [x] Run second-stage regression and create the separate DWB-decoupling commit.
- [x] Run isolated Foxy L2 build/gtest/configure-only validation and L3-S synthetic graph/fault-injection validation. L3-S ran inside an unprivileged network namespace with loopback only and no route to any actuator network.
- [x] Run one continuous real-D455 L4 clear/cone/clear acceptance with zero `/cmd_vel` subscribers, verify source-specific costmap marking and cleanup, applied-state disable/re-enable acknowledgement, timing, rosbag integrity, A/B resources, and exact teardown.
- [x] Obtain separate authorization before any L6 motion run; the operator confirmed the map start, clear surroundings, continuous supervision, and immediate hardware e-stop access.
- [x] Execute one formal L6 motion attempt with no automatic retry, evidence capture, and exact teardown (terminal `ABORT` during waypoint 3; full-route acceptance not achieved).
- [ ] Obtain a new, separate authorization before any further L6 motion attempt.

### Phase 115 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| ByteRover MCP was unavailable and `brv` was absent from PATH/common install locations; the repository also has no `.brv` directory | 1 | Recorded the environment limitation and continued from the existing PWF history because the user explicitly authorized this implementation |
| Local Python environments do not contain pytest or PyYAML, and no `colcon`/Foxy runtime is installed | 1 | Used the repository's unittest suite, compileall, XML parsing, Bash syntax, diff checks, and ROS 2 static validator; explicitly deferred C++ build/L2+ validation |
| The first ROS 2 engineering skill read used the `.agents` root instead of the registered `.codex` skill root | 1 | The read-only command changed nothing; reloaded the complete skill from `C:\Users\111\.codex\skills\ros2-engineering-skills\SKILL.md` |
| The local host has neither Docker nor an installed WSL distribution, so a hardware-independent Foxy container cannot be used | 1 | Kept the repository unchanged and evaluated the isolated Jetson path instead |
| Jetson preflight found unrelated actuator-capable runtime already active, so concurrent build/L2/L3 execution would violate the acceptance runbook and risk resource interference | 1 | Performed no remote mutation, launch, build, process stop, or ROS publication; wait for that runtime to finish and for operator isolation confirmation |
| The first remote L2 build wrapper used a 1-second local SSH timeout | 1 | Read-only follow-up proved the script never reached the Jetson: no build process and no evidence directory existed. Retry once with a normal long command timeout |
| The first delivered L2 script enabled Bash nounset before sourcing the Foxy setup file, which reads optional `AMENT_TRACE_SETUP_FILES` | 1 | The script stopped before CMake. Source Foxy/overlay setup files with nounset temporarily disabled, then restore strict mode |
| The first real Foxy build failed because the derived plugin target did not receive PCL include paths required by the pinned base header | 1 | Added direct PCL/pcl_conversions CMake and package dependencies, mirrored the pinned package's PCL component/link handling, and added a repository contract assertion |
| The first `colcon test --packages-select cone_inflated_voxel_layer` discovered zero packages because the plugin source is outside the overlay's default `src` directory | 1 | Added the same explicit `--base-paths` used for build; Jetson then ran all 4 gtests successfully |
| Temporary remote patch transport hit nested-shell quoting, PowerShell line-joining, and one transient Tailscale SSH 502 before any patch applied | 3 | Switched to authenticated system OpenSSH plus exact-file `scp`, then verified the remote Git diff matched the three intended files |
| The first configure-only wrapper stopped the ROS 2 daemon and then issued an unbounded lifecycle query before restarting discovery | 1 | Outer timeout triggered the trap and left no process; explicitly start the domain-93 daemon and bound every CLI call |
| Foxy `nav2_planner/planner_server` defaults its node name to `/nav2_planner`, while the runbook and parameter root require `/planner_server` | 1 | Add `-r __node:=planner_server` to the configure-only command and assert it in the L2/L3 contract test |
| The first push of the PCL fix used the user's inactive `127.0.0.1:6696` Git proxy | 1 | Retried the single push with temporary per-command empty proxy settings; did not change global Git configuration |
| The first clean-sync script guessed the full `a307b54` hash incorrectly | 1 | Validation stopped before file changes; queried the real local full hash and reran the verified reverse-diff/fast-forward sequence |
| The first Phase 115 L4 startup passed its D455 UDP preflight but Foxy rejected the empty optional launch token `waypoint_file:=` before Nav2 started | 1 | Build launch arguments as an array and append `waypoint_file` / `expected_map_id` only when non-empty; commit `c730f85` passed local and Jetson `294/294` and the second startup reached GO |
| Windows could not reach GitHub while publishing `c730f85`, and Jetson SSH later became unavailable immediately before `CONE_IN` capture | 1 | Transferred the exact commit through a verified Git bundle; a Jetson reboot ended the run before `CONE_IN`, so the 47 MB bag was marked discontinuous and preserved, generated parameter dumps were moved into evidence, the worktree was restored clean, and Jetson later pushed `c730f85` to origin |
| The first continuous-run timing analyzer followed only the original cone beams `91-103`, so it stopped the clock while the cone/operator was still moving across the scan and falsely reported local cleanup as `2658.857 ms > 2500 ms` | 1 | Preserved the v1 result, then used 97 clear-before scans plus full-scan contiguous-cluster tracking to follow the physical removal through beams `167-171`; final local/global timing is `2068.409/2595.241 ms`, both within threshold |
| Signaling only the top-level L4 launch processes left eight orphaned Foxy children because they had inherited the unrelated Tailscale process group | 1 | Never signaled that shared process group; resolved and terminated only the exact remaining PIDs, then verified no relevant process, running container, control port, or Git change |
| The first resource comparison treated baseline A's low-load dynamic CPU scaling below 1420 MHz as thermal throttling | 1 | Corrected the criterion to evaluate sustained frequency loss under high-load cone mode B; all 59 B samples stayed at 1420 MHz, maximum CPU temperature was 36.5 C, swap was zero, and the kernel log had no OOM event |
| Resource wrappers hit Windows/SSH quoting, Foxy setup under nounset, and buffered `ros2 topic hz` output before measurement completed | 3 | Switched complex remote commands to base64 standard-input transport, sourced Foxy before enabling nounset, and used `PYTHONUNBUFFERED=1`; incomplete attempts were excluded from the final evidence |
| The first Phase 115 L6 preflight wrapper used a JavaScript `btoa` helper that is unavailable in the command orchestrator | 1 | The failure occurred locally before SSH execution; switched to the previously validated PowerShell standard-input transport and confirmed zero remote state change |
| The first successful L6 audit targeted the historical dirty development checkout rather than the formal deploy clone | 1 | Treated it as NO-GO, changed nothing, enumerated repository/worktree candidates, and located the clean formal deploy at `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy` on exact `c730f85` |
| A read-only historical-evidence listing used a transmitted Bash `for` block that arrived incomplete and ended with `unexpected end of file` | 1 | The command changed nothing and returned only the directory names; replaced it with a single bounded `find` command |
| The first L6 execution wrapper was rejected locally because JavaScript interpolated Bash `${stamp}` before SSH | 1 | No remote command ran; escaped the Bash brace expressions before retrying |
| The first remote L6 startup's rosbag command line contained `/cmd_vel_arbiter/mode`, so `start_competition.sh` `[0/6]` broad cleanup `pkill -f cmd_vel_arbiter` killed the recorder | 1 | The supervisor failed closed before Lite3 preparation or TaskManager launch. Remove that topic from the recorder command line while retaining `/cmd_vel*`, and terminate the exact top-level launcher PID before cleanup on every exit |
| The corrected L6 supervisor was not dispatched because a PowerShell carriage-return replacement used a backtick inside the JavaScript template string, causing local `SyntaxError: Unexpected identifier 'r'` | 1 | No SSH or remote command ran; replace it with `$remoteScript.Replace([string][char]13, '')` and retain escaped Bash `${...}` expressions |
| The first wrapper cleanup did not signal the still-running top-level `start_competition.sh`, allowing its cuVSLAM child to create a container after the wrapper's initial audit | 1 | Performed immediate exact-PID and exact-container recovery, sent another direct Lite3 zero burst, and verified zero relevant process/container/control-port residue; the corrected supervisor signals and waits for the launcher before its remaining teardown |
| The corrected supervisor's initial already-running guard matched its own SSH command text, and the next exact-process guard was rejected by nested SSH quoting | 2 | Neither command launched the supervisor or touched the robot; verified no supervisor PID/status, then used a simple single-purpose `nohup` command after a separate read-only process check |
| The post-reboot formal startup passed the D455 streaming validator but `start_cuvslam_rviz_gui.sh` falsely reported no RealSense because `set -o pipefail` combined with `lsusb | grep -q` treated `lsusb` SIGPIPE 141 as failure | 1 | Capture the complete `lsusb` inventory before matching, require the command explicitly, and add a regression contract forbidding the unsafe pipeline; local focused `4/4` and full `295/295` pass |
| The first full local regression after the USB fix omitted the repository `src` directory from `PYTHONPATH`, causing 10 collection-time `ModuleNotFoundError: nodes` errors | 1 | No test body failed; reran with the repository's established `PYTHONPATH=<repo>/src` environment and all `295/295` tests passed |
| The first actual L6 motion attempt exhausted the single 120 s `pass_obstacle` phase budget while the third waypoint was active | 1 | Preserve the terminal `ABORT` and evidence without retry: `obstacle_cross_target` succeeded after about 85.5 s, `pos1_left_clear` succeeded after about 13.7 s, then `pos1_middle` was cancelled when the aggregate phase time reached `120.1 s` |

## Current Update - 2026-08-14 Phase 114 supervised Cone-to-grab-approach mission
Run the accepted cone and four-observation workflow once, continue to the calibrated `grab_area_approach` waypoint, then enter a terminal state without red-bar detection, arm motion, placeholder manipulation, or any placement goal. Preserve the existing Phase 113 nine-waypoint preset unchanged and require a fresh no-actuation acceptance gate before enabling the Lite3 command path.

### Phase 114: Full pre-grasp navigation acceptance
- **Status:** complete (cancelled before implementation after user clarified that the intended endpoint is the existing ninth waypoint / four-inspection Phase 113 boundary)
- [x] Remove the unneeded pre-grasp mode edits and preserve the validated `--cone-to-whz-l6` behavior unchanged.

### Phase 114 Resolution
- The phrase "抓取前的那个航点" referred to the existing inspection workflow boundary, not `grab_area_approach`. Continue Phase 113 with the calibrated 9-goal `inspection_interleaved` route and finish after four WHZ observations.

## Previous Update - 2026-08-14 Phase 112 staged exit from formal cone avoidance
Preserve the field-validated `725c122` formal Cone Avoidance behavior inside the obstacle zone, then add a stopped, acknowledged transition that disables the D455 depth stream, drains cone-specific processing, clears both cone-aware costmaps, bypasses the cone-health velocity gate while retaining the command watchdog, and continues Nav2 into the preloaded on-demand WHZ inspection workflow. Infra1, Infra2, IMU, cuVSLAM, and host odometry remain continuously required by localization; their post-transition verification must be configurable so it can be enabled during testing and disabled for timed competition runs.

### Phase 112: Formal cone-to-inspection resource transition
- **Status:** complete (implementation, L1 regression, and L4 no-actuation validation complete; full moving mission deferred to Phase 113)
- [x] Reuse the existing `AVOIDANCE -> DISABLED` mission milestone for formal `--cone-avoidance` without changing accepted cone parameters or in-zone behavior.
- [x] Run the Docker RealSense controller in verified `parameter` mode for integrated cone missions and confirm the live `enable_depth` value before acknowledging the transition.
- [x] Add configurable post-transition Infra1/Infra2/IMU/cuVSLAM-odometry and host `/odom` health verification.
- [x] Clear local/global cone costmaps and switch the final cone safety gate to watchdog-preserving bypass only after the `DISABLED` acknowledgement.
- [x] Preserve preloaded, request-scoped WHZ RTSP recognition/audio behavior and add focused L0/L1 regression coverage.

### Phase 112 Result
- Integrated cone missions require a continuous `1.0 s` stationary window after `obstacle_cross_target` before requesting `AVOIDANCE -> DISABLED`; stale odometry, motion above the settle thresholds, or an active navigation goal resets the window.
- Live L4 no-actuation validation confirmed false readback for `enable_depth`, `pointcloud.enable`, and `decimation_filter.enable`, both cone costmap layers disabled and read back, both costmaps cleared, scan-health bypass active, and the command watchdog retained.
- Infra1, Infra2, IMU, cuVSLAM odometry, and host `/odom` verification are enabled for testing and can be skipped for timed competition runs with `--skip-depth-disable-health-check`.
- The original pre-grab `MANIPULATION` milestone remains intact, so the depth pipeline is re-enabled before `grab_area_approach`; the resource shutdown is not permanent for the rest of the mission.
- Final local verification passed: focused tests `24/24`, full non-hardware regression `264/264`, Python compilation, Bash syntax, `package.xml` parsing, `git diff --check`, and the ROS 2 skill validator with zero issues. The validator skipped generic Nav2 YAML parsing because PyYAML is not installed; repository contract tests covering the changed YAML passed.

### Phase 112 Safety Gates
- Formal cone avoidance remains fail-closed and behaviorally unchanged until the robot has stopped after `obstacle_cross_target`.
- A missing/rejected RealSense parameter acknowledgement, failed costmap clear, invalid mode status, or stale command keeps `/cmd_vel` at zero.
- The final local handoff session performs no additional Jetson connection, ROS launch, navigation goal, actuator initialization, or robot command; the completed L4 evidence is the separately recorded no-actuation run.

## Current Update - 2026-08-14 Phase 113 supervised integrated Cone-to-WHZ mission
Validate the complete competition sequence under supervision: formal Cone Avoidance while moving, stopped resource transition after `obstacle_cross_target`, continued Nav2 with depth/cone processing off, and request-scoped WHZ recognition plus one-shot speech. The first authorized moving attempt aborted fail-closed before any navigation goal or nonzero command because the mission-start AVOIDANCE request was published before the cone-mode relay subscription became ready.

### Phase 113: Full moving mission acceptance
- **Status:** in_progress (the latest unchanged L6 run completed the first two goals, then the phase-wide 120-second `pass_obstacle` timeout canceled goal 3; no WHZ inspection ran and the one-run authorization is consumed)
- [x] Deploy the Phase 112 implementation plus startup-gate fixes to the authoritative Jetson checkout through the reviewed commit/sync path and verify GitHub/local/Jetson at `fdad03c`.
- [x] Run a no-actuation startup gate confirming installed-source provenance, lifecycle state, mode-controller readiness, WHZ preload, and sole `/cmd_vel` ownership.
- [x] Harden the Phase 113 route before motion: require completed field waypoint calibration, disable TaskManager goal/inspection retries, separate odometry readiness from SLAM tracking status, use phase-specific timeouts, stop after WHZ inspection, and reject placeholder manipulation unless explicitly enabled for bench debugging.
- [x] Formalize the Phase 71 field-run coordinates in `waypoints_real.yaml`, bind them to the phase-1 map hashes, validate the route locally, deploy the file, and repeat the no-actuation startup gate with the exact map ID.
- [x] Fix the mission-start depth request startup race with matching latched reliable QoS and idempotent 0.5 s republish; validate locally without actuation.
- [x] Deploy the startup-race fix to the clean formal Jetson checkout, rebuild the main package, and pass Jetson non-hardware regression without starting runtime or actuator paths.
- [x] Pass a formal no-actuation startup gate proving matching real-stack depth ACK, late-subscriber delivery, zero `/cmd_vel` subscribers, no actuator path, and complete teardown at `d29fdf3`.
- [x] With operator approval, run one bounded integrated route through the cone zone and confirm a continuous stationary window before depth shutdown.
- [ ] Confirm depth/pointcloud/cone scan stop, both cone layers are disabled and costmaps cleared, IR1/IR2/IMU/cuVSLAM and `/odom` remain healthy, then verify Nav2 continues toward inspection.
- [ ] At an inspection stop, request one WHZ recognition and verify the built-in camera is opened on demand, the result is correct, and speech plays once.
- [ ] Decide the competition setting for `--skip-depth-disable-health-check` from measured transition latency and localization behavior; then perform exact teardown and archive evidence.

### Phase 113 First Moving Attempt Result
- Operator-confirmed route clearance, immediate emergency stop, and on-site supervision were recorded before startup.
- Formal route/map/provenance gates passed at exact deploy `7703e20`; D455/cuveSLAM, depth control, Host odometry, Nav2, and the Lite3 bridge initialized.
- TaskManager published the mission-start `AVOIDANCE` request at `05:15:57.938`; `cone_mode_relay` did not report ready until `05:15:59.855`, so the one-shot volatile request was lost before its subscriber existed.
- The depth controller remained `BOOTING` with `message=waiting for mission depth request`; TaskManager timed out after 8 seconds and entered `ABORT` before sending any NavigateToPose goal.
- Bridge diagnostics remained `motion=0`, last received/sent commands were all zero, and `udp_errors=0`. Exact cleanup left no relevant process, Docker container, control UDP endpoint, or Git change.
- Evidence: `/home/superwfx666/competition_logs/cone_to_whz_l6/20260814_051326_phase113_integrated_7703e20`.

### Phase 113 Second Moving Attempt Result
- Fresh operator authorization and all preflight gates passed at clean deploy `d29fdf3`, including the calibrated 9-goal route, pinned phase-1 map, D455/audio devices, Lite3 reachability, and empty pre-existing runtime/control ports.
- The robot moved only on the first goal `obstacle_cross_target=(1.05,0.75,pi)`. DWB commanded up to `0.24 m/s` with steering, then reported `No valid trajectories out of 351` after the robot entered the gap between two cones.
- Recovery cleared costmaps, rejected spin because of an imminent collision, waited, then briefly resumed. Global planning repeatedly failed to generate a path to `(1.05,0.75)` and Nav2 aborted the action; TaskManager entered terminal `ABORT` under the zero-retry contract.
- The command bridge's motion count stopped at `284`; from the Nav2 abort onward it continuously submitted `(0,0,0)` with `udp_errors=0`. Final retained odometry was approximately `(1.744,0.482,-19.4 deg)`.
- The operator reported the physical cone trap and was instructed to use the e-stop. Emergency cleanup then left zero running containers, relevant processes, and control UDP endpoints; deploy Git status remained clean.
- Evidence: `/home/superwfx666/competition_logs/cone_to_whz_l6/20260814_065621_phase113_integrated_d29fdf3`.

### Phase 113 Third Moving Attempt Result
- A pre-motion wrapper invocation failed closed before cleanup, Docker, ROS, Lite3 initialization, or motion because it omitted `TASK_EXPECTED_MAP_ID`; after confirming zero runtime residue, the wrapper was corrected to pass the same `competition_field_phase1` identity used by the accepted formal runs.
- The sole actual motion startup used unchanged deploy/configuration `d29fdf3`. Goals 1 `obstacle_cross_target` and 2 `pos1_left_clear` both succeeded; the acknowledged `AVOIDANCE -> DISABLED` transition occurred after goal 1, and Nav2 continued to goal 3 `pos1_middle`.
- The `pass_obstacle` timer is phase-wide, not per-goal. It reached `120.1 s` about 18 seconds after goal 3 was sent, so TaskManager canceled the active action and entered terminal `ABORT` despite completing two goals.
- No WHZ inspection or speech ran. Final bridge diagnostics were `(0,0,0)` with `udp_errors=0`; teardown left zero containers, relevant processes, control UDP endpoints, and deploy Git changes.
- Evidence: `/home/superwfx666/competition_logs/cone_to_whz_l6/20260814_073201_phase113_third_supervised_d29fdf3`.

### Phase 113 Safety Gates
- One supervised integrated run only; no retry or second route without a fresh review of the first result.
- Any failure of stop confirmation, parameter readback, costmap cleanup, localization continuity, command ownership, or watchdog freshness aborts before continued motion.
- L4 evidence from Phase 112 must not be treated as L6 proof of the moving competition workflow.

### Phase 113 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| The first run-once wrapper omitted the required `TASK_EXPECTED_MAP_ID` environment value | 1 | Formal launcher rejected before cleanup/Docker/ROS/Lite3/motion; confirmed zero residue, then passed exact `competition_field_phase1` for the authorized motion startup |
| Windows PowerShell could not resolve the bare `bash` command during the first parallel validation wrapper | 1 | No repository command depended on the missing shell result; rerun Bash syntax with the Git for Windows executable resolved by absolute path and recollect all other results separately |
| Focused unittest module imports could not resolve the repository `nodes` package | 1 | The tests did not reach implementation code; rerun with the repository's expected `PYTHONPATH=src` environment |
| The first PWF append patch anchored `progress.md` to a line that existed in `findings.md`, so `apply_patch` rejected the complete edit | 1 | No file changed; read the exact file tails and re-applied the append using end-of-file context |
| The first Jetson fast-forward command had mismatched nested SSH quoting | 1 | The remote script did not execute; switched to standard-input script transport and then verified the exact new HEAD and clean worktree |
| Two build attempts received a trailing CR in `console_cohesion+` through the PowerShell here-string pipeline | 2 | Colcon rejected its arguments before building; switched to a direct one-line SSH command and the package build passed |
| Combined Jetson provenance commands were parsed locally because of nested PowerShell/SSH/Python quoting | 2 | No target checks ran in those failed invocations; split the checks and then used Base64 script transport for deterministic read-only verification |
| Installed `start_competition.sh` hash lookup failed because setup.py intentionally installs launch/config assets but not operator shell scripts | 1 | Verified the packaging manifest and checked the source-controlled deploy script directly; the installed launch hash still matched source exactly |
| The first route-formalization patch used an imprecise README anchor | 1 | `apply_patch` rejected the complete patch without changing files; split the edit into exact per-file patches |
| Windows route description could not import `rclpy` | 1 | Used the same pure route parser locally, then ran the actual CLI successfully in the Jetson Foxy environment for both the 9-goal inspection and 14-goal full routes |
| The first post-build install hash command received a trailing CR in its final path | 1 | Build, tests, route descriptions, HEAD, and clean status had already passed; reran provenance checks through deterministic remote scripts |
| System SSH became intermittent over the Tailscale path | 2 | No remote command ran during the failed handshakes; switched to the working native `tailscale ssh` transport and rechecked empty runtime state before mutation |
| The first no-actuation wrapper timed out at 360 s before the launcher completed its own acceptance checks | 1 | Automatic cleanup left zero process/container/UDP residue; reran the launcher without the premature outer timeout and obtained GO |
| A previous-boot depth control request caused a transient invalid monotonic timestamp fault | 1 | Added startup reset of only `depth_control_request.json` and `depth_controller_status.json` after old-process cleanup, preserving runtime fail-closed timestamp validation |
| The first authorized moving attempt lost the one-shot mission-start AVOIDANCE request because TaskManager published about 1.92 s before `cone_mode_relay` subscribed | 1 | Fail-closed ABORT occurred before any navigation goal or nonzero command; completed exact teardown and stopped under the one-run rule. Add a tested startup-ready/republish contract before requesting fresh field authorization |
| The second authorized attempt entered the two-cone gap, then DWB found no valid trajectory and global planning could no longer produce a path to `obstacle_cross_target` | 1 | Nav2/TaskManager aborted without retry and continuously commanded zero; operator e-stop was requested and exact emergency cleanup passed. Do not rerun until the cone geometry/costmap interaction is reproduced and corrected offline or in a bounded stationary test |

## Current Update - 2026-08-13 Phase 111 repeat one-shot obstacle-cross run
Repeat Phase 110 exactly once after the robot was returned to the same start: formal `725c122` cone stack, one NavigateToPose goal to `(1.05,0.75,pi)`, no auxiliary tests, no retry, then full teardown.

### Phase 111: Repeat single goal
- **Status:** complete (exactly one repeated goal sent; SUCCEEDED; full teardown complete)
- [x] Confirm clean deploy `725c122`, no runtime/container/actuator-port residue, and robot returned to the original start.
- [x] Start the same formal cone stack and wait only for its built-in GO/NO-GO result.
- [x] Send exactly one goal `(1.05,0.75,pi)`, record terminal status, and tear down all run-owned processes/container.

### Phase 111 Result
- Formal `725c122` cone startup reached GO with the bridge holding continuous zero and `udp_errors=0` before the goal.
- Exactly one repeated NavigateToPose goal `(1.05,0.75,pi)` was sent under a new one-shot lock. It returned `SUCCEEDED` after about 24.7 s with five recoveries; final feedback was approximately `(1.244,0.876)` with `0.231 m` remaining.
- Bridge motion count reached 732, then remained at continuous `(0,0,0)` with `udp_errors=0`. Planner logged two aborted compute-path attempts during recovery; BT Navigator ultimately logged `Navigation succeeded`.
- Full teardown passed: no relevant process, container, or UDP `43893/19012/19001` endpoint remained. Deploy stayed clean at `725c122`.
- Evidence: `/home/superwfx666/competition_logs/cone_l4/20260813_phase111_repeat_725c122` and `/home/superwfx666/Desktop/logs/competition_20260813_215643.log`.

### Phase 111 Safety Gates
- Reuse the immediately preceding confirmed on-site supervisor, emergency-stop, cone placement, and personnel-clear conditions.
- One action goal only; no TaskManager, route runner, regression, retry, or second goal.

## Current Update - 2026-08-13 Phase 110 single-goal obstacle-cross field run
Run the shortest supervised real-robot cone-avoidance test using the already deployed Phase 106 profile. Cold-start only the required formal stack and actuator bridge, then send exactly one NavigateToPose goal to `obstacle_cross_target=(1.05,0.75,pi)`; do not run regression suites, stationary acceptance cycles, TaskManager, route execution, or any second goal.

### Phase 110: One-shot obstacle-cross navigation
- **Status:** complete (exactly one goal sent; NavigateToPose SUCCEEDED; full teardown complete)
- [x] Minimal preflight: exact clean deploy `725c122`, no conflicting control owner/actuator endpoint, D455 and Lite3 reachable.
- [x] Start formal cone avoidance with dog motion preparation and `cmd_vel_bridge`; require launcher GO and sole safety-gate `/cmd_vel` publisher before the bridge subscribes.
- [x] Send exactly one goal `(1.05,0.75,pi)`, monitor its terminal status, then stop the stack and verify no actuator process remains.

### Phase 110 Result
- Operator confirmed on-site supervision, immediate emergency stop, and no people/temporary obstacles; the cone was intentionally placed on the target path as the test obstacle.
- Formal `725c122` startup reached GO with `cone_scan_safety_gate` as the sole `/cmd_vel` publisher and `cmd_vel_bridge` as the sole subscriber. Before the goal, bridge diagnostics remained zero with `udp_errors=0`.
- Exactly one `NavigateToPose` goal was submitted to `map: (1.05,0.75,pi)`, protected by a one-shot lock. It returned `SUCCEEDED` after about 20.7 s with one recovery; final feedback was approximately `(1.186,0.958)` and `0.249 m` remaining.
- The bridge recorded 748 nonzero motion samples and returned to continuous `(0,0,0)` with `udp_errors=0`. Nav2 logged one transient `No valid trajectories out of 351`, recovered, and then logged `Navigation succeeded`.
- Teardown removed all Nav2, bridge, cone host, odometry bridge, Lite3, and startup processes; `/cmd_vel` became unknown, relevant UDP ports were empty, and the exact cuVSLAM container was stopped. Deploy remained clean at `725c122`.
- Evidence: `/home/superwfx666/competition_logs/cone_l4/20260813_phase110_single_725c122` plus `/home/superwfx666/Desktop/logs/competition_20260813_212850.log`.

### Phase 110 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| `start_competition.sh --help` is not a supported help mode and began a no-actuator startup | 1 | No goal or actuator path existed; precisely removed that invocation/container and then used the formal command once |
| First cuVSLAM teardown used a case-mismatched container name | 1 | Stopped the already identified exact container ID `20dcfde6ab6e` and verified no container/process/port remained |

### Phase 110 Safety Gates
- Human supervisor beside the dog with immediate emergency-stop authority; route to `(1.05,0.75)` clear of people and unexpected obstacles.
- Exactly one NavigateToPose goal; no retry, TaskManager, multi-waypoint runner, auto-advance, or secondary goal.
- Any duplicate command owner, wrong deploy SHA, startup NO-GO, nonzero command before the goal, UDP error, or operator stop aborts before/through motion.

## Current Update - 2026-08-13 Phase 109 Jetson deploy sync with external processes preserved
Synchronize the clean local Phase 106 commit `725c122` to the authoritative Jetson deploy checkout only after read-only preflight. The separate `quadruped-vision-yolo-refactor` worktree and its active `competition_manager`, `apriltag_udp_bridge`, and `arm_motion.launch.py` processes must remain untouched; do not launch testing or connect the actuator path.

### Phase 109: Read-only Jetson audit and code sync
- **Status:** complete (deploy was already synchronized to `725c122`; no code update or test launch was needed)
- [x] Inspect Jetson host, worktrees, deploy HEAD/status, active processes, ROS_DOMAIN_ID, `/cmd_vel` graph, and Lite3 UDP endpoints without mutation.
- [x] Verify the clean formal deploy checkout already equals local `725c122`; preserve the dirty vision worktree and perform no redundant Git mutation.
- [x] Recheck remote commit/worktree/process/ROS ownership state read-only; do not start or stop any test process.

### Phase 109 Result
- Jetson rebooted at `2026-08-13 20:59:31 +08:00`. The previously observed `competition_manager`, `apriltag_udp_bridge`, and `arm_motion.launch.py` processes are no longer running; they were not terminated by this session.
- The vision worktree remains at `/home/superwfx666/worktrees/quadruped-vision-yolo-refactor`, branch `feature/vision-change-jetson-test`, HEAD `608d93e`, with its existing modified and untracked files preserved untouched.
- The authoritative deploy is clean on branch `codex/formal-cone-941bed6` at exact HEAD `725c122`. Reflog proves the fast-forward from `34e6e65` occurred at `20:01:23 +08:00`, before this audit and before the reboot.
- No `/cmd_vel` topic, relevant ROS node/process, Docker container, or Lite3 UDP `43893/19012` endpoint remains. No build, launch, goal, velocity, hardware initialization, or field test was run.
- A ROS 2 CLI read-only query auto-started `_ros2_daemon`; this session stopped only that newly created daemon and verified it was gone.

### Phase 109 Safety Gates
- No process termination, ROS launch, navigation goal, Twist publication, actuator initialization, posture/mode change, or test execution.
- Abort synchronization if formal deploy is dirty, not fast-forwardable, or the target commit cannot be verified.

## Current Update - 2026-08-13 Phase 108 Phase 99 cone costmap visualization
Produce a truthful visual check of the real cone placement using the complete Phase 99 stationary rosbag. Correct the clear/cone capture anchors, replay only in an isolated localhost ROS domain with no actuator or navigation nodes, and show local costmap cells together with the base_link cone scan. This does not claim to be a live Phase 105/current-global snapshot because the D455 is not currently enumerated.

### Phase 108: Visualize real-cone placement in local costmap
- **Status:** complete
- [x] Confirm the complete Phase 99 bag and current no-control-process/no-container state on Jetson.
- [x] Correct the extractor to sample stable frames 6 seconds after `CLEAR_BEFORE` and `CONE_IN_R1` independently.
- [x] Replay the bag in isolated `ROS_DOMAIN_ID=77`/localhost-only mode and extract corrected local/global/scan snapshots.
- [x] Generate and verify the interactive costmap placement visual at desktop and mobile widths.

### Phase 108 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Remote replay wrapper sourced Foxy under `set -u`, and `setup.bash` referenced unset `AMENT_TRACE_SETUP_FILES` | 1 | No replay or ROS node started; source ROS environments before enabling strict undefined-variable checking |

## Current Update - 2026-08-13 Phase 107 supervised on-robot retest of early avoidance
Single supervised cone-bypass retest on the dog with the Phase 106 formal overlay. Same protocol as Phase 105: one goal (`pos1_left_clear`), preview before send, send exactly once, stop on any gate failure/abort/anomaly. New acceptance focus: the global path must bend away from the cone at preview time (before motion), and the robot must not stomp in place near the cone.

### Phase 107: On-robot validation of Phase 106 tuning
- **Status:** pending (awaiting field session)
- [ ] Cold start `bash scripts/start_competition.sh --dog --cmd-vel-bridge --prepare-lite3-motion --cone-avoidance`; require GO banner (runtime gates now enforce 0.60/2.0, PathAlign/PathDist 16, sim_time 2.5).
- [ ] Static check: with the robot ~4.6 m from the cone, confirm the cone appears in both costmaps by ~3.0 m and the previewed global path visibly bends around it before any goal is sent.
- [ ] Send `pos1_left_clear` once; observe early arc (no in-place stomping within ~1 m of the cone), record /cmd_vel, controller log, costmaps.
- [ ] Regression leg: run the inspection route preview (`--describe-route`) and watch narrow corridors / near-wall waypoints for detours or approach failures caused by 0.60 inflation.
- [ ] Debrief: log outcomes in progress.md + findings.md; if narrow-corridor side effects appear, plan split local/global inflation (global 0.60 / local 0.40) as Phase 108 candidate.

### Phase 107 Safety Gates
- Human supervisor with remote-stop authority next to the robot for the whole run; abort on any abnormal gait, oscillation, or proximity breach.
- One goal only; never re-send after abort. Any NO-GO from the startup chain ends the session before motion.
- Velocity envelope unchanged (max_vel_x=0.24, max_vel_theta=0.30, min_vel_x=0, max_vel_y=0); no experimental overlay unless the formal profile fails and L4 gates are explicitly satisfied.

## Current Update - 2026-08-13 Phase 106 early cone-avoidance tuning
Fix the "stomp in place in front of the cone" behavior from Phase 105 by making avoidance start early: larger inflation so NavFn bends the global path away from the cone well before contact, longer DWB lookahead, weaker path attraction, and cone marking out to the scan-chain 3.0 m limit. Only the cone overlays, launcher expectations, and pinned contract tests change; base `nav2_params.yaml` stays untouched.

### Phase 106: Tune formal cone overlay for early avoidance
- **Status:** complete (L1); on-robot validation pending as Phase 107
- [x] Formal overlay: inflation_radius 0.30->0.60, cost_scaling_factor 3.0->2.0, obstacle_range 2.50->3.00 (both costmaps); FollowPath adds sim_time 2.5, PathAlign.scale 16.0, PathDist.scale 16.0.
- [x] Experimental overlay stays a strictly-more-aggressive distinct profile: 0.75/1.5, PathAlign/PathDist 12.0, sim_time 3.0, obstacle_range 3.00.
- [x] start_competition.sh: update formal/experimental CONE_EXPECTED_* values and add a FollowPath.sim_time runtime gate.
- [x] Update pinned tokens in test_cone_avoidance_contract.py and test_formal_startup_chain.py; run both focused test files (20/20 OK). configs/navigation/README.md refreshed to match.

### Phase 106 Safety Gates
- No Jetson access, launch, goal, or motion in this phase; L0/L1 only.
- min_vel_x=0, max_vel_y=0, max_vel_x=0.24, max_vel_theta=0.30 velocity envelope is unchanged.

## Current Update - 2026-08-13 Phase 105 single supervised cone-bypass retest
Reuse the live Phase 104 formal cone/Nav2 stack and hot-add only the proven Lite3 motion preparation plus `cmd_vel_bridge`. After one minimal zero-command/runtime gate, preview the existing `pos1_left_clear` goal with the live planner and send it exactly once. Stop on any gate failure, abort, safety anomaly, or completion; never retry or send a second goal.

### Phase 105: Run one bounded low-speed goal
- **Status:** complete (one goal sent; robot traversed 4.605 m straight-line displacement and reached 0.374 m from the goal, but NavigateToPose ABORTED after repeated DWB `No valid trajectories out of 351`; no retry; actuator chain removed)
- [x] Hot-add `cmd_vel_bridge` with `init_dog=false` and run the no-toggle Lite3 motion-mode preparation.
- [x] Require one `/cmd_vel` actuator subscriber, five active lifecycle nodes, live TF, continuous bridge zero command, and `udp_errors=0`.
- [x] Capture current pose and local/global costmap evidence, then require a valid live `ComputePathToPose` result to `pos1_left_clear=(0.600,2.900)`.
- [x] Send exactly one NavigateToPose goal, monitor it to abort, and perform identity-scoped teardown with final zero-command/no-actuator evidence.

### Phase 105 Safety Gates
- Do not restart the live D455/Nav2 stack, run TaskManager/auto-advance, enable reverse/lateral motion, or repeat prior regression/stationary tests.
- Any duplicate command owner, nonzero idle command, UDP error, stale cone health/scan, lifecycle/TF failure, invalid path, unexpected process, abort, or operator stop is immediate stop with no goal retry.
- `/cmd_vel` alone is not a complete stop claim; require bridge zero-send diagnostics and observed physical stop before actuator teardown.

### Phase 105 Result
- Lite3 preparation completed with `simple=50 complex=48 errors=0`; the formal installed bridge ran with `init_dog=false`, one expected `/cmd_vel` subscription, continuous idle `last_recv/last_send=(0,0,0)`, and `udp_errors=0`.
- The Foxy `ComputePathToPose` action returned a nonempty successful path from approximately `(5.25,1.15)` to `(0.60,2.90)`. Exactly one NavigateToPose goal was then sent, with terminal handover disabled so the probe could not emit a second action goal.
- The goal started at `(5.253,1.145,-2.530)` and ended at `(0.967,2.830,2.910)`: straight-line displacement `4.605 m`, remaining XY error `0.374 m`. The probe captured 3839 velocity samples, 2295 nonzero, with maxima `0.24 m/s`, `0.30 rad/s`, and zero lateral velocity.
- NavigateToPose ended `ABORTED` (`action_status=6`). The formal log contains repeated `No valid trajectories out of 351`, followed by `Navigation failed`; this is substantial progress beyond Phase 102 but not a successful bypass acceptance. Without the operator's physical observation, the software trace alone does not prove how the body cleared the cone.
- Synchronized evidence contains 23 local and 24 global costmap snapshots. Global costmap changed during the run (2 unique hashes), proving the new cone-aware global layer was live; the remaining terminal DWB infeasibility is preserved for geometry analysis.
- After abort, bridge motion count stayed fixed at 2295 while it continuously sent three-axis zero with zero UDP errors for about one minute. The bridge was then identity-scoped away. Final `/cmd_vel` state is one safety-gate publisher and zero subscribers; no bridge, motion sender, TaskManager, goal probe, costmap watcher, UDP 43893, or UDP 19012 endpoint remains. The five Nav2 lifecycle nodes and the existing cuVSLAM container remain active.
- Evidence: `/home/superwfx666/competition_logs/cone_l4/20260813_phase105_single_34e6e65`.

### Phase 105 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Two read-only remote batches had local PowerShell/Bash quoting errors | 1 each | No remote mutation or goal occurred; switched to the established UTF-8 Base64 remote-script transport |
| The actuator-enable SSH wrapper hit the local 35 s ceiling after completing remotely | 1 | Did not repeat the Lite3 preparation; recovered its `50/48/0` evidence and the live bridge state from the remote directory |
| The first two planner CLI payloads used newer `ComputePathToPose` fields absent from Foxy (`goal`, then `use_start`) | 1 each | No action reached the server; inspected the installed Foxy interface and used its actual `pose + planner_id` schema |
| The successful Foxy planner result used `Goal finished with status: SUCCEEDED`, which did not match the newer status-text assertion | 1 | Reused the already successful nonempty path result instead of replanning, then sent the sole NavigateToPose goal |
| SIGINT to the `ros2 run` wrapper did not propagate to the bridge child; later identity-scoped SIGTERM removed both without the expected logged shutdown burst | 1 | Do not claim a graceful shutdown burst. Retain the stronger pre-teardown evidence: about one minute of continuous zero sends, fixed motion count, `udp_errors=0`, plus final zero subscribers/no actuator process |

## Current Update - 2026-08-13 Phase 104 fast Jetson readiness for supervised bypass retest
Move the completed Phase 103 cone-bypass fix to the authoritative Jetson checkout with the minimum discriminating validation. Reuse the already-passed 45 focused tests, skip unrelated regression and repeated stationary cycles, prove the actual planner/controller load the dual-costmap overlay and pinned plugin with the actuator path absent, then stop at the physical safety confirmation boundary before any motion.

### Phase 104: Deploy and reach no-actuator runtime readiness
- **Status:** complete (formal no-actuator runtime GO at `34e6e65`; live stack intentionally retained while awaiting fresh on-site motion confirmation)
- [x] Commit and push the already-reviewed Phase 103 files without rerunning local tests.
- [x] Read-only preflight the authoritative Jetson deploy, camera owner, ROS/UDP residue, and Lite3/actuator isolation; accept only a clean fast-forwardable checkout.
- [x] Fast-forward the formal checkout and run only the package-limited build/install refresh needed for the changed launch/config/runtime contract.
- [x] Cold-start formal cone mode without `--dog`, bridge, TaskManager, auto-advance, or any navigation goal; require launcher GO plus live `1.0/21/0/0`, dual cone layers, and pinned plugin mappings in controller/planner.
- [x] Capture one current read-only local/global costmap snapshot, preserve the GO snapshot/log, and stop at the physical confirmation boundary before enabling the actuator path.

### Phase 104 Result
- Phase 103 was committed and pushed as `34e6e65ccc856942cfb826e4f216c0a5740c8902`; the clean formal Jetson checkout fast-forwarded from `025b320` to that exact SHA and a package-only symlink build completed without tests.
- Three confirmed Phase 102 no-actuator orphan processes were precisely removed before startup. The final pre-start ROS graph, relevant processes, and actuator UDP ports were empty.
- Formal `bash scripts/start_competition.sh --cone-avoidance` produced GO. All five lifecycle nodes are active; live formal values are `ObstacleFootprint=1.0`, `vtheta_samples=21`, `min_vel_x=0`, `max_vel_y=0`, and both local/global persistence values are `1.5`.
- controller_server and planner_server both map the exact canonical pinned plugin library. The 10 s health gate passed with 99 scans at `9.803 Hz`, 97 continuously healthy samples, no errors/unhealthy samples, and maximum source age `46.385 ms`.
- `/cmd_vel` has one publisher (`cone_scan_safety_gate`) and zero subscribers. No `cmd_vel_bridge`, transfer/motion sender, TaskManager, UDP 43893, or UDP 19012 endpoint is running. Lite3 is physically connected/reachable, but its actuator path remains disabled.
- Current read-only snapshots were saved under `/home/superwfx666/competition_logs/cone_l4/20260813_phase104_ready_34e6e65`; local/global costmaps are both publishing. No marker, Twist, navigation goal, posture/mode change, or physical motion was issued.
- The live no-actuator stack is intentionally retained to minimize time to the supervised test. The next action requires fresh operator confirmation of robot/route/cone placement, supervision, controller neutral, and working emergency stop.

### Phase 104 Safety Gates
- Before fresh operator confirmation, do not connect or initialize the Lite3 actuator path, publish Twist, send a navigation goal, or change robot posture/mode.
- Skip repeated local tests, full repository tests, old three-cycle persistence regression, resource A/B, and unrelated camera diagnostics. Reuse Phase 103 L0/L1 and prior D455/scan acceptance unless the current runtime gate contradicts them.
- Any dirty formal checkout, non-fast-forward deploy, duplicate D455 owner, unexpected `/cmd_vel` actuator subscriber, wrong plugin mapping, stale scan/health, lifecycle failure, or global costmap lacking the cone layer is immediate NO-GO.
- Runtime readiness is L2/L3/L4-no-actuation evidence only; it does not authorize or imply physical bypass success.

### Phase 104 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| The single no-actuator formal cold-start SSH wrapper did not return within its 240 s outer timeout and no remote stdout was delivered | 1 | Do not restart. Preserve the potentially live stack and inspect the latest launcher log/snapshot, exact processes, containers, lifecycle, params, plugin mappings, and command ownership read-only before deciding whether cleanup is needed |
| The first post-GO costmap snapshot command did not `cd` to the formal repository, so both relative script paths failed; no ROS or hardware state changed | 1 | Keep the accepted live stack, rerun only the two read-only snapshot commands from the explicit formal repository directory, and do not repeat startup |

## Current Update - 2026-08-13 Phase 103 cone bypass configuration fix
Fix the Phase 102 structural local minimum without broadening hardware authority. Make the formal cone overlay visible to both local and global costmaps, give DWB a meaningful pre-collision obstacle gradient, and include a true zero-yaw sample. Preserve the validated forward-only/non-holonomic motion envelope until reverse or lateral Lite3 gait safety is separately proven.

### Phase 103: Make cone-aware paths locally feasible
- **Status:** complete (local L0/L1 implementation and contracts passed; Jetson L2/L3 and supervised bypass retest remain separate future phases)
- [x] Add the buffered cone obstacle layer to the formal global costmap so NavFn replans around observed cones instead of repeatedly producing a path through them.
- [x] In cone mode only, set `FollowPath.ObstacleFootprint.scale` to a conservative value within the proposed `0.5-2.0` range and make `vtheta_samples` odd; keep `min_vel_x: 0.0` and `max_vel_y: 0.0` unchanged.
- [x] Keep the opt-in experimental overlay structurally compatible with the same global cone ownership, update documentation, and harden formal startup/runtime contracts around the new live parameters and plugin provenance.
- [x] Run focused contracts, real YAML parsing, shell/Python static checks, ROS 2 skill validation, and diff hygiene. This phase is local L0/L1 only; do not connect to Jetson or command hardware.

### Phase 103 Result
- Formal cone mode now loads the same buffered `NonPersistentVoxelLayer` into local and global costmaps. `navigation.launch.py` has mutually exclusive static/depth/cone planner branches, so planner_server actually receives the cone overlay.
- Cone-mode DWB overrides are `ObstacleFootprint.scale=1.0` and `vtheta_samples=21`; base/static values remain unchanged, and reverse/lateral motion remains disabled.
- Formal startup requires live dual-costmap parameters and canonical pinned plugin mappings in both controller_server and planner_server. The explicit experimental profile remains selectable with its own strict expected values.
- Focused verification passed 45/45 tests plus Bash syntax, Python compilation, real YAML parsing, ROS 2 validators, and diff hygiene. Full discovery passed 241 tests; three unrelated WHZ image suites could not import because the project `.venv` lacks `numpy`.
- Verification level is L0/L1 only. No ROS graph, Jetson runtime, D455, Lite3, navigation goal, or physical bypass was exercised; L2/L3 and a supervised one-attempt L4 retest are not implied by completion of this phase.

### Phase 103 Safety Gates
- No SSH to Jetson, D455 ownership change, ROS/Nav2 launch, Lite3 connection, velocity publication, navigation goal, or physical motion in this phase.
- Do not enable reverse or lateral motion. `min_vel_x` remains zero and `max_vel_y` remains zero until a separately supervised gait-safety test authorizes either degree of freedom.
- Treat static/unit success as L0/L1 evidence only. A later cold-start L2/L3 check must prove both costmaps load the pinned plugin, and any bypass claim requires a fresh one-attempt supervised field run.

### Phase 103 Decisions
- Use `ObstacleFootprint.scale: 1.0` for the formal cone overlay: it is the midpoint of the proposed `0.5-2.0` starting range and remains isolated from non-cone navigation.
- Use `vtheta_samples: 21` in cone mode so the symmetric angular grid includes exactly zero; this removes the observed `+/-0.015789 rad/s` sampling artifact but is not treated as the root bypass fix.
- Keep inflation at the already stationary-validated `0.30 / 3.0`; global cone visibility is the root correction, while wider inflation is not assumed to create feasible trajectories.

### Phase 103 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Two combined read-only orchestration batches returned exit 1 when an `rg` command had no matches, suppressing sibling output | 1-2 | No files changed; split mandatory reads from optional searches and normalize expected `rg` no-match status instead of repeating the combined pattern |
| The first validation batch used `.venv` with `pytest`, but that environment does not install pytest, so the batch stopped before sibling results were reported | 1 | The focused tests are standard-library `unittest` suites; rerun them with `python -m unittest` and keep the remaining checks independent of pytest |
| Focused `unittest` run passed 44/45 but one runbook contract still expected the obsolete phrase `首次 local 标记` | 1 | Updated the contract to the new `首次 local/global 标记` wording and expanded the runbook's configure-only gate to cover planner/global costmap |
| YAML validation used the project `.venv`, which does not include the repository's available `invoke.vendor.yaml` parser | 1 | Keep `.venv` for unittest/compile checks, but use the system Python environment already known to provide `invoke.vendor.yaml` for real YAML parsing |
| Full `unittest discover` ran 244 tests but three unrelated WHZ image suites could not import because `.venv` lacks `numpy` | 1 | Record the environment gap without installing or changing unrelated dependencies; 241 tests passed and all 45 focused Nav2/cone/startup contracts passed |

## Current Update - 2026-08-13 Phase 102 minimal supervised hardware motion acceptance
Proceed from the completed Phase 100/101 formal-startup GO to one bounded on-robot cone-avoidance motion check. Reuse the proven formal deployment and existing motion chain, skip repeated stationary cone cycles and unrelated regression suites, issue at most one low-speed goal with a planned route of approximately 4-5 m after fresh on-site safety confirmation, and never auto-retry motion after a failed gate or goal.

### Phase 102: Run one bounded low-speed cone motion check
- **Status:** complete (single 4.980 m planned goal physically attempted once; safe obstacle stop observed but bypass failed after 0.843 m with DWB `No valid trajectories out of 335`; no retry; exact teardown complete)
- [x] Recover the already validated Lite3 motion/bridge/goal procedure and choose one obstacle-relevant goal whose accepted global plan is approximately 4-5 m, with conservative limits.
- [x] Pass a fresh read-only Jetson gate for formal HEAD/worktree, single D455 owner/reboot state, empty ROS/UDP command chain, and current Lite3 connectivity state.
- [x] Obtain fresh operator confirmation for robot placement, route clearance, controller neutral, on-site supervision, and working emergency stop before enabling any actuator path.
- [x] Cold-start only the required formal cone/Nav2/Lite3 chain; before the goal require startup GO, five active lifecycle nodes, healthy scan/cone stream, fresh TF/odom, one expected `/cmd_vel` actuator subscriber, and an idle zero-command state.
- [x] Send one approximately 4-5 m low-speed goal, monitor command/scan/health/local costmap/tracking and physical response, stop immediately on the first abort, then precisely teardown and archive evidence. No second goal was sent.

### Phase 102 Result
- Formal startup passed its fail-closed GO at `025b320`; TaskManager and auto-advance were disabled. The bridge had one expected subscriber, completed Lite3 motion preparation with zero errors, and remained at zero command before the goal.
- The read-only global planner returned a 384-pose, `4.980432 m` path from live start `(4.725, 0.750)` to the single destination `(0.600, 2.900)`.
- The accepted goal moved the robot `0.843132 m` from `(4.7169, 0.7402)` to `(3.8839, 0.8703)` and rotated about `-0.8024 rad`; commanded maxima were `0.24 m/s` and `0.30 rad/s`.
- Operator observed the robot approach the cone without collision, then step in place at close range until Nav2 aborted. The controller independently logged `No valid trajectories out of 335`, followed by `ABORTED`; the remote operator did not cancel the goal first.
- Cone runtime health passed throughout: 1188 scans at `9.8936 Hz`, 1187 health samples, no unhealthy samples/errors, and maximum source age `169.746 ms`. This localizes the failure to feasible local trajectory generation rather than scan/health transport.
- Result is `NO_GO_NAV2_NO_VALID_TRAJECTORIES`: physical collision prevention was demonstrated, but cone bypass was not. No second goal or automatic retry occurred.
- Evidence: `/home/superwfx666/competition_logs/cone_l4/20260813_043340_phase102_single_4_5m`.
- Final state: no running container, ROS/Nav2/bridge/cone process, or UDP 43893/19001/19002/19012 listener. The historical D455 container remains stopped exactly as left by the user's Jetson reboot (`exit 137`, OOM=false); Lite3 remains connected and reachable but no command process is running.

### Phase 102 Safety Gates
- No actuator connection, Lite3 mode change, velocity, or navigation goal before fresh on-site confirmation. A text request to proceed does not substitute for confirming the current physical scene.
- Keep the route bounded to approximately 4-5 m and speed-limited; require the entire corridor to be visible/clear, an operator at the robot with a tested immediate stop path, and the controller centered.
- Any cone-health, scan, TF, odom, controller, tracking, duplicate-process, or command-ownership anomaly is NO-GO. Stop and inspect; never auto-retry motion.
- Preserve the historical D455 owner and formal deploy provenance. Teardown only identity-checked Phase 102 processes/containers and restore the prior camera state.

### Phase 102 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| The first combined read-only preflight embedded Bash `$(...)`/`||` inside a PowerShell double-quoted SSH command, so PowerShell rejected it locally before SSH | 1 | No Jetson command was sent; use the established UTF-8 Base64 remote-script transport and do not repeat the quoting pattern |
| The first final preflight timed out because Jetson SSH/Tailscale was temporarily unavailable after Lite3 reconnection | 1 | No remote command was delivered; waited for the user to restore SSH, then reran the gate successfully without repeating any hardware test |
| The first post-reboot preflight expected the historical D455 container to be running, but it had exited 137 during the user's Jetson reboot | 1 | Verified OOM=false, matching reboot timing, D455 USB presence, no camera owner, and no runtime residue; accepted direct formal camera takeover instead of restarting the historical container first |
| A read-only ROS gate sourced Foxy under `set -u`, which failed on unset `AMENT_TRACE_SETUP_FILES` | 1 | No ROS query or goal was issued; removed nounset for ROS environment sourcing and continued with bounded read-only queries |
| One combined read-only ROS CLI batch exceeded its local 30-second timeout | 1 | No goal was issued; split action, TF, lifecycle, and diagnostics into bounded calls, then continued without restarting the healthy stack |
| The single goal aborted after 0.843 m because DWB reported `No valid trajectories out of 335` near the cone | 1 | Honored the one-attempt contract: no retry/second goal; verified continuous zero command, preserved evidence, and precisely tore down the Phase 102 stack |
| Initial SIGINT teardown left the launch root and three Python cone/bridge children alive | 1 | Identity-checked exactly PIDs 7566/7578/7584/7586, escalated only those to SIGTERM, and verified all ROS/UDP/container residue empty |

## Current Update - 2026-08-13 Phase 100 formal startup-chain hardening
Harden the formal `scripts/start_competition.sh --cone-avoidance` path so a clean Jetson shell always loads Foxy, the pinned `NonPersistentVoxelLayer` overlay, the Nav2 BT overlay, and the formal install in that order. Fail before cleanup, Docker, or D455 ownership if provenance is incomplete, and print success only after the formal runtime acceptance gate passes. Do not change cone perception, costmap tuning, the experimental overlay, or authorize L4.

### Phase 100: Make formal cone startup reproducible and fail closed
- **Status:** complete (focused local L0/L1 passed; commit `03eb780` pushed; Phase 101 runtime verification started)
- [x] Add independent `CONE_PLUGIN_OVERLAY_SETUP` and `NAV2_BT_OVERLAY_SETUP` inputs with the required source order and cone-only fail-fast behavior.
- [x] Before any runtime mutation, resolve all three required ROS packages and prove the plugin XML plus shared library exist; capture a startup provenance snapshot.
- [x] Replace the unconditional completion banner with a fail-closed gate for five active lifecycle nodes, `/cmd_vel` actuator-subscription expectations, scan endpoint QoS, scan rate, continuous cone health, and live plugin parameters.
- [x] Add focused contracts for cone/non-cone dependency behavior, source order, lifecycle success gating, stable/experimental parameter selection, and `3 / 0.20` safety defaults.
- [x] Run the user-approved focused unittest set, Bash syntax, Python AST, real YAML parsing, ROS 2 skill validation, and `git diff --check`; review the diff before commit/push. Full unrelated repository unittest was intentionally skipped to reach Phase 101 sooner.

### Phase 100 Safety Gates
- Phase 100 is local implementation and static/unit verification only. Do not connect to Jetson, stop a D455 owner, start ROS/Nav2, publish a goal/Twist, reconnect Lite3, or enter L4.
- Preserve formal defaults `1.5 / 0.30 / 3.0 / 32 / 32 / 0.02` and gate defaults `3 / 0.20`; never select the experimental overlay by default.
- A failed preflight or runtime acceptance must print an explicit `NO-GO`, suppress the success banner, and exit nonzero.

### Phase 100 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| The first read-only PowerShell PWF-size summary piped directly from a `foreach` block and failed with `An empty pipe element is not allowed` | 1 | No file or runtime state changed; replaced it with an explicit result array before formatting and continued the audit |

### Phase 100 Context
- `planning-with-files` and the ROS 2 navigation/lifecycle/QoS/provenance/bringup/testing guidance were loaded before implementation.
- ByteRover CLI is unavailable on the local host, so no L1-3 history could be recalled; Phase 99 PWF evidence is the authoritative startup-defect source.

### Phase 101: Jetson clean-shell cold-start verification
- **Status:** complete (clean-shell formal cold start GO at `025b320`; exact teardown and historical D455 restoration complete; L4 remains unauthorized)
- [x] Require a clean formal checkout, physical Lite3 isolation, no actuator/Nav2 residue, and an identifiable historical D455 owner before deployment.
- [x] Fast-forward formal deploy to the final Phase 100 fix `025b320`, refresh only the formal package install needed for console entry points, and start with the literal default command `bash scripts/start_competition.sh --cone-avoidance` from `env -i`.
- [x] Accept only the launcher's new GO result plus snapshot proof for overlays/packages/plugin `.so`, five active lifecycle nodes, scan >=8 Hz, continuous health, official live params, experimental overlay absence, and zero `/cmd_vel` subscribers.
- [x] Precisely stop the Phase 101 stack/container and six identity-checked orphan children, restore the same historical D455 container, verify color/depth service, and leave Lite3 isolated. No cone-in/out repetition or L4 occurred.

### Phase 101 Result
- Clean-shell default command passed its own fail-closed gate on formal Jetson HEAD `025b3200f89e4be6714157ef1b9ad708e73037c6`; formal worktree remained clean.
- Snapshot proved Foxy -> pinned plugin -> Nav2 BT -> formal install, the official base/cone YAMLs, five lifecycle nodes `active [3]`, `/cmd_vel` actual/expected subscribers `0/0`, and controller mapping the resolved pinned plugin library.
- Live official values remained `1.5 / 0.30 / 3.0 / 32 / 32 / 0.02`; safety gate remained `3 / 0.20`. The experimental overlay was not selected.
- Read-only runtime probe passed with 101 scans at `10.0018 Hz`, 100/100 continuously healthy frames, sequence `2029 -> 2128`, maximum source age `37.635 ms`, and zero errors.
- Evidence: `/home/superwfx666/competition_logs/cone_l2_l3/20260813_032123_phase101_cold_start` and `/home/superwfx666/Desktop/logs/competition_startup_20260813_035430.txt`.
- Final state: Phase 101 container absent; ROS/Nav2/cone/bridge and UDP 43893/19002/19012 residuals empty; historical D455 container ID `cadfa809...` is the sole running container, OOM=false, color about `29.17 Hz`, depth about `59.94 Hz`; Lite3 remains no-carrier and unreachable.

### Phase 101 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Local orchestration attempted to use unavailable JavaScript `TextEncoder` before sending the first remote audit | 1 | No Jetson command was sent; switched to PowerShell UTF-8 Base64 encoding for all multiline remote scripts |
| First cold start correctly NO-GO because the formal install had stale console entry-point metadata; the initial decision to skip colcon rebuild was wrong | 1 | Exact teardown, historical D455 restoration, then package-limited rebuild of `quadruped_robot_competition`; verified all three cone/arbiter entry points before retry |
| The first NO-GO cleanup left the newly created cuVSLAM container running, and historical D455 restoration briefly produced two running containers | 1 | Immediately stopped only the exact new container, restored single-owner state, and added identity-recorded new-container cleanup to `startup_no_go` in commit `5972642` |
| Rebuilt entry points were still invisible at runtime because the launcher overwrote `PYTHONPATH` after sourcing the formal install | 2 | Removed the overwrite, preserved the formal overlay path, and added pre-D455 `pkg_resources.load_entry_point` checks in commit `9dbcb79` |
| Foxy verbose topic info uses long `RMW_QOS_POLICY_RELIABILITY_*` names, while the first gate parsed only short reliability names | 1 | Accepted both Foxy long and short formats without relaxing endpoint-count equality in commit `aa82740` |
| Controller mapped the symlink-install build-path target while the first runtime check compared its map line to the install prefix text | 1 | Resolve both the installed library and `/proc/maps` path with `readlink -f` and require exact identity; committed as `025b320` |
| After accepted-run root teardown, six identity-checked Nav2/cone orphan processes remained | 1 | Sent SIGINT only to those exact PIDs, then SIGTERM only to survivors; final process and UDP checks were empty |

## Current Update - 2026-08-13 Phase 99 formal deploy and stationary persistence regression
Fast-forward the clean formal Jetson checkout from `941bed6503f22d76a7bc9017757876e047f9d03c` to the pushed Phase 98 commit `ca7d61ed0993228a648abb23cccddb537099d4c4`, rebuild the formal packages, prove the default cone runtime uses `observation_persistence=1.5` and `CONE_SCAN_MIN_HEIGHT=0.05` without the experimental overlay, then rerun the stationary real-D455 L3-D persistence acceptance. Retain physical Lite3 isolation, publish no navigation goal or velocity command, and do not enter L4.

### Phase 99: Deploy Phase 98 and rerun stationary L3-D
- **Status:** complete (scope reduced by user after one valid cone-in/out cycle; no repeatability claim and no L4 authorization)
- [x] Run read-only Jetson connectivity, formal-checkout, Lite3 isolation, D455 ownership, forbidden-process, and `/cmd_vel` subscriber gates.
- [x] Fast-forward the clean formal checkout to exact `ca7d61e`; rebuild formal packages and verify package/config provenance.
- [x] Run a stationary no-actuator cone smoke and prove the runtime snapshot selects the formal overlay, `CONE_SCAN_MIN_HEIGHT=0.05`, and no experimental overlay.
- [x] Capture one user-approved real-cone clear/cone-in/cone-out cycle timed from the final cone-bearing source scan; the user stopped the planned second/third repetitions, so no repeatability claim is made.
- [x] Verify live 3-frame/0.20 s gate parameters, zero actuator subscribers, zero navigation goals/external commands, and healthy scan/odometry resources; no fresh fault-injected gate transition was requested after the user stopped testing.
- [x] Teardown only exact Phase 99 processes/container, restore and verify the historical D455 owner, and record `GO_WITH_SINGLE_VALID_CYCLE`.

### Phase 99 Result
- Formal Jetson deploy is clean at `ca7d61ed0993228a648abb23cccddb537099d4c4`. Retry 2 loaded the pinned `NonPersistentVoxelLayer` library plus the Nav2 BT overlay, and all five managed Nav2 nodes became active.
- Live formal values were persistence `1.5`, scan minimum height `0.05`, inflation `0.30/3.0`, DWB `32/32/0.02`, and gate `3/0.20`; the experimental overlay was not selected.
- The accepted stream was 180-beam `base_link` BEST_EFFORT scan at `10.0007 Hz`, maximum source age `37.677 ms`, with continuous healthy frames and zero `/cmd_vel` subscribers.
- One real `0.75 m` cone cycle passed. The corresponding cone connected region cleared `1989.951 ms` after the final cone-bearing source scan, within the `2500 ms` contract. The complete stationary local hash returned to baseline at `2589.949 ms` and remained stable; the global hash never changed.
- The user ended testing after the first valid cycle. Result is `GO_WITH_SINGLE_VALID_CYCLE`, not a three-cycle repeatability acceptance. L4 remains unauthorized.
- Evidence: `/home/superwfx666/competition_logs/cone_l2_l3/20260813_021100_phase99_smoke_retry2`.
- Exact retry-2 processes and container were removed without `stop_all.sh`. Historical `d455_yolo_repro_20260811` was restored with unchanged normalized configuration, color `29.401 Hz`, depth `59.900 Hz`, and OOM=false. Lite3 remained no-carrier/unreachable.

### Phase 99 Safety Gates
- Any dirty formal worktree, non-fast-forward update, wrong target HEAD, reachable Lite3 control link, actuator subscriber, forbidden bridge/TaskManager process, wrong runtime parameter file, or experimental-overlay selection is an immediate stop condition.
- Never pass `--dog`, `--cmd-vel-bridge`, `--task-manager`, or `--auto-advance`; never publish a navigation goal or Twist; do not enter L4.
- Keep the robot stationary and Lite3 physically isolated. Only an on-site person may move the cone after the remote runtime and graph gates pass.
- Preserve the pre-existing D455 container identity/configuration and restore it after acceptance. Teardown must target only exact Phase 99 processes and containers.

### Phase 99 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| The initial preflight tested the legacy path `/home/superwfx666/quadruped-robot-competition-nav2-dwb` with a directory-only `.git` check, while the historical D455 container was stopped with exit 137 shortly before the audit | 1 | A Git-aware audit showed the legacy path is a highly dirty linked worktree at `72e3833` and must remain untouched; the authoritative formal checkout is `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy` at `941bed6`. Container finish time `17:38:16Z`, host boot around `17:41:12Z`, and OOM=false corroborate the user's Jetson-reboot explanation |
| Jetson Python 3.8 could not import `tests.test_cone_avoidance_contract` or `tests.test_cone_l2_l3_contract` because `tests/` is not a Python package | 1 | The command stopped before build and made no source change; rerun the same files through `unittest discover -s tests -p <filename>` with repository `src` on `PYTHONPATH` |
| Phase 99 startup did not reach the Host/Foxy verification stage within the 180-second monitor ceiling, although the exact cone container appeared and cuVSLAM odometry began tracking | 1 | Preserve the live single-owner stack; inspect the top-level, cuVSLAM, container, and process logs read-only to determine whether the cone pipeline is delayed, failed, or the startup script is still progressing before choosing any targeted recovery |
| The first L4 audit shell sourced `/opt/ros/foxy`, the Nav2 BT `local_setup.bash`, and the formal `local_setup.bash`, then incorrectly required the pinned nonpersistent plugin prefix from that new shell; `ros2 pkg prefix nonpersistent_voxel_layer` was empty and stopped the audit after runtime/container checks | 1 | Do not alter the healthy live stack. Read `controller_server`'s actual `/proc/<pid>/environ`, command line, and live plugin parameters, then reproduce the process environment by sourcing the pinned plugin `local_setup.bash` explicitly for the remaining read-only audit |
| The follow-up process audit used `pgrep -x controller_server`, which returned no PID because Linux process `comm` names are limited/truncated for long executable names | 1 | No live state changed; find the process by its full `/proc/<pid>/cmdline` pattern, corroborate it with the live ROS node, and then inspect that exact PID |
| Phase 99 smoke attempt 1 reached the launcher's printed completion banner, but live lifecycle states were `map_server/planner_server=inactive` and `controller_server/bt_navigator/recoveries_server=unconfigured`; cone-layer parameters were undeclared and no nonpersistent plugin library was mapped | 1 | Reject the smoke despite the banner. Preserve evidence, read the competition/lifecycle logs for the exact configure failure, then precisely teardown only attempt-1 processes/container and restart with both the pinned plugin and Nav2 BT overlays in the inherited environment |
| Retry-2 preflight used `set -e` while intentionally expecting the Lite3 ping to fail, so it exited after recording the physical-isolation state and before the combined-overlay check | 1 | No runtime started; rerun the preflight with the ping return code captured explicitly, then require the complete clean/process/port/container/package-prefix gate before startup |
| The combined read-only runtime audit exceeded the local SSH helper's 90-second wait while Foxy CLI accumulated lifecycle, parameter, endpoint, action, and 10-second scan queries | 1 | The remote audit completed cleanly seconds later and left no probe process. Read the completed evidence files, then use smaller bounded queries for remaining live checks |

## Current Update - 2026-08-13 Phase 98 cone obstacle persistence and scan-height hardening
Implement the reviewed cone-only configuration changes without changing the accepted inflation or DWB defaults: retain cone observations for 1.5 seconds, make the pointcloud-to-scan minimum height safely configurable with a byte-compatible 0.05 m default, revise the stationary acceptance timing contract, and provide an opt-in cone-only experiment overlay for inflation/DWB tuning. Do not deploy to Jetson or run hardware/motion tests in this phase.

### Phase 98: Harden cone memory and prepare isolated tuning experiments
- **Status:** complete (local L0/L1 only; Jetson/ROS/hardware validation pending)
- [x] Set `cone_scan.observation_persistence` to `1.5` only in the cone overlay; keep the global costmap and non-cone modes unchanged.
- [x] Add validated `CONE_SCAN_MIN_HEIGHT` propagation to the generated Humble launch, help text, and runtime configuration snapshot with default `0.05`.
- [x] Add or update contract tests for the persistence value, float/range validation, generated launch value, runtime snapshot, and default-path isolation.
- [x] Revise the L3-D runbook to time clearing from the final cone-bearing scan and preserve appropriate global/static hash checks.
- [x] Add a complete opt-in cone-only experiment overlay for `0.45/2.0` inflation and candidate DWB critic weights, without wiring it into the default launcher.
- [x] Run focused tests, shell/Python/YAML validation, broader relevant regression tests, and `git diff --check`.

### Phase 98 Result
- Formal cone overlay now retains observations for `1.5 s`; accepted inflation remains `0.30/3.0`, base DWB remains `PathAlign=32`, `PathDist=32`, `ObstacleFootprint=0.02`, and safety-gate defaults remain 3 frames / 0.20 s.
- `CONE_SCAN_MIN_HEIGHT` defaults to `0.05`, accepts canonical floating literals in `[0.0, 1.20)`, rejects wrong types/ranges/injection text before Docker checks, is written to the generated launch and runtime evidence, and is AST-validated after generation.
- The L3-D contract now measures from the final cone-bearing source observation with an initial `2.5 s` ceiling, preserves global hashing, and adds stationary local clear-baseline hashing; moving rolling costmaps use spatial/count evidence.
- The `0.45/2.0` inflation and `16/16/0.05` DWB candidates live only in `nav2_cone_obstacles_experimental.yaml`. The default launcher never names this file; explicit `CONE_NAV2_PARAMS_FILE` selection is required and its path is logged.
- Verification: full local unittest discovery `253/253` passed with repository `src` on `PYTHONPATH`; both overlays passed real YAML parsing and type/value assertions; four Python files passed AST parsing; both shell scripts passed `bash -n`; valid height values `0.0/0.05/0.12/1.19` passed preflight; `git diff --check` passed.
- No Jetson deployment, ROS graph, D455, Docker container, Lite3 link, navigation goal, or motion test was run. L3-D persistence retest and L4 field gates remain separate work.

### Phase 98 Safety Gates
- Do not connect to Jetson, start ROS, claim L3/L4 validation, publish a navigation goal, or command the robot.
- Keep `required_consecutive_frames=3` and `health_timeout_sec=0.20` unchanged.
- Do not change the accepted cone inflation/DWB defaults; candidate values must remain explicit opt-in experiments.
- Preserve global-costmap static-only behavior and all static/depth-mode defaults.

### Phase 98 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Initial repository search included a nonexistent `quadruped_robot_competition` directory and returned exit code 1 after printing valid matches | 1 | No files were changed; repeated the read-only search using only paths that exist in this checkout |
| A second read-only search named nonexistent root `CMakeLists.txt`, and the default Windows Python lacks PyYAML | 1 | No business files were affected; removed the optional path from searches and use repository contract tests plus an available workspace runtime or an explicit parser-gap report for YAML validation |
| Python 3.14 `py_compile` could not replace an existing `tests/__pycache__` entry (`WinError 5`) | 1 | Do not modify or delete the existing cache; rerun tests with `PYTHONDONTWRITEBYTECODE=1` and parse Python files through `ast` without filesystem writes |
| Focused contract suite retained an assertion for the old two-snapshot variable names `before/after` after the runbook introduced explicit local/global names | 1 | Updated the existing assertion to require `global_before/global_after`; the new dedicated test separately requires the local clear-baseline hash invariant |
| Full unittest discovery imported eight `nodes.navigation.*` test modules without the repository `src` directory on `PYTHONPATH` | 1 | The run executed 224 cases and showed import-environment errors only; rerun the same discovery with the repository `src` path explicitly prepended |

## Current Update - 2026-08-13 Phase 97 formal cone-avoidance deployment smoke
Fast-forward the formal Jetson deploy checkout to `941bed6503f22d76a7bc9017757876e047f9d03c`, promote the accepted cone runtime image, rebuild the formal Foxy packages, and run only the stationary cone-avoidance module while the Lite3 control link remains physically disconnected. Restore the historical D455 container after acceptance without invoking any generic cleanup that publishes Twist.

### Phase 97: Upgrade and smoke-test formal cone deployment
- **Status:** complete (formal stationary cone smoke GO; historical D455 restored; L4 remains blocked)
- [x] Require a clean formal checkout, create the requested backup branch, diagnose the non-fast-forward history, and switch the formal checkout to user-selected branch `codex/formal-cone-941bed6` at exact target `941bed6` while preserving both old branches.
- [x] Tag the accepted image as `isaac_ros_cuvslam_runtime:humble-rs-cone`, or build it only if the accepted image ID is absent; validate `pointcloud_to_laserscan` offline.
- [x] Rebuild `whz` and `quadruped_robot_competition`, then verify package prefixes resolve to the formal checkout and pinned plugin workspace.
- [x] Reconfirm `eth0` has `NO-CARRIER`, no address, and Lite3 is unreachable before changing camera ownership.
- [x] Save the historical D455 container inspection, stop it, and start only `scripts/start_competition.sh --cone-avoidance` with no actuator/task/navigation-goal options.
- [x] Verify zero `/cmd_vel` subscribers, BEST_EFFORT cone scan publication, continuously healthy cone health, active Nav2/controller lifecycle, and absence of Lite3/TaskManager/velocity-bridge processes.
- [x] Interrupt only this smoke-start process, stop only its cuVSLAM container, restore the historical D455 container, and verify color/depth rates near 30/60 Hz.

### Phase 97 Result
- Formal stationary cone deployment smoke is GO on branch `codex/formal-cone-941bed6` at exact commit `941bed6503f22d76a7bc9017757876e047f9d03c`; formal worktree is clean. Original formal and backup branches remain at `b1ae5af`.
- Accepted image ID `sha256:3062ea205303...` is tagged `isaac_ros_cuvslam_runtime:humble-rs-cone`; offline `pointcloud_to_laserscan` package/executable validation passed. Both Foxy packages rebuilt with correct formal/pinned-plugin prefixes.
- Retry 2 used the startup script's existing `NAV2_OVERLAY_SETUP` variable to select `nav2_foxy_overlay_ws/install/local_setup.bash`, avoiding the full overlay setup that chains the legacy repository. Formal competition/cone executables and Nav2 configs all resolved to the deploy checkout.
- `/cmd_vel` had one cone safety-gate publisher and zero subscribers. Host scan had one BEST_EFFORT publisher and one BEST_EFFORT local-costmap subscription. All five managed Nav2 nodes were active. No Lite3, TaskManager, velocity-bridge process, or navigation-goal publisher existed.
- Continuous evidence: 30/30 health frames true, sequence `4265 -> 4294` strictly increasing, max source age `27.512 ms`, reason `ready`; scan rate `10.003 Hz`.
- Teardown targeted only exact Phase 97 PID trees and container `5f14eac62fd4`; no teardown call to `stop_all.sh`. Historical D455 container `cadfa809e7b2...` is the only running container, OOM=false, color `29.157 Hz`, depth `59.920 Hz`.
- Final safety state: `eth0` remains `NO-CARRIER/DOWN` with no address; Lite3 is unreachable; no cone/Nav2/bridge/TaskManager/Lite3 process remains. This does not authorize L4 or reconnection/motion.

### Phase 97 Safety Gates
- Any dirty formal worktree, non-fast-forward history, wrong target HEAD, failed image/package check, reachable Lite3 link, actuator subscriber, forbidden process, navigation goal, unhealthy cone stream, or inactive Nav2/controller is an immediate stop condition.
- Never pass `--dog`, `--cmd-vel-bridge`, `--task-manager`, or `--auto-advance`; never publish a navigation goal.
- Do not use the generic cleanup script because it may publish zero Twist. Teardown must target only the exact Phase 97 launcher/process group and cuVSLAM container created by this run.
- L4 remains out of scope; do not reconnect Lite3 or perform motion.

### Phase 97 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| The first SSH Git gate passed a multiline quoted script through the legacy argument-joining helper; inner quoting was stripped, producing an ambiguous literal `n` as status and triggering the dirty-tree stop before fetch or branch creation | 1 | Treat the result as an execution-wrapper failure, not evidence of a dirty tree; transmit subsequent remote scripts as Base64 and decode them directly into Bash |
| The authoritative `git merge-base --is-ancestor b1ae5af 941bed6` returned 1 after a successful fetch and backup-branch creation | 1 | Stopped exactly as required; no merge, image, build, container, or ROS action was performed. Read-only graph inspection found merge base `97ca3ef` and a `4 / 10` divergence, so an explicit replacement history strategy is required |
| The exact user-required `bash scripts/start_competition.sh --cone-avoidance` internally invokes `bash scripts/stop_all.sh` at line 81 as startup pre-cleaning, despite teardown instructions forbidding the generic cleanup | 1 | Do not invoke it separately and do not repeat it during teardown. The internal call occurred while Lite3 was physically disconnected, no container/ROS node was running, and no actuator path existed; teardown will target only exact Phase 97 processes/container |
| First formal smoke sourced the formal prefix but launched package executables and Nav2 parameter files from legacy `/home/superwfx666/quadruped-robot-competition-nav2-dwb`; Host cone scan/health never appeared | 1 | Captured zero `/cmd_vel` subscribers, active controller, zero goal publishers, and no forbidden process, then rejected the run for provenance and missing cone topics. Precisely interrupted only the launch/bridge PID trees, stopped only the Phase 97 container, restored historical D455, and diagnose stale symlink/build metadata before retrying |
| Parent-only SIGINT did not terminate all backgrounded ROS Python processes; the first remote cleanup call also outlived the SSH helper's 30-second read timeout | 1 | Reconnected to verify exact state, recursively fixed the Phase 97 PID list, delivered SIGINT to that list, then SIGTERM only to the three non-responsive exact PIDs; all selected ROS processes exited without generic cleanup |

### Phase 97 Decision
- User selected option 1: create `codex/formal-cone-941bed6` at exact target `941bed6` in the formal checkout, preserving the original formal branch and backup branch unchanged.

## Current Update - 2026-08-12 Phase 96 Jetson cone avoidance L3-D
Execute only the stationary real-D455 cone-avoidance acceptance after L2 and L3-S GO, while retaining the operator-confirmed physical disconnection between Jetson and Lite3. Use the clean Phase 93 acceptance worktree because the formal deploy does not contain the cone runtime. Validate single D455 ownership, real scan/health/QoS/TF, zero actuator subscribers, local-only costmap marking and clearing, gate timing, and A/B resources. Do not send a navigation goal or enter L4 motion.

### Phase 96: Execute real D455 stationary acceptance
- **Status:** complete (L3-D GO; historical `d455_yolo_repro_20260811` restored and verified)
- [x] Audit the accepted startup script, environment/source order, runtime provenance, D455 availability, forbidden processes, UDP port 19002, and `/cmd_vel` subscriber state without starting the stack.
- [x] Start the baseline and cone-enabled stationary stacks with no dog/bridge/task-manager flags; prove single D455 ownership and the expected Humble/Foxy cone processes.
- [x] Capture real scan rate, 180-beam `base_link` semantics, QoS, health/source age, and gate state; stop on any `/cmd_vel` actuator subscriber or scan rate below 8 Hz.
- [x] Record clear/cone-in/cone-out markers and costmap evidence; require local marking, clear within 1 second, unchanged global data, and no late local marking after gate allow.
- [x] Capture comparable 90-second warmup plus 60-second A/B resource and odometry-rate evidence.
- [x] Clean all started processes/containers, verify both Git worktrees remain clean, restore the original D455 container, and record L3-D GO.

### Phase 96 Result
- L3-D GO. Evidence: `/home/superwfx666/competition_logs/cone_l2_l3/20260812_185325_phase96_l3d/B3_reconnect_20260812_222610`.
- The real cone at a `0.75 m` center-axis horizontal distance produced a coherent approximately `0.742-0.822 m` scan cluster and changed only the local costmap. The local map returned byte-for-byte to the clear baseline in `259.780 ms`; the global data hash remained unchanged.
- B-mode Host scan was `9.985 Hz`; health was `298/298` healthy; odometry was `27.615 Hz` versus A `30.010 Hz`, a `7.981%` drop within the `10%` limit; no OOM or sustained throttling was observed.
- During the formal B3 clear/cone-in/cone-out sequence, no navigation goal or speed command was published; `/cmd_vel` retained zero subscribers and Lite3 remained physically unreachable. Earlier failed Phase 96 cleanup attempts had invoked the generic `stop_all.sh`, which may briefly publish zero Twist, but those attempts also had zero actuator subscribers and a physically disconnected Lite3 link.
- The temporary B3 stack, recorder, watchdog, and Host processes are gone. The same historical container ID `cadfa809e7b2...` is running with its original image/command; color is `29.965 Hz`, depth is `59.846 Hz`, and OOM is false. Formal deploy `b1ae5af` and acceptance worktree `6a69b93` remain clean.

### Phase 96 Safety Gates
- Retain the explicit operator confirmation that the Jetson-to-Lite3 control link is physically disconnected; any evidence that the link/process chain has returned is an immediate stop condition.
- Use `/home/superwfx666/cone-l2-l3-acceptance-6a69b93`; do not modify or run the formal deploy for cone acceptance because it lacks the Phase 93 cone runtime.
- Do not source the contaminated legacy Nav2 overlay unless a read-only provenance audit proves it is required and does not shadow the acceptance worktree; prefer the pinned `nonpersistent_voxel_layer` overlay plus acceptance `local_setup.bash`.
- Do not pass `--dog`, `--cmd-vel-bridge`, `--task-manager`, `--auto-advance`, or publish a navigation goal. `/cmd_vel` must have zero actuator subscribers throughout.
- The robot, D455 mount, and support remain stationary. Only an on-site person may move a cone into or out of the D455 view.

### Phase 96 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Read-only startup gate showed `ip route get 192.168.1.120` via `eth0` source `192.168.1.111`, and ping succeeded in `0.748 ms`, contradicting the assumed physical Jetson-to-Lite3 disconnection | 1 | Stop before `stop_all.sh`, Docker, D455, ROS/Nav2, or any command topic starts; require the on-site operator to physically verify and disconnect the Lite3 control network, then rerun the gate |
| Baseline A startup created the D455/cuVSLAM path but `competition.launch.py` failed before Nav2 because disabled WHZ still resolves `FindPackageShare("whz")`, while the acceptance install contained only the main package; the harness then treated the absent `/cmd_vel` topic as a subscriber failure | 1 | Cleanup ran before any goal/actuator path; explicitly stopped the exact Phase 96 container left by `stop_all.sh`, confirmed zero residuals, and build the acceptance worktree's own `whz` package before retrying with a gate that accepts an absent `/cmd_vel` as zero subscribers only if required Nav2 nodes are independently present |
| Baseline A attempt 2 passed Nav2, zero-subscriber, and single-D455-owner gates, then failed because Foxy `ros2 topic echo` does not support Humble's `--once` argument | 1 | The container-diff cleanup stopped the exact new container and zero residuals were confirmed; use bounded `timeout ros2 topic echo` plus content validation on Foxy instead of repeating `--once` |
| Baseline A attempt 3 completed 59 tegrastats samples and 12 Docker samples, but the Host Foxy command recorded an empty Humble `/visual_slam/tracking/odometry` rate file; the forbidden-process substring also matched the harmless launch argument `enable_task_manager:=false` | 1 | Keep the complete resource evidence, measure odometry inside the Humble container after a fresh 90-second baseline warmup, and replace substring process checks with exact ROS node/process identity checks |
| During the baseline odometry补采, historical container `d455_yolo_repro_20260811` was externally started at 19:12 and exclusively opened D455, causing `VIDIOC_S_FMT` device-busy/input-output failures in the cone acceptance cuVSLAM startup | 1 | Cleanup removed all Phase 96 processes; do not stop or modify the unrelated container without user authorization. L3-D cannot continue until it is temporarily stopped and later restored, or the external owner releases D455 |
| Cone-enabled mode B container exited before creating any ROS node because the pinned Isaac ROS Humble image cannot resolve package `pointcloud_to_laserscan`; the launcher used `--rm`, so the exited container object was removed before later inspection | 1 | Preserve `/home/superwfx666/cuvslam_lite3_logs/20260812-201703/launch.log` as the authoritative failure evidence; do not repeat B until the existing image/startup path is audited and a pinned, reversible dependency fix is validated |
| First no-device image probe enabled `set -u` before sourcing Humble, so `/opt/ros/humble/setup.bash` failed on unset `AMENT_TRACE_SETUP_FILES` | 1 | The temporary `--rm` probe container exited without device mounts or ROS nodes; source Humble before enabling strict unset-variable checks |
| Second no-device image probe let inner Bash expand `${Package}` in a `dpkg-query` format string under `set -u`, aborting before apt policy output | 1 | Remove the unnecessary custom format and nounset mode; the third read-only probe established the exact apt candidate version without runtime residue |
| First B2 delivery used a one-second local SSH timeout; the connection ended before Jetson created the evidence directory, so the harness never started | 1 | Confirmed zero container/process residue and the historical D455 container still stopped; redeliver the same gated harness through a persistent Jetson-side `nohup` wrapper and capture its remote PID/log |
| Cone-enabled startup performed a single immediate Humble topic-list check after cuVSLAM odometry appeared and falsely reported that the cone scan pipeline was absent; the same live container then showed the topic, publisher, exporter, and continuously advancing healthy sequence | 1 | Reused the existing single-owner container and reran only the Host/Foxy startup after DDS discovery settled; fix the production startup check to use a bounded retry before finalizing L3-D |
| The first B2 safety process grep matched the harmless launch argument `enable_task_manager:=false`, and a separate check sourced Foxy under inherited nounset | 1 | `/cmd_vel` was already proven to have zero subscribers; reran with exact ROS node/process identities and source-before-strict ordering, which passed all safety/provenance gates |
| Foxy `ros2 topic hz /cone_obstacle/scan` produced no piped output before timeout, although a custom 10-second subscriber received 98 scans | 1 | Use the custom monotonic subscriber count/interval evidence as the formal Host rate measurement and retain Humble `ros2 topic hz` only as the raw-side cross-check |
| Local combined cone regression omitted the repository `src` directory from `PYTHONPATH`, so three pure-Python test modules could not import `nodes`; the 28 contract tests that did import all passed | 1 | Rerun the complete focused set with the repository `src` prepended to `PYTHONPATH`, matching the project's established test invocation |
| Jetson Tailscale/SSH became unreachable while B2 was awaiting the manual clear/cone-in/cone-out step; Tailscale reported the host offline and both bounded pings timed out | 1 | Do not assume remote state or continue field actions; the previously installed Jetson-side watchdog is scheduled to clean B2 and restore `d455_yolo_repro_20260811`, and restoration must be verified first when connectivity returns |
| After the operator reconfirmed physical Jetson-to-Lite3 isolation and authorized temporary D455-container interruption, Jetson remained offline (`last seen 21m ago`) and two bounded reconnect probes received no Tailscale/SSH reply | 2 | No remote command was delivered. Keep Phase 96 in progress and require a fresh container/process/network/ROS provenance check before either accepting historical D455 restoration or restarting cone mode B |
| Resumed B3 started the cone scan pipeline, but the first odometry UDP exporter exited during DDS discovery; Host `/odom` and TF were absent, leaving costmaps unconfigured | 1 | Reuse the same single-owner D455/cuVSLAM container and restart only the non-actuating odometry bridge after independently proving the Humble odometry publisher exists |
| The first two odometry bridge restarts failed because the container's `/tmp/cuvslam_odometry_udp_exporter.py` was a stale host-absolute symlink, so `docker cp` could not replace it with a usable container file | 2 | Remove only that B3 container-local temporary link, copy the verified regular exporter source explicitly, and restart the Host bridge; `/odom`, `odom -> base_link`, and all managed Nav2 lifecycle nodes then became active |
| The initial Foxy rosbag recorded zero `/cone_obstacle/scan` messages because the publisher is BEST_EFFORT and the recorder was started without an explicit compatible QoS override | 1 | Preserve the complete five-topic bag and independent live scan captures, add `configs/ros/cone_rosbag_qos.yaml`, and verify a recovery bag records 55 scan plus 55 health messages with SQLite integrity `ok` |
| Controlled teardown stopped an auto-remove B3 container, then `docker rm` raced with Docker's automatic removal and returned `No such container` before historical D455 restoration | 1 | Recheck exact container/process state instead of repeating cleanup; confirm B3/watchdog/Host processes are gone, then start the same historical container ID and perform full topic/rate/config verification |
| Local post-check could not import PyYAML while parsing `configs/ros/cone_rosbag_qos.yaml` | 1 | Do not install or mutate the host for a redundant parser check; the Foxy Jetson recorder already loaded the exact file and recorded 55 BEST_EFFORT scan messages, while the contract test verifies the required keys |

## Current Update - 2026-08-12 Phase 95 Jetson cone avoidance L3-S
Execute only section 5 of the cone avoidance runbook on the Jetson after fresh physical no-actuator confirmation: run the isolated synthetic UDP/ROS acceptance on loopback, ROS domain 93, UDP port 19012, and `/cone_l3/*`; validate the complete JSON evidence and cleanup. Do not start controller/Nav2/D455/cuVSLAM, use production topics or ports, publish a navigation goal, or connect to Lite3.

### Phase 95: Execute isolated synthetic cone-scan acceptance
- **Status:** complete (L3-S GO; evidence at `/home/superwfx666/competition_logs/cone_l2_l3/20260812_183742_phase95_l3s`)
- [x] Reconfirm the section 5 command surface, required JSON steps, latency limit, graph-isolation invariant, and cleanup checks from the accepted runbook and contract tests.
- [x] Obtain fresh physical no-actuator confirmation from the on-site operator.
- [x] Run the isolated L3-S probe in the accepted Jetson worktree and write `l3_synthetic.json` into a new evidence directory.
- [x] Independently validate schema, all required steps, maximum fail-closed latency <= 250 ms, allowed child exit codes, and the sole subscriber on `/cone_l3/cmd_out`.
- [x] Confirm no bridge/gate/probe or domain-93 process remains, then record L3-S GO/NO-GO.

### Phase 95 Safety Gates
- The `--confirm-isolated-no-actuator` flag represents an on-site physical fact and must not be supplied until the operator confirms power-off or physical control-link disconnection.
- Use only `ROS_LOCALHOST_ONLY=1`, ROS domain 93, UDP `127.0.0.1:19012`, and `/cone_l3/*` topics.
- Do not start `controller_server`, Nav2, D455/cuVSLAM, Lite3 drivers/bridges, TaskManager, action goals, or any production velocity publisher.
- `/cone_l3/cmd_out` may carry a synthetic nonzero Twist only when its unique subscriber is the acceptance probe; it must never be remapped to `/cmd_vel`.

### Phase 95 Result
- Three isolated runs passed all 13 required steps; bridge and gate exited with code 0 after every run.
- Silence fail-closed latency was `249.298 ms`, `249.254 ms`, and `249.221 ms`; the maximum passed the `250 ms` contract with only `0.702 ms` margin, so L3-D must retain latency/resource observation under real D455 load.
- Final checks found no cone/controller/Nav2/Lite3/TaskManager process, no UDP 19012 listener, and no change to either the formal deploy or acceptance worktree.

## Current Update - 2026-08-12 Phase 94 Jetson cone avoidance L2
Execute only section 4 of the cone avoidance runbook on the Jetson: preserve the formal deploy checkout, create an isolated acceptance worktree at the exact Phase 93 commit, capture provenance, verify the Foxy plugin, build the package, and perform controller configure-only validation on localhost ROS domain 93. Do not activate the controller, start D455/cuVSLAM, publish commands/goals, or run L3 in this phase.

### Phase 94: Execute Jetson L2 dependency and configure-only acceptance
- **Status:** complete (L2 GO; evidence at `/home/superwfx666/competition_logs/cone_l2_l3/20260812_164907_phase94_l2`)
- [x] Create a recoverable isolated Jetson worktree for commit `6a69b93` without changing the formal deploy checkout at `b1ae5af`.
- [x] Capture clean provenance, source hashes, forbidden-process state, Foxy/Nav2 package versions, and `NonPersistentVoxelLayer` plugin XML evidence.
- [x] Build `quadruped_robot_competition` with Foxy and verify installed cone bridge/gate executables and Python module provenance.
- [x] Start only `controller_server` on localhost ROS domain 93, configure but never activate it, verify the live local costmap plugin list and zero actuator subscribers, then shut it down.
- [x] Confirm no relevant ROS process/container remains and record an L2 GO/NO-GO result.

### Phase 94 Safety Gates
- Preserve `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy` and its current branch/HEAD unchanged.
- Do not run `start_competition.sh`, D455, cuVSLAM, Nav2 lifecycle activation, any Lite3 driver/bridge, TaskManager, action goal, or velocity publisher.
- Use `ROS_LOCALHOST_ONLY=1`, ROS domain 93, and remap controller output to `/cone_l2/cmd_vel`.
- Any pre-existing actuator-capable or navigation process is a stop condition; do not automatically kill unrelated processes.

### Phase 94 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| First remote provenance script sourced Foxy under `set -u`, but Foxy `setup.bash` reads unset `AMENT_TRACE_SETUP_FILES` | 1 | No build/runtime started; keep `set -e -o pipefail` and disable nounset while sourcing ROS setup files |
| Jetson has only system Nav2 `0.4.7`; `NonPersistentVoxelLayer` is absent, and the existing BT overlay setup also injects the legacy repo install prefix | 1 | Do not build against the contaminated setup chain; create a separate pinned `nonpersistent_voxel_layer` 2.2.1 overlay and source only its `local_setup.bash` after `/opt/ros/foxy` |
| First configure-only harness restarted `ros2 service list` every 2 seconds, preventing Foxy DDS discovery from settling and producing a lifecycle-service timeout before any transition | 1 | Controller/local costmap created successfully and the trap removed them; replace the short restart loop with one bounded lifecycle query after a fixed discovery wait |

## Current Update - 2026-08-12 Phase 93 cone avoidance L2/L3 acceptance tooling
Prepare a reproducible no-actuator acceptance path before any Jetson motion test: add a ROS-independent synthetic cone-scan generator, an isolated Foxy bridge/gate runtime probe, and a Chinese Jetson runbook. Resolve the clear-scene ambiguity by treating healthy depth coverage with zero obstacle returns as a valid clear scan while continuing to reject isolated/short finite runs.

### Phase 93: Build and locally validate L2/L3 acceptance tooling
- **Status:** complete (acceptance tooling locally validated at L0/L1; Jetson L2/L3 execution and evidence remain pending)
- [x] Add deterministic 180-beam UDP scenarios for clear space, cone returns, isolated points, stale timestamps, bad CRC, sequence regression, backlog, silence, and stream restart.
- [x] Add an isolated Foxy L3 probe that uses test-only topics/UDP port, proves three-frame warmup and fail-closed timing, and emits machine-readable evidence without any actuator subscriber.
- [x] Add a Jetson L2/L3 runbook covering provenance, dependency/plugin loading, graph ownership, local/global costmap checks, stationary D455 rates/resource A/B, cleanup, and go/no-go criteria.
- [x] Change healthy-depth empty scans from sensor failure to clear-space observations; retain rejection of short finite runs and unhealthy depth coverage.
- [x] Add focused tests and run the complete local non-hardware regression plus syntax/XML/diff validation.

### Phase 93 Safety Gates
- Do not connect to Jetson, launch ROS/Nav2, or send robot commands during local implementation.
- The automated gate probe must use isolated test topics and a non-production UDP port by default.
- Any production-topic or non-zero command test must require an explicit no-actuator runtime gate and is deferred to the Jetson runbook.
- L4 motion remains blocked until L2/L3 evidence passes and a separate physical safety confirmation is obtained.

## Current Update - 2026-08-12 Phase 91 lightweight D455 cone avoidance
Replace the unvalidated shared-file depth/Host point-cloud path with an opt-in, CPU-only cone avoidance path owned by the existing Humble D455 process: RealSense decimation x4 and pointcloud, `pointcloud_to_laserscan` transformed into `base_link`, latest-only UDP, and Foxy `NonPersistentVoxelLayer` on the local costmap only. Preserve cuVSLAM IR/IMU ownership, the static global costmap, existing DWB limits, and a recoverable legacy depth path.

### Phase 91: Implement and locally validate the cone scan pipeline
- **Status:** complete (local L0/L1 implementation; Jetson L2-L6 validation remains a separate gated phase)
- [x] Add a bounded binary LaserScan UDP contract with stream/sequence/source-time/CRC and depth coverage health fields.
- [x] Add the Humble exporter with `BEST_EFFORT + KEEP_LAST 1`, decimated-depth health checks, isolated-return filtering, and latest-frame scan transport.
- [x] Add the Foxy latest-only UDP receiver, source-age/CRC/sequence validation, `base_link` LaserScan publication, diagnostics, and consecutive-frame health gate.
- [x] Add a dedicated fail-closed velocity gate that blocks motion within 250 ms of stale or invalid cone-scan health.
- [x] Add a separate Nav2 overlay using `NonPersistentVoxelLayer` in the local costmap only; leave the global costmap static.
- [x] Wire an explicit `--cone-avoidance` startup mode without enabling the legacy shared-file depth pipeline or a second D455 owner.
- [x] Add focused protocol, health-policy, YAML, launch, and startup-contract tests.
- [x] Run local L0/L1 verification; do not connect to Jetson or perform motion validation in this phase.

### Phase 91 Safety Gates
- Cone avoidance remains opt-in and must never start a second RealSense process.
- The Host receives `base_link` scans only and must not publish or require camera TF.
- Empty/single-point depth health, CRC errors, stale source timestamps, sequence regressions, or UDP silence must fail closed.
- Global costmap and existing DWB motion limits remain unchanged.

### Phase 91 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| ByteRover CLI/MCP was unavailable for the required pre-task long-term-memory query | 1 | Record the absence and proceed from the repository PWF/history without inventing recalled knowledge |
| Neither default nor bundled Windows Python exposed PyYAML for structured config parsing | 2 | Stop repeating the unavailable parser path; retain manual YAML review plus launch/config contract tests and defer ROS parameter loading to L2 |

## Current Update - 2026-08-12 Phase 92 one-click full inspection launcher
Provide a no-argument executable that starts the already accepted four-observation inspection directly, without requiring a separate `--check-only` invocation or manual mode/confirmation flags. Preserve the accepted launcher's internal fail-closed runtime gates and cleanup behavior.

### Phase 92: Add and deploy the direct launcher
- **Status:** complete
- [x] Add a minimal executable wrapper that directly selects `--full --confirm-motion`.
- [x] Prove the wrapper contains no `--check-only` or `--single-d` path.
- [x] Run focused and full local tests, validate Bash syntax on Jetson, deploy with mode 755, and restore a clean formal checkout.
- [x] Confirm deployment without executing the wrapper or starting any robot process.

### Phase 92 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Windows host has no `bash` executable for local `bash -n` | 1 | Keep the passing static/unit checks and run `bash -n` successfully on the target Jetson before commit |
| Remote `stat -c "%a %n"` format was split by the PowerShell/SSH quoting boundary | 1 | No file changed; rerun with the single-token `%a` format and confirm mode `755` |

## Current Update - 2026-08-12 Phase 90 dedicated Nav2 + WHZ inspection runner
Build and deploy a dedicated supervised inspection runner that reuses the proven Nav2 waypoint probe and the validated `inspection_interleaved` route while keeping TaskManager disabled. The runner must execute WHZ only at observation actions, require fresh odometry and a continuous stop before each service call, validate exactly one audio-backed result per observation, abort and clean the stack on any failure, and emit a terminal `FINISH` only after four unique A/B/C/D results.

### Phase 90: Implement, deploy, and validate the dedicated inspection path
- **Status:** complete
- [x] Reuse the proven waypoint probe through a narrow `run_segment()` subclass wrapper without changing the base probe's default navigation behavior.
- [x] Add a dedicated Nav2 + WHZ inspection runner using `inspection_interleaved`, with TaskManager excluded by construction.
- [x] Add a one-click shell wrapper with startup gates, stop-on-failure cleanup, evidence capture, and no automatic motion before operator confirmation.
- [x] Add focused tests for route selection, observation-only WHZ calls, stop gating, A/B/C/D uniqueness, one-shot audio, ABORT, FINISH, and launcher flags.
- [x] Run local static/unit regression and confirm TaskManager, waypoint coordinates, and Nav2 parameters are unchanged.
- [x] Deploy the minimal tested files to the formal Jetson checkout and complete static plus no-actuation provenance/hardware gates; no package rebuild was required because only direct-run scripts and a test were added.
- [x] After fresh route-clear/e-stop/on-site confirmation, run the supervised single-D navigation/recognition sequence and preserve evidence.
- [x] Establish human-audible USB playback in a stationary audio-only gate; process exit status alone is insufficient.
- [x] Run the first four-observation attempt fail-closed, diagnose the second observation's `no_valid_frame`, and deploy a tested full-frame-letter fallback without changing the route or thresholds.
- [x] Return the robot to the official start, reconfirm physical safety, then run the four-observation acceptance.

### Phase 90 Safety Gates
- The formal deploy remains `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy`; do not use the legacy dirty worktree.
- Do not fast-forward the Jetson to mixed local `2034df2`; deploy only the minimal Phase 90 surface on top of `97ca3ef` with a recoverable backup.
- No NavigateToPose goal or robot-mode change until the operator confirms the route is clear, the emergency stop is available, and they are supervising on site.
- A successful WHZ response with `audio_played=true` is never retried; any later contract mismatch aborts to prevent duplicate announcements.

### Phase 90 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Local Git Bash `--check-only` resolved `python3` to the Windows Store placeholder | 1 | No ROS or remote operation ran; add an overridable `PYTHON_BIN` while retaining `python3` as the Jetson default |
| First grouped remote SHA-256 script appended PowerShell CR to its final path | 1 | First two hashes passed and no deploy file changed; verify the third file with a single-line SSH command |
| Remote commit message containing parentheses was stripped by nested PowerShell/SSH quoting | 2 | Staging remained intact; use a shell-safe one-word commit subject |
| Jetson repository had no Git author identity configured | 1 | Do not alter global or repository config; commit with one-command `-c user.name` and `-c user.email` overrides |
| First supervised preflight command lost quotes around remote process/grep patterns through the Windows-to-SSH argument chain | 1 | No ROS or motion started; retain the valid Git/static-contract evidence and rerun only the invalid runtime/hardware checks through a CR-normalized Base64 Bash script |
| First single-D run aborted at the startup stop gate because the runner never serviced a `/cmd_vel` callback (`cmd_age_sec=Infinity`) while the bridge independently received continuous zero commands | 1 | No goal was sent and cleanup passed; move the acceptance-critical `/cmd_vel` sample onto a dedicated executor, validate it without actuation, and require a fresh physical confirmation before another motion run |
| First post-run log tail could not print a Unicode status mark through the Windows GBK console | 1 | No remote state changed; set `PYTHONIOENCODING=utf-8` for subsequent evidence reads |
| First SFTP deployment attempt embedded the Chinese workspace path in stdin Python and Windows replaced `比赛` with `??` | 1 | Upload never started and Jetson stayed clean; derive the local root from `Path.cwd()` and deploy only the two intended files |
| No-actuation arbiter smoke left the `ros2 run` wrapper and child alive after `SIGINT` | 1 | No velocity bridge or robot path existed; verify the two exact PIDs, terminate them with `SIGTERM`, and confirm zero relevant processes |
| Single-D response reported `audio_played=true`, but the on-site operator heard no announcement | 1 | Keep physical audio acceptance failed; the 3-second MP3 and decoder are valid, while USB PCM is only 30% (-20.16 dB). Require a stationary audible test at a higher agreed volume before the full route |
| PowerShell stdin added a carriage return to the first remote `--check-only` argument | 1 | No ROS or motion started; rerun the static contract as a direct SSH command |
| The interrupted first full-run SSH session left the launcher in stack startup | 1 | Send the launcher an interrupt, run the formal `stop_all.sh`, and verify zero relevant processes and cuVSLAM containers before restarting |
| The first full four-observation attempt returned `no_valid_frame` at `pos2a_upper_right` after five successful navigation segments | 1 | Fail-closed cleanup passed; stationary diagnostics proved the red gauge was detected but the A letter was discarded when the anchored crop missed, so add a full-frame-letter fallback and validate it on the exact failed frame plus a fresh live 3-frame batch |
| Root-level `colcon build --packages-select whz` returned success while building zero packages because `whz` is nested under the main package | 1 | Reject the zero-package result and rebuild with `colcon build --base-paths whz --packages-select whz --symlink-install`; verify the package job return code and imported module path |

## Current Update - 2026-08-11 Phase 89 freeze WHZ Phase 1 and integrate TaskManager
Freeze the accepted standalone WHZ service into reviewable Git history, deploy that exact revision to the formal Jetson deploy checkout, then replace TaskManager's inline OpenCV/YOLO path with an arrival-gated asynchronous `/whz/inspect` workflow. Preserve Nav2 parameters, the velocity chain, cuVSLAM, maps, and waypoints. Validate logic locally before any supervised robot motion.

### Phase 89: Freeze, deploy, integrate, and stage field validation
- **Status:** in_progress
- [x] Preserve a recovery ref for `752c652`, split the mixed acceptance commit so the Lite3 test-fixture repair is isolated, verify the rewritten tree, and update the remote branch with lease protection.
- [x] Fast-forward the formal Jetson deploy checkout to the frozen Phase 1 revision, rebuild `whz` and `quadruped_robot_competition`, and verify clean Git/source/install/runtime provenance plus the exact model SHA-256 without launching ROS or moving the robot.
- [x] Replace TaskManager inline WHZ processing with a non-blocking `/whz/inspect` client and an explicit navigation/settling/inspection state machine.
- [x] Add bounded navigation and inspection retries, terminal ABORT behavior, stale-callback rejection, A/B/C/D deduplication, result-schema normalization, and completeness gating.
- [x] Retire the legacy duplicate `/whz/inspect` entrypoint while preserving red-bar YOLO behavior and all frozen navigation/runtime surfaces.
- [x] Add focused pure unit tests and run the complete non-hardware regression suite.
- [x] Deploy the tested Phase 2 revision without starting motion and verify the formal deploy checkout/build/runtime provenance.
- [x] Run the installed TaskManager without a Nav2 server and verify three retries, fourth-attempt ABORT, zero goal send, zero velocity output, and complete cleanup.
- [ ] Run one supervised observation-position workflow after fresh physical safety confirmation.
- [ ] Only after the single-position gate passes, run the complete four-position inspection and verify exactly one A/B/C/D result each.

### Phase 89 Safety Gates
- No navigation launch, action goal, velocity command, robot mode change, or audio test is allowed during Git history cleanup or Phase 1 formal deployment.
- Single-position and four-position motion validation require a fresh operator confirmation that the robot is at the intended start, the route is clear, and the emergency stop is available.
- Phase 2 must not modify Nav2 parameters, maps, cuVSLAM, the velocity chain, or waypoint coordinates.

### Phase 89 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| First read-only Jetson preflight lost nested shell quoting around process patterns | 1 | No deployment command ran; switch to a CR-stripped stdin script for all subsequent SSH operations |
| Root-level colcon discovery ignored nested package `whz`, so the combined selection built only the main package and returned `unknown package 'whz'` | 1 | Confirm `colcon list --base-paths whz` discovers the package, then build it explicitly with `--base-paths whz` and complete provenance checks |
| Local default Python 3.14 has no `pytest` or `setuptools` | 1 | Use the repository's `unittest` runner for tests; rely on Jetson Foxy colcon for packaging validation instead of the unavailable local setuptools probe |
| First full unittest discovery omitted repository `src` and produced five import collection errors | 1 | Prepend the repository `src` directory to `PYTHONPATH`; all 169 tests then passed |
| First TaskManager contract assertion rejected the unrelated map client's legacy `wait_for_service` | 1 | Narrow the assertion to the WHZ client; WHZ remains fully asynchronous and the focused contract suite passes |
| First large TaskManager method patch used stale exact context and did not apply | 1 | Re-read the live function boundaries and replace the method in smaller verified patches; no partial large-patch edit occurred |
| First Foxy API heredoc printed all three successful capability checks but the PowerShell CRLF wrapper evaluated the terminator as Python | 1 | Preserve the successful `True` capability evidence and avoid heredocs; a later one-line retry failed locally before SSH and made no remote change |
| A parallel read-only wrapper included the optional local `学习` directory, which does not exist in this checkout, and returned nonzero | 1 | No state changed; query only confirmed repository paths and keep independent read results isolated |
| First resumed SSH probe targeted `192.168.1.111`, which is the Jetson's robot-LAN source address and is not reachable from this Windows host | 1 | No remote command arrived; use the recorded Tailscale management address `100.126.48.49`, which passed Tailscale ping and SSH |
| First no-Nav2 smoke wrapper embedded PowerShell's backtick CR escape inside the JavaScript tool source and failed parsing locally | 1 | SSH was never invoked; replace the CR expression with a backtick-free regex replacement before retrying |
| The first no-Nav2 smoke assertion counted the shared server-unavailable phrase in ERROR/WARN/ABORT lines and searched uppercase `ABORT`, while the phase topic publishes lowercase `abort` | 1 | Inspect preserved evidence directly: four ERROR attempts, three numbered retry warnings, terminal `navigation_failed_after_4_attempts`, and `data: abort`; all safety/cleanup evidence passed |

## Concurrent Update - 2026-08-11 Phase 88 staged D455 depth modes and cone avoidance
The user chooses one Phase 1 map for the whole mission and requires the D455 depth function only in the obstacle zone and later grasp/placement zones because Xavier NX compute headroom is tight. Preserve D455 infrared/IMU and cuVSLAM continuously. First prove whether runtime `enable_depth` toggling leaves the validated infrared/IMU pipeline and cuVSLAM healthy; only then implement the cross-container depth control, relay, PointCloud2 costmaps, fail-closed safety gate, mission milestones, and staged hardware validation. Do not add Phase 2 map switching.

### Phase 88: Implement staged depth activation for obstacle and manipulation zones
- **Status:** in_progress (user approved local-only implementation; Jetson access and runtime changes remain prohibited while the remote system is busy)
- [ ] Freeze and fingerprint the current navigation/cuVSLAM/WHZ/deploy baseline; define separate depth-enabled configuration and rollback path.
- [ ] On an idle Jetson with no actuation, identify the installed RealSense node/version/parameters and A/B test `enable_depth` OFF/ON while measuring infra/IMU rates, cuVSLAM tracking, `/odom`, CPU/GPU/memory, USB traffic, and restart latency.
- [ ] Select hard depth-stream toggling only if cuVSLAM remains healthy; otherwise use the measured fallback that keeps the camera pipeline stable while deactivating relay, point-cloud, filtering, visualization, and dynamic-obstacle consumers.
- [x] Replace the incomplete raw-file relay with a versioned atomic shared-memory contract carrying sequence, source stamp, monotonic stamp, image metadata, depth scale, CameraInfo, optical frame, mode, heartbeat, and explicit OFF/FAULT acknowledgements. (local implementation and tests complete; Docker runtime pending)
- [x] Implement the Foxy Host depth bridge without reopening D455, then generate a decimated `PointCloud2` with correct optical TF, range/height filtering, diagnostics, and stale-frame rejection. (local implementation and projection tests complete; Foxy runtime pending)
- [x] Add a separate Nav2 dynamic-obstacle profile using local `VoxelLayer`, global `ObstacleLayer`, the existing DWB `ObstacleFootprint`, conservative update rates, and the single Phase 1 static map. (profile and launch contract complete; Nav2 loading pending)
- [x] Insert a single fail-closed safety gate after command arbitration; require fresh depth/TF only in depth-required modes and retain the existing downstream command watchdog in all modes. (local policy and launch wiring complete; ROS graph validation pending)
- [x] Implement an explicit depth state machine: `BOOTING/AVOIDANCE/DISABLED/MANIPULATION/FAULT`; require robot stop plus acknowledgement before every transition. (local state-machine tests complete)
- [x] Add data-driven mission milestones: depth ON before `obstacle_cross_target`, depth OFF only after that goal succeeds and the robot is stopped, depth ON again after `pos2b_lower_right` before `grab_area_approach`, and no Phase 2 map switch. (TaskManager and opt-in probe integration complete locally)
- [x] Add L0/L1 tests for mode transitions, acknowledgements, stale data, route milestones, command gating, optical-frame conversion, and rollback behavior. (187-test repository regression passed after resumed ROS 2 safety review)
- [ ] Complete L2/L3 build and robot-disconnected ROS graph tests, including synthetic cone clouds, costmap marking/clearing, plan bending, failed depth activation, and zero-command ownership.
- [ ] Complete L4 stationary Jetson resource/toggle tests and require fresh depth, stable cuVSLAM, stable `/odom`, no unintended command, and measurable resource reduction before motion.
- [ ] Complete L5 supervised single-cone and fault-injection tests at reduced speed, then L6 randomized double-cone and complete-route tests with evidence and rollback.

### Phase 88 Decision Gates
- Hard OFF/ON is accepted only if infrared/IMU topics recover deterministically, cuVSLAM has no reset/tracking-loss event, `/odom` returns to its accepted rate, and the robot remains stopped throughout the transition.
- Entering `AVOIDANCE` or `MANIPULATION` requires consecutive fresh depth frames, valid CameraInfo/TF, current point cloud/costmaps, and safety-gate readiness; failure stays stopped in `FAULT`.
- Entering `DISABLED` requires a confirmed zero command and explicit Docker-side OFF acknowledgement; the absence of depth frames by itself is not a successful transition.
- No L6 claim is allowed until randomized two-cone layouts pass with zero contact and the full mission demonstrates both depth transitions without cuVSLAM degradation.

### Phase 88 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Initial `findings.md` append accidentally preserved patch `+`/`-` prefixes | 1 | Inspect the written file immediately, replace the malformed block with plain Markdown, and verify no prefix lines remain |
| Final parallel local-check wrapper treated the expected missing-`bash` probe as a fatal sibling error and discarded otherwise independent outputs | 1 | No repository command mutated runtime state; rerun the full tests and parse checks separately, and make the Bash availability probe explicitly tolerant |

## Concurrent Update - 2026-08-11 Phase 87 clean Jetson synchronization to `c070b1f`
The user requests replacing the functionally equivalent but dirty Jetson state (`94137ea` plus three runtime overlays and an external launcher) with a reproducible clean Git deployment at `c070b1f`. Preserve a recoverable snapshot, fast-forward only, rebuild the ROS package, verify source/install/runtime identity, and do not execute the launcher or start navigation.

### Phase 87: Synchronize formal Jetson deploy checkout
- **Status:** complete (formal Jetson deploy is clean at `c070b1f`, package-limited build and source/install/module provenance passed, and no launcher/navigation process was started; the pre-existing vision-worktree bridge and YOLO container were intentionally left untouched)
- [x] Reconfirm the exact dirty set/hashes, target remote commit, existing process ownership, and external launcher identity.
- [x] Preserve the dirty overlay and launcher in a timestamped backup plus Git stash, fetch the target branch, and fast-forward the formal deploy checkout to `c070b1f`.
- [x] Run a package-limited symlink build and verify clean Git state, source/install/module provenance, launcher identity/mode, and final process ownership without launching navigation.

### Phase 87 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Initial PWF insertion assumed Phase 83 was still the first task section, but concurrent Phase 84-86 work had been added | 1 | Preserve all concurrent WHZ work and insert this deployment task as the new Phase 87 using the actual Phase 86 heading as the anchor |
| First remote transaction wrapper interpreted the Bash `${stamp}` expression as a JavaScript template variable | 1 | Escape the interpolation marker and rerun; the failure occurred before SSH, so Jetson state was unchanged |
| Combined final provenance command exceeded 120 seconds because `find -type f` skipped the installed params symlink and `cmp` then waited for stdin | 1 | Identify and terminate only the residual verifier PIDs, use the known installed symlink path, and rerun bounded checks successfully |
| First split Python module probes lost nested quotes across PowerShell/SSH | 1 | Move the probes into a PowerShell literal here-string and bound each import with `timeout 10`; both module paths and hashes then matched source |

## Current Update - 2026-08-11 Phase 86 standalone WHZ RTSP inspection service
Implement only the independent WHZ inspection service on the current Foxy Nav2 branch. Preserve `/whz/inspect`, replace the D455 ROS-image path with Lite3 front RTSP, add one-time YOLO model initialization and letter/gauge spatial pairing, retain deterministic multi-frame voting and one-shot audio, package the model, and remove the WHZ-only D455 color publisher from competition launch. Do not modify Nav2, cuVSLAM, the velocity chain, waypoints, or TaskManager. TaskManager integration remains blocked on supervised Jetson recognition and audio validation.

### Phase 86: Build and locally validate standalone WHZ inspection
- **Status:** complete (standalone RTSP/YOLO/voting/audio service passed local regression, isolated Jetson build, live recognition and one-shot audio, profiled stationary cuVSLAM + Nav2 coexistence, and exact cleanup; TaskManager remains intentionally deferred)
- [x] Audit current WHZ, remote detector source, launch/package surfaces, tests, model availability, and expected JSON/audio contract.
- [x] Implement RTSP camera, YOLO detector, normalized inspection result/voting, service parameters/resource cleanup, model packaging, and launch isolation.
- [x] Add fake camera/detector/player unit coverage for distinct-frame reads, pairing ambiguity, voting, JSON, and one-shot audio. (16 focused tests pass locally)
- [x] Run the strongest local L0/L1 checks available and document Jetson L2-L4 validation commands without claiming hardware success.
- [x] Leave TaskManager and all explicitly excluded navigation/cuVSLAM/relay surfaces unchanged.
- [x] When the Jetson is idle, run RTSP capture, GPU single-frame inference, three-frame vote, MP3 playback, and stationary cuVSLAM + Nav2 coexistence checks in order.

### Phase 86 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| ByteRover MCP/CLI is unavailable in this Windows session (carried from Phase 85) | 1 | Reuse the Phase 85 repository/PWF/Git assessment and do not repeat the unavailable lookup |
| Initial three-file PWF insertion used the wrong `findings.md` title anchor | 1 | Verify the real headings and reapply an incremental patch; no partial edit occurred |
| First parallel WHZ audit wrapper treated a successful `rg` output batch as exit 1 and suppressed sibling results | 1 | Split source reads from tolerant searches and confirm remote paths before retrying; no code edit occurred |
| Foxy import probe lost a quoted Python string through PowerShell/SSH | 1 | Use a quote-free numeric print sentinel; required Foxy imports then passed without starting ROS or camera |
| Static search passed a Windows-invalid `tests/test_whz*.py` path and returned exit 1 | 1 | Use directory + `-g` filtering and interpret the empty focused search as no stale references |
| Isolated full pytest collection could not import repository `nodes` | 1 | Prepend the repository `src` directory to `PYTHONPATH`; the complete non-hardware suite then passed |
| First installed-model probe used remote `$(ros2 pkg prefix ...)`, which local PowerShell evaluated | 1 | Use the explicit installation path from the successful build log; the hash and CPU warmup then passed |
| No-audio service probe exceeded the SSH timeout during cleanup | 1 | Logs proved the service had returned `no_valid_frame`; stop the exact wrapper/child PIDs and replace `ros2 run` wrapper cleanup with direct-process ownership for future probes |
| Cleanup verification inherited a PowerShell CRLF in the final `ps -o args` token | 1 | Run a separate direct `ps -p ... -o ...` check; both Phase 86 processes were absent |
| Local image-stat probe could not import OpenCV | 1 | Run the same read-only statistics on Jetson, where the validated runtime OpenCV is installed |
| First real-service wrapper enabled `set -u` before sourcing Foxy and exited on `AMENT_TRACE_SETUP_FILES` | 1 | Source Foxy/overlay first, then enable strict unset-variable checking; no node or camera process had started |
| First corrected live service call returned `no_valid_frame` although stored frames passed at 960/0.30 | 1 | Measure a fresh live confidence batch, retain 960, and lower only the shared letter/gauge cutoff to 0.25 because D was 0.263-0.304 while the competing B remained 0.071-0.086 |
| The one audio-enabled live service call still returned `no_valid_frame`, and a 30-frame probe then classified actual D as B throughout | 1 | Do not lower the global threshold; use the stable gauge detection to drive a second YOLO pass over a gauge-relative letter ROI, then map detections back through the existing pairing/ambiguity gates |
| Stationary ROS topology script reached all lifecycle checks but ended before topic details with Bash `unexpected end of file` | 1 | Treat the successful lifecycle output as valid, remove the CRLF-sensitive remote shell loop, and rerun topic queries explicitly; no runtime state changed |
| Foxy rejected `ros2 topic echo --once`, then a CRLF-tainted `true` token made the read-only topology script exit nonzero after all required topic info was printed | 1 | Preserve the complete topology evidence and replace CLI echo probing with a bounded `rclpy` multi-topic subscriber that records counts and maxima; no runtime state changed |
| Baseline resource probe assumed unsupported `tegrastats --count` and PowerShell CRLF tainted the final `ps` format token; the parallel wrapper also discarded the sibling ROS sampler output | 1 | Use `timeout` around `tegrastats`, strip carriage returns before SSH, and run the bounded ROS sampler separately so each evidence stream is retained |
| Corrected sampler wrapper embedded PowerShell's backtick-`r` inside a JavaScript template literal and failed local parsing before SSH | 1 | Replace the PowerShell escape with `.Replace([char]13, '')`; the failed wrapper never reached the Jetson |
| PowerShell selected the `String.Replace(char,char)` overload, so an empty replacement could not convert to `char` and SSH was again not reached | 2 | Switch to PowerShell regex replacement `-replace '\r',''`, avoiding both JavaScript backticks and the char overload |
| The corrected baseline sampler printed complete valid JSON but Bash did not recognize the final heredoc terminator and Python then evaluated `PY` as a name | 3 | Accept the measurement emitted before the wrapper-only `NameError` (the node shutdown already ran) and stop using nested heredocs; stream future Python directly to `python3 -` |
| WHZ start script successfully launched PID 13283 but the final `ps ... args` field again received a trailing CR from PowerShell native piping | 1 | Keep the exact started PID/evidence directory, verify it with direct SSH, and avoid piped Bash scripts for subsequent queries/cleanup |
| Combined coexistence sampler/resource/service wrapper exceeded its 35-second child-command limit and discarded all three parallel outputs | 1 | Do not repeat the service call; inspect server/client/process state and logs read-only, then recover retained evidence with independent commands and explicit per-command bounds |
| A second parallel diagnostic paired a successful thread query with an expected nonzero `timeout tegrastats`, so the wrapper again retained only the failing command's output | 1 | Stop parallelizing commands that intentionally terminate nonzero; rerun the thread query independently and keep subsequent evidence calls separate |
| Final exact-PID verification correctly found no processes, but `ps -p` returned status 1 and caused the parallel wrapper to discard container/pattern output | 1 | Treat the empty exact-PID table as successful absence evidence and rerun only the two always-zero checks independently; both were empty |
| Coexistence readiness initially trusted `ros2 service list`, which could reflect the stopped WHZ in the Foxy daemon cache; the new process was still busy | 1 | Gate on the new PID's own `WHZ inspection ready` log and direct process/thread evidence, not daemon-only graph presence |
| Separately launched WHZ omitted the production `FASTRTPS_DEFAULT_PROFILES_FILE`/RMW environment and spun two DDS threads at about 57% CPU each | 1 | Restart the exact WHZ PID with the same `rmw_fastrtps_cpp`, domain 0, and no-SHM profile inherited by the formal competition launch; apply the same environment to diagnostic clients |
| Profiled-WHZ readiness grep lost quotes around the multi-word pattern across Windows SSH and treated `inspection`/`ready` as filenames | 1 | The loop still waited until the only `WHZ` ready line appeared; verify with direct log and CPU/thread reads, and avoid multi-word remote grep patterns |
| Final full regression exposed an existing Lite3 UDP test fixture without the production parser's `test_closed_yaw` field | 1 | Add only the missing `False` default to the test `SimpleNamespace`; do not change UDP motion behavior or runtime parameters, then rerun the complete suite |

## Concurrent Update - 2026-08-11 Phase 85 selective WHZ vision/audio integration assessment
The user confirms the SLAM + Nav2 path is already sufficiently validated and now wants to integrate gauge recognition plus voice announcements from `feature/vision-yolo-refactor` into the current Nav2 branch. Preserve the navigation baseline, assess a selective port rather than a branch merge, and make no business-code changes until the integration boundary is agreed.

### Phase 85: Define a safe selective port for gauge recognition and audio
- **Status:** complete (selective integration is feasible on the Jetson Host, but the remote branch must not be merged wholesale; no business-code merge or runtime-state change was performed)
- [x] Attempt the required L1-3 history query and fall back to repository PWF because ByteRover is unavailable in this host.
- [x] Inventory the current branch's perception, WHZ, audio, packaging, launch, TaskManager, and test surfaces.
- [x] Compare those surfaces with the remote refactor and classify files as reuse, repair-and-port, or reject.
- [x] Produce the target runtime architecture, implementation order, validation gates, and merge recommendation without editing business code.

### Phase 85 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| ByteRover MCP is not exposed and `brv` is not available in PATH | 1 | Use the existing PWF history and direct Git/source evidence; do not repeat the unavailable query |
| Jetson was not in the expected stopped state: an existing YOLO reproduction container and `cmd_vel_bridge` processes were active | 1 | Do not stop or alter user-owned runtime state; use the completed read-only compatibility probe only and stop further remote testing |

## Concurrent Update - 2026-08-11 Phase 84 `feature/vision-yolo-refactor/src/whz` read-only review
The user asked to inspect the remote `src/whz` implementation and then requested a deeper review. Review the remote Git objects without switching the dirty local worktree, focus on runtime correctness and integration with the current Nav2 branch, and make no ROS/Jetson or business-code changes.

### Phase 84: Review remote WHZ YOLO inspection integration
- **Status:** complete (read-only review found multiple deterministic runtime blockers; no remote branch checkout, business-code edit, ROS/Jetson startup, or robot command)
- [x] Confirm the remote branch tip, directory contents, history, and divergence from the current branch.
- [x] Trace the WHZ detector, ROS entrypoints, packaging, TaskManager state flow, model/resource delivery, and documentation contract.
- [x] Perform bounded static checks and report findings ordered by severity with exact remote file references.

### Phase 84 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Anonymous GitHub REST requests returned 404 for the repository objects | 1 | Use the already-fetched authenticated Git remote-tracking objects; do not switch branches or modify the working tree |

## Current Update - 2026-08-11 Phase 83 doubled-speed overlay and check-free one-click run
The user requires the already validated local `0.24m/s` linear and `0.30rad/s` angular limits to be active in the next one-click launch, and then explicitly requires deleting all launcher preflight/runtime gates so startup contains only the stack and route execution. Deploy the three runtime speed files, rebuild the package, upload the simplified launcher, and do not start the stack or route during deployment.

### Phase 83: Deploy doubled-speed runtime overlay and simplified launcher
- **Status:** complete (the three speed files and 148-line check-free launcher are deployed; source/build/install identity, executable hash, and stopped final state were verified without running the launcher)
- [x] Remove all repository, hardware, install, lifecycle, action, TF, parameter, topic, and route-description gates from the launcher while retaining full-stack startup, foreground 14-goal execution, cleanup, and evidence archiving.
- [x] Back up and deploy the three `0.24/0.30` runtime files to the Jetson, then run a package-limited build and static provenance checks.
- [x] Upload the simplified launcher, verify exact hash and mode `0755`, and leave Jetson stopped without executing the launcher.

### Phase 83 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Final combined verification invoked `bash` by name, but the current PowerShell `PATH` does not expose Git Bash | 1 | Locate Git for Windows and rerun syntax validation with explicit `C:\Program Files\Git\bin\bash.exe`; no launcher or robot process was started |
| Required L1-3 lookup could not run because neither ByteRover MCP nor the `brv` CLI is available in this Windows session | 1 | Continue with repository PWF, local Git objects, GitHub `ls-remote`, and read-only Jetson provenance evidence |
| One concurrent SSH query for launcher hash/stat timed out while other read-only Jetson queries succeeded | 1 | Retry hash, size, mode, and mtime as separate bounded SSH queries; all returned successfully |
| Remote `find -printf` evidence listing lost quoting across PowerShell/SSH | 1 | Replace it with `ls --full-time` plus direct `sed` reads of the recorded evidence files |
| A temporary-file pipeline intended to hash Git blob contents was blocked by the host command policy | 1 | Use the clean local working-tree files and direct `Get-FileHash`; their Git blob identity/status had already established they equal `c070b1f` |

## Current Update - 2026-08-11 Phase 82 one-click cmd_vel_nav2 topology gate fix
The first launcher run stopped before goal submission because its `/cmd_vel_nav2` gate incorrectly required one publisher. The Foxy topology fix was implemented and covered, but the user's later requirement to remove every startup gate superseded it; the final launcher contains no topic-count gate.

### Phase 82: Correct the Nav2 input-topic topology gate
- **Status:** complete (the valid `controller_server + recoveries_server` Foxy topology was diagnosed and the identity-based fix passed regression coverage; the entire gate was subsequently removed under Phase 83)
- [x] Replace the exact `/cmd_vel_nav2` publisher-count assertion with endpoint-identity validation for controller/recoveries publishers and the sole arbiter subscriber.
- [x] Add regression coverage and pass local Bash/Python checks.
- [x] Supersede the corrected gate with the user's later check-free launcher requirement and deploy without executing it.

### Phase 82 Errors
| Error | Attempt | Resolution |
|---|---:|---|

## Concurrent Update - 2026-08-11 Phase 81 navigation speed limits doubled
The user requests doubling the current main Nav2 linear and angular velocity limits. Update the complete production command-limit chain from `0.12m/s` to `0.24m/s` and from `0.15rad/s` to `0.30rad/s`, keep precision-control and acceleration/deceleration settings unchanged, add angular-limit contract coverage, and perform local L0/L1 validation only without connecting to Jetson or sending motion commands.

### Phase 81: Double main Nav2 linear/angular velocity limits
- **Status:** complete (main Nav2 command chain is synchronized at `v=0.24m/s` and `omega=0.30rad/s`; local L0/L1 checks passed; no Jetson connection, ROS/Nav2 startup, or motion command)
- [x] Synchronize DWB, recovery, arbiter, and bridge linear/angular speed ceilings.
- [x] Extend the speed-limit contract test to cover both axes and run focused static/unit validation.

### Phase 81 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Combined unittest command could not import `nodes.navigation.cmd_vel_arbitration` because the local Windows interpreter did not include repository `src` on `PYTHONPATH` | 1 | Re-run the focused suite with the repository `src` directory explicitly prepended to `PYTHONPATH` |
| Final line-number-only `rg` command had an unclosed regex after crossing PowerShell/JavaScript quoting | 1 | Re-run as fixed-string searches; this command did not validate or modify behavior |

## Current Update - 2026-08-11 Phase 80 Jetson full navigation one-click launcher
The user requests a single Jetson-side shell entrypoint derived from the validated manual startup procedure. Build a fail-fast launcher around the repository's real scripts and route probe, preserve physical-safety gates and shutdown behavior, add focused validation, and do not connect to Jetson or send motion commands in this phase.

### Phase 80: Jetson one-click full-navigation launcher
- **Status:** complete (launcher implemented, locally syntax/contract validated, and uploaded executable to Jetson; the launcher itself was not run, including check-only mode)
- [x] Extract the exact validated startup, readiness, route, evidence, and shutdown contract from the manual and repository scripts.
- [x] Implement a deployable Jetson shell entrypoint with automatic execution, signal trapping, provenance/runtime gates, cleanup, and evidence capture; no interactive confirmation phrase.
- [x] Add focused contract tests, pass local Bash/Python/text validation, upload to Jetson home, and verify file mode/hash without executing the launcher.

### Phase 80 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Local `--describe-route` execution imports `rclpy`, which is unavailable in the Windows Python environment | 1 | Use structured JSON parsing for local route validation; reserve the real route-description command for Jetson ROS validation without sending goals |
| Initial search assumed `describe_waypoint_route` was defined in the probe file | 1 | Located the imported implementation in `src/nodes/navigation/waypoint_calibration.py` and used its exact `steps` schema |
| `git diff --no-index --check` returned status 1 for each new file because any no-index content difference uses status 1, even with no whitespace diagnostics | 1 | Treat the empty diagnostic output correctly and use explicit PowerShell trailing-whitespace checks plus remote `bash -n` |
| Local `tailscale ssh` could not access the protected Tailscale daemon pipe from the managed session | 1 | Use the already-routable Tailscale IP with standard OpenSSH under the required network permission |

## Current Update - 2026-08-11 Phase 79 immediate full14 rerun
The user confirms the robot has been manually returned to the official start and requests the fastest complete rerun. Reuse clean deploy `94137ea`, skip repeated static/hardware tests, retain only startup zero, one action server, and start TF before sending `full_interleaved --stop-on-failure`; always stop the stack and preserve evidence without rolling back the deployment.

### Phase 79: Immediate supervised full14 rerun
- **Status:** in_progress
- [ ] Cold-start the validated production stack and pass the minimal action/start-TF gate.
- [ ] Execute the 14-point route with stop-on-failure.
- [ ] Stop all motion/ROS/cuVSLAM processes and preserve the exact L6 result.

### Phase 79 Errors
| Error | Attempt | Resolution |
|---|---:|---|

## Current Update - 2026-08-11 Phase 78 fastest supervised full14 run
The user states the robot is at the official start and requests an immediate full navigation-stack run with no repeated static checks. Use the persistent clean `94137ea` deploy, keep only the minimum non-negotiable motion gates (startup, start TF, single command chain, continuous zero before action), execute `full_interleaved --stop-on-failure`, then stop the stack and preserve evidence without rolling back the 14-point deployment.

### Phase 78: Fast supervised full14 L6 run
- **Status:** complete (one supervised L6 attempt completed; points 1-9 succeeded, point 10 `grab_area_approach` aborted on DWB `No valid trajectories out of 335`, points 11-14 were not sent; stack stopped and `94137ea` retained)
- [x] Start the validated deploy stack from the official start with the existing production parameters.
- [x] Pass only the minimum motion gates and send the 14-point route with stop-on-failure.
- [x] Stop Nav2/bridge/cuVSLAM after success or first failure and verify the command-chain stop evidence.
- [x] Preserve the run artifacts and report the exact L6 result without reverting `94137ea`.

### Phase 78 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| First minimum gate required an RPY line that `timeout 5 tf2_echo` cut off after already emitting a valid translation and quaternion | 1 | Exit trap stopped the untouched stack before any goal was sent; confirmed the valid `(4.689,0.746,~pi)` pose, then restarted and computed yaw from the quaternion |

## Current Update - 2026-08-11 Phase 76 persistent full14 deployment
The user confirmed that the 14-waypoint route and the two `xy_goal_tolerance=0.30` settings are the intended Jetson deploy baseline. Replace the previous temporary-overlay-and-restore procedure with a traceable Git deployment, retain the old 11-point commit only as an explicit rollback target, update the manual accordingly, and perform no ROS/Nav2 startup or motion command.

### Phase 76: Persist 14-waypoint / 0.30m configuration on Jetson deploy
- **Status:** complete (Jetson deploy is clean at `94137ea`; 14-point/0.30m source and install provenance passed; no ROS/Nav2 process or motion command was started)
- [x] Verify the exact source commit contains the six deployment files and the expected 14-point/0.30m contract.
- [x] Back up the Jetson repository state, fetch, and fast-forward the deploy checkout to the approved source commit.
- [x] Build only `quadruped_robot_competition` and verify source/install/runtime provenance without activating Nav2.
- [x] Update the manual so normal shutdown preserves the current deployment; rollback is explicit only.
- [x] Run static checks, ROS skill validators, and record L2 evidence and limitations.

### Phase 76 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Initial parallel audit wrapper used PowerShell here-string syntax directly inside JavaScript | 1 | Reissued the read-only audit using JavaScript strings; no repository or robot state changed |
| Jetson SSH connection timed out before the Git deployment command started | 1 | Tailscale status and three bounded pings confirmed `100.126.48.49` was offline; no remote state changed, so local documentation and validation continued while awaiting connectivity |
| Local default Python 3.14 and the bundled runtime did not include pytest | 1 | Used `uv run --isolated --no-project --with pytest`; no system Python packages were installed |
| First expanded pytest command collected hardware scripts outside `tests/` | 1 | Restricted collection to `tests/` and excluded only the known `test_lite3_udp_smoke.py` fixture; 106 tests passed |
| Remote regex lost backslashes while crossing the JavaScript command-string layer | 2 | Replaced the deployment assertion with exact stripped-line comparisons; the Git blob itself was unchanged and correct |
| First colcon wrapper used `set -u`, which Foxy `setup.bash` does not support | 1 | Reused the same evidence directory and reran with `set -eo pipefail`; build then completed with one package |
| Final route-description check assumed a nonexistent `waypoint_count` key | 1 | Inspected the emitted schema and asserted `len(steps)==14` plus point-8 label; no navigation action was created |

### Concurrent Update - 2026-08-11 Phase 77 14-waypoint map visualization
The user requested a map image showing all 14 route steps. Render the existing `full_interleaved` preview route over the ROS PGM map, preserve repeated route steps at shared coordinates with distinct sequence labels, and do not change navigation configuration or start ROS/Nav2.

### Phase 77: Render the 14-goal route on the competition map
- **Status:** complete
- [x] Read the PGM metadata and the exact `full_interleaved` route coordinates.
- [x] Generate a high-resolution numbered PNG with route direction, yaw indicators, coordinate grid, and legend.
- [x] Visually inspect the output and verify all 14 sequence entries and repeated-coordinate annotations.

### Phase 77 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| PyYAML is not installed in the active Windows Python environment | 1 | Use JSON for the JSON-compatible waypoint file and a strict standard-library parser for the three required map metadata fields; no dependency installation needed |

## Goal
为四足机器人比赛仓库建立 L1-2 短期记忆三件套，使后续开发、联调、测试和沉淀知识可以跨 session 衔接。

### Current Update — 2026-08-11 Phase 73 第一阶段锥桶障碍区方案调研
用户将此前 14 航点实跑定位为 SLAM + Nav2 可行性验证，现要求基于完整代码库、现有硬件和比赛规则，研究第一阶段锥桶障碍区应如何实现；允许联网检索。本阶段先做只读架构与证据调研，不修改导航实现、不连接 Jetson、不启动 ROS/Nav2 或发送运动命令。

### Phase 73: 第一阶段锥桶障碍区感知与导航方案
- **Status:** complete（规则、代码、硬件和官方资料调研完成；未修改导航实现、未连接 Jetson、未执行真机动作）
- [x] 从比赛规则 PDF 提取障碍区布局、锥桶约束和判定条件。
- [x] 审计当前 D455/cuVSLAM、深度中继、Nav2 costmap、DWB、路线与命令链的实际能力和缺口。
- [x] 查阅与当前 Foxy/Jetson 条件匹配的官方 Nav2、RealSense 与 Isaac ROS 资料。
- [x] 形成推荐架构、实施阶段、验收门禁、主要风险和备选方案，不执行代码或真机修改。

### Concurrent Update — 2026-08-11 Phase 74 Jetson DWB 部署仓库审计
用户指出手册可能误用了旧 `nav2-dwb` 目录，要求核对 Jetson 多个仓库。只读审计确认正式部署目录应为 `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy`；旧 `/home/superwfx666/quadruped-robot-competition-nav2-dwb` 是保留的历史脏 worktree。Phase 71 的进程证据表明当次实际误从旧 worktree 启动，因此已纠正手册全部运行/同步路径并增加仓库根、ROS prefix 和进程参数三层防串仓门禁。本辅助审计不改变仍在进行的 Phase 73 障碍区调研状态。

### Phase 74: Jetson DWB 部署仓库审计与手册纠正
- **Status:** complete
- [x] 只读枚举 Jetson 相关仓库，比较 Git HEAD、工作区状态、关键运行文件和安装态链接。
- [x] 用 Phase 71 `pre_goal_gate.txt` 与备份状态确认当次真实进程来源。
- [x] 将手册全部 Jetson 操作路径改为 `quadruped-robot-competition-nav2-dwb-deploy`，保留 Windows 本机源仓库路径不变。
- [x] 增加 deploy repo、ROS package prefix 和旧 worktree 进程路径门禁，并完成格式/契约/ROS validator 验证。

### Concurrent Update — 2026-08-11 Phase 75 正式 deploy 完整 14 点导航
用户要求直接运行完整导航栈。本轮只使用 `/home/superwfx666/quadruped-robot-competition-nav2-dwb-deploy`。现场确认和全部动作门禁通过后发送 14 点路线；第 1 点因 15 秒无位移触发 `Failed to make progress` 并 `ABORTED`，第 2–14 点未发送。Nav2 和 bridge 均记录 599 个非零命令，但 TF 位移仅 `0.000023m`，故障边界位于 ROS/UDP 发送之后的 Lite3 执行状态或机体侧。已停栈、归档并恢复 deploy clean 基线，不做自动重试。

### Phase 75: 正式 deploy 完整 14 点监督实跑
- **Status:** complete（完成一次正式 deploy 监督实跑；第 1 点无机体位移后 progress checker abort，第 2–14 点未发送；已停栈、归档并恢复 clean 基线）
- [x] 只读确认 deploy clean、Jetson 空栈、D455 在线、Lite3 3/3 ping 和磁盘空间正常。
- [x] 备份 deploy 六个运行文件到 `competition_deploy_backups/codex_manual_full14_20260811_124934`。
- [x] 同步本机 Phase 70 六文件并限定构建；安装态 prefix 为 deploy，14 点、第 8/13 点、两处 `0.30m` 和 Planner `0.20m` 门禁通过。
- [x] 获取本轮实时现场安全确认后，冷启动完整栈并执行动作前门禁；deploy-only 进程、5 个 lifecycle、起点 TF、参数、action 和单一速度链全部通过。
- [x] 前台运行 `full_interleaved --stop-on-failure`；第 1 点明确 `ABORTED`，后续 13 点未发送，未重试。
- [x] 停栈、停止 cuVSLAM、归档证据、恢复 deploy 原始 clean 11 点/`0.15m` 基线并复核末态。

### Current Update — 2026-08-11 Phase 72 手动完整导航流程文档
用户要求在 `C:\Users\111\Desktop\比赛\quadruped-robot-competition\学习\可以成功运行全部航点的启动脚本.md` 写入一份可人工执行的完整流程。文档必须以仓库和 Jetson 的实际脚本接口为准，覆盖安全前置条件、14 点/`0.30m` 运行态门禁、完整栈启动、路线执行、结果判断、失败停栈和证据保存，并明确 Phase 71 只通过前 12 点、第 13 点仍有 Planner 风险，不能把标题写成已保证全通。

### Phase 72: 手动完整导航流程文档
- **Status:** complete
- [x] 读取目标文档现状，并核对启动、停止、路线 probe、Lite3 prepare 与运行态门禁的真实 CLI。
- [x] 编写可逐段复制执行的 Markdown 手册，包含物理监护、失败立即停止和第 13 点已知风险。
- [x] 静态验证文档内路径、参数、路线/容差断言、Markdown 格式与 ROS validator；本机无 Bash，未执行 `bash -n`，文档内 Bash 已人工逐段复核。
- [x] 更新 PWF 三件套并交付绝对路径。

### Current Update — 2026-08-10 Phase 71 `0.30m` + `lower_corner_clear` 完整 14 点 L6 实跑
用户确认机器狗已回官方起点，明确要求启动完整导航栈并运行完整路线。本轮部署 Phase 70 的两处 `xy_goal_tolerance=0.30m` 与独立 `lower_corner_clear` 14 点路线，复用 `robot + custom + 640x360x30 + backend true`、`base_start` planar bridge、显式 Lite3 motion prepare、1Hz 无运动恢复 BT、0.35m 终点无重规划 handover 和 `--stop-on-failure`。实跑前 12 点成功，第 13 点 `placement_C_approach` 因 GridBased 无法生成有效路径而 `ABORTED`，第 14 点未发送；新增第 8 点 `lower_corner_clear` 与第 9 点 `pos2b_lower_right` 均成功。证据已归档，Jetson 已恢复部署前状态并停栈。

### Phase 71: 完整 14 点监督实场导航
- **Status:** complete（完成一次监督 L6 全路线尝试；12/14 点成功，第 13 点 Planner abort，第 14 点按 `--stop-on-failure` 未发送；证据归档和远端恢复完成）
- [x] 只读确认 Jetson 空栈、D455/Lite3 在线、远端部署基线可恢复，并临时同步 Phase 70 六个运行文件。
- [x] 限定构建并核验安装态 14 点路线、两处 `0.30m` 容差和独立 `lower_corner_clear`。
- [x] 冷启动完整定位/Nav2/bridge/Lite3 链，确认 lifecycle active、单一命令链、TF 新鲜和动作前持续零速。
- [x] 运行 `full_interleaved --stop-on-failure`，保存结果后停栈、停止 cuVSLAM、恢复远端部署并核验末态。

### Phase 71 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Jetson 未安装 `jq`，首次 `summary.json` 解析退出 | 1 | 改用 `python3 -m json.tool` 和 Python `json` 结构化解析 |
| 恢复构建首次 SSH 包装超时过短，未产生构建输出 | 1 | 先确认无残留构建进程和源码哈希正确，再以 120 秒超时重跑限定构建并成功 |
| `colcon --symlink-install` 未自动清理已从 `setup.py` 删除的终点 XML 链接 | 1 | 精确删除 `build/`、`install/` 中两个悬空链接，并复核 source/build/install 均不存在该 XML |
| 最终证据脚本的 CRLF/正则提取导致只读检查提前退出 | 2 | 统一脚本 LF，改用固定字符串提取零速窗口后完成末态核验 |

### Current Update — 2026-08-10 Phase 70 `0.30m` 终点容差与下侧独立过渡航点
用户要求在当前回退分支上完成两项软件修改：将两处 `xy_goal_tolerance` 从 `0.20m` 提高到 `0.30m`；恢复独立的 `lower_corner_clear=(2.60,3.25,pi)`，同步 preview/真实标定/默认路线/导航说明，并扩展上下六段静态净空回归。本阶段仅做本机 L0/L1 验证，不连接 Jetson、不启动 ROS/Nav2、不发送运动命令。

### Phase 70: `0.30m` 容差与 14 点路线恢复
- **Status:** complete（两处容差已同步为 `0.30m`；9 点巡检/14 点完整路线、独立标定项和六段净空回归已完成；L0/L1 全部验证通过）
- [x] 将 goal checker 与 DWB 的两处 `xy_goal_tolerance` 从 `0.20` 同步提高到 `0.30`，并增加契约断言。
- [x] 新增独立 `lower_corner_clear`，同步 inspection/full 路线、真实标定顺序和导航说明。
- [x] 扩展上下六段 51x24 静态扫掠及下侧两段 101x48 高密度预检，运行聚焦与扩展回归、解析/编译/路线/格式/ROS validator 检查。

### Current Update — 2026-08-10 Phase 69 历史成功与近期失败根因对照
用户要求解释 Phase 61/62 曾连续通过前 7 点、但 Phase 65–68 最近多次在第 3 点附近失败的原因。本阶段只读比较历史/近期 L6 产物、Nav2 原始日志、运行态配置与控制/定位轨迹；不修改参数、不部署文件、不启动 ROS/Nav2 或发送运动命令。不确定的 Nav2 Foxy 行为以安装源码或官方上游资料核对。

### Phase 69: `pos1_middle` 成功/失败差异定因
- **Status:** complete（直接触发、DWB 阈值机制和末态足迹碰撞已定因；运行间物理运动与 cuVSLAM 观测的各自贡献仍需额外传感器证据区分）
- [x] 从最近一次 `/tmp/competition.log` 与 route 产物提取首个控制失败文本和精确时序。
- [x] 结构化比较 Phase 61/62 成功运行与 Phase 65–68 失败运行的第 3 段：handover 触发、TF 轨迹、cmd_vel、耗时与终点漂移。
- [x] 核对实际代码/参数/安装态/启动配置是否存在能解释差异的版本或 overlay 变化。
- [x] 对未能由本地证据确定的 Foxy Nav2 机制查阅安装源码或官方资料，给出根因置信度与下一次最小验证方案。

### Current Update — 2026-08-10 Phase 68 回退版 13 航点完整导航复跑
用户已将本机分支回退到 `4c65807fe67d2b30ec9fa4640737e37034eff71c`，并确认机器狗回到官方起点。按 Phase 61/62 的一致配置重新运行 `full_interleaved` 13 航点：`robot + custom + 640x360x30 + backend true`、`base_start` planar bridge、显式 Lite3 motion prepare、1 Hz 无运动恢复 BT、0.35m 终点无重规划 handover、`--stop-on-failure`。本轮不带 `lower_corner_clear`，任何航点失败立即停止后续 goal，并执行停栈、部署恢复和末态核验。

### Phase 68: Phase 61/62 配置 13 航点 L6 复跑
- **Status:** complete（重启后重新冷启动；第 1–2 点成功，第 3 点 `pos1_middle` handover 后 `ABORTED`，第 4–13 点未发送；已停栈并恢复远端 clean）
- [x] 只读确认 Jetson 空栈、D455/Lite3 在线与远端部署基线，备份并临时同步五个目标文件。
- [x] 冷启动完整定位、Nav2、`cmd_vel_bridge` 与 Lite3 motion prepare，验证启动完成、Nav2 active、单一命令链和动作前零速。
- [x] 运行 `waypoints_reordered_preview.yaml/full_interleaved` 13 航点，保持 `--allow-preview-route --goal-timeout 130 --stop-on-failure`。
- [x] 明确失败后停栈、停止 cuVSLAM、恢复远端部署并记录 L6 结果。

### Phase 68 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 首次完整栈启动完成、尚未发送 goal 时，用户对 Jetson/机器狗掉电重启，`/tmp` 运行备份随重启消失 | 1 | 新 boot 空栈且五个部署文件哈希完整；从 deploy 的不可变 `HEAD=52d30d6` 逐文件重建原始基线备份后重新冷启动 |

### Current Update — 2026-08-10 Phase 67 官方起点第三次完整 14 航点实跑
用户确认机器狗再次回到官方起点，要求立即再次运行全部航点。复用 Phase 66 的已验证部署组合，不进行软件测试或新诊断；保留最小启动门禁、`--stop-on-failure`、安全停栈和远端恢复。

### Phase 67: 官方起点第三次 14 航点 L6 重跑
- **Status:** complete（第一次启动在早期图检查提示后未运动即清理；第二次冷启动成功，第 1–2 点成功，第 3 点 `pos1_middle` ABORTED，第 4–14 点未发送；已恢复远端部署）
- [x] 临时部署已验证导航组合并冷启动完整执行链。
- [x] 启动完成后运行 `full_interleaved` 14 个航点。
- [x] 成功或明确失败后停栈、恢复远端部署并记录结果。

### Current Update — 2026-08-10 Phase 66 官方起点重新冷启动 14 航点实跑
用户确认机器狗已重新人工放置于官方地图起点，要求重启完整导航栈并再次执行完整路线。本轮复用已验证的 `0.20m` goal tolerance、终点无重规划切换、`ObstacleFootprint` 和 `lower_corner_clear`；不做本机测试或新诊断，仅做必需部署、启动门禁、完整路线、停栈和恢复。

### Phase 66: 官方起点 14 航点 L6 重跑
- **Status:** complete（完整路线重新尝试；第 1–2 点成功，第 3 点 `pos1_middle` 明确 ABORTED，第 4–14 点未发送；已停栈并恢复远端部署）
- [x] 临时部署已验证的完整导航组合，冷启动定位、Nav2、bridge 与 Lite3 执行链。
- [x] 启动完成后运行 14 点 `full_interleaved --stop-on-failure`。
- [x] 成功或明确失败后停栈、恢复远端部署并同步结果。

### Current Update — 2026-08-10 Phase 65 `lower_corner_clear` 完整 14 航点实跑
用户确认机器狗已人工放回官方起点，要求不重复软件测试或扩展诊断，以最快速度部署 Phase 64 路线并运行 `full_interleaved` 全部 14 个航点。本轮只做空栈、最小文件部署、启动完成、Nav2 active 与末端零速门禁；路线保留 `--stop-on-failure`，结束后停栈并恢复临时部署。

### Phase 65: 14 航点 L6 快速验收
- **Status:** complete（按用户要求完成一次快速完整路线尝试；第 1–2 点成功，第 3 点 `pos1_middle` 超时，第 4–14 点未发送；已停栈并恢复远端部署）
- [x] 临时部署 `lower_corner_clear` 相关最小文件并快速启动完整导航执行链。
- [x] 启动完成后立即运行 14 点 `full_interleaved --stop-on-failure`。
- [x] 成功或明确失败后停栈、恢复部署并同步运行结果。

### Current Update — 2026-08-10 Phase 64 下侧墙角过渡航点修复
Phase 63 已确认第 8 段从失败位姿重发时，DWB 的 `ObstacleFootprint` 在首个控制周期拒绝全部候选。用户要求新增独立的 `lower_corner_clear` 过渡航点，将原来的 `pos1_middle_turned -> pos2b_lower_right` 对角线拆为两段轴向走廊；本阶段只做本机路线、静态足迹与契约验证，不启动 Jetson 或发送运动命令。

### Phase 64: `lower_corner_clear` 路线修复
- **Status:** complete（preview/真实模板/默认常量均已新增独立下侧过渡点；9 点巡检与 14 点完整路线契约、上下侧全向静态足迹扫掠和扩展回归均通过）
- [x] 在 preview、真实模板与默认路线常量中新增 `lower_corner_clear=(2.60,3.25,pi)`。
- [x] 将 inspection/full 路线改为 `pos1_middle_turned -> lower_corner_clear -> pos2b_lower_right`，同步导航说明。
- [x] 增加下侧两段全向静态足迹扫掠与路线契约测试，完成 L0/L1 验证和 PWF 同步。

### Current Update — 2026-08-10 Phase 63 第 8 段 DWB critic 定因复现
用户已将机器狗人工放置在 Phase 62 第 8 段 ABORTED 位姿 `(1.822, 2.932, -0.605)`，要求快速冷启动后只重发 `pos2b_lower_right`，开启 DWB 逐轨迹评分并采集 Planner、Controller、BT、costmap 与 footprint 证据。冷启动的 `map -> odom` 必须临时与该放置位姿对齐，运行结束后恢复部署并停栈。

### Phase 63: 第 8 段 DWB critic 逐项定因
- **Status:** complete（冷启动从 Phase 62 终止位姿只重发第 8 段；DWB 在首个控制周期因 `ObstacleFootprint` 拒绝全部候选，未产生运动）
- [x] 临时对齐冷启动 map 位姿，启用 `debug_trajectory_details`，保存可恢复备份。
- [x] 快速启动，只发送 `(2.60, 2.00, pi)`，保留 1Hz 重规划 BT。
- [x] 保存 DWB critic 评分、Nav2 stdout、plan、costmap 与 footprint，停栈并恢复部署。

### Current Update — 2026-08-10 Phase 62 全路线复跑与 DWB 证据采集
用户将机器狗重新置于官方起点，要求快速完整运行 13 航点，并同时监控 Planner、Controller、BT stdout 与 `/plan`，以确定 Phase 61 第 8 段问题。只进行必要临时部署、等待“启动完成”、路线执行、证据保存和清理。

### Phase 62: 第 8 段 DWB 失败 L6 复现与观测
- **Status:** complete（完整路线尝试；第 1–7 点成功，第 8 点 `pos2b_lower_right` 再次 DWB ABORTED，第 9–13 点未发送）
- [x] 快速启动后运行同一 `full_interleaved --stop-on-failure`，不重复软件测试或运行态预检。
- [x] 保存完整 Nav2 stdout 和 `/plan`，同时保留 probe 的 summary/trace/cmd_vel 产物。
- [x] 确认 Planner 持续提供路径，失败直接来自 DWB `No valid trajectories out of 335`。
- [x] 安全停栈、恢复远端部署并删除临时备份；进程、Docker 与 deploy Git 状态均为空/干净。

### Current Update — 2026-08-10 Phase 61 终点切换完整 13 航点实跑
用户确认机器狗已在官方起点，要求不重复部署与诊断，以最快速度启动并运行 Phase 60 的完整 `full_interleaved`。本轮只等待脚本“启动完成”标志后发送 13 点路线，保留 `--stop-on-failure`；运行结束后停栈、恢复临时部署并清理。

### Phase 61: 终点无重规划切换 L6 验收
- **Status:** complete（完成完整路线尝试；第 1–7 点成功，第 8 点 `pos2b_lower_right` 在周期重规划阶段 ABORTED，第 9–13 点未发送）
- [x] 复用已部署的 Phase 60 五文件修复，快速启动完整定位、Nav2、bridge 与 Lite3 执行链。
- [x] 启动完成后立即运行 13 点 `full_interleaved --stop-on-failure`。
- [x] 验证第 1–7 点均完成“周期 goal 取消、零速确认、无重规划终点 goal”切换并成功。
- [x] 第 8 点明确失败后停栈，恢复远端 4 个原文件并删除新增 XML，确认进程、Docker 与 deploy Git 状态为空/干净。

### Phase 61 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 本机工具隔离不提供 `btoa`/`TextEncoder`，两次启动命令编码在本机解析阶段失败 | 2 | 远端命令均未发出；改用 ASCII Base64 编码函数后启动成功 |
| 首次启动标志轮询中的 `$(...)` 被 PowerShell 本地展开 | 1 | 未影响远端启动；改用 Base64 传递完整 Bash 脚本后只等待“启动完成” |
| 前两次 probe 分别缺少本地 `src` 路径、随后又以 `PYTHONPATH=src` 覆盖 ROS Python 路径 | 2 | 两次均在发送 goal 前退出、机器狗未移动；最终使用 `PYTHONPATH=src:$PYTHONPATH` 正式运行 |

### Current Update — 2026-08-10 Phase 60 终点阶段停止周期重规划
Phase 59 证实 Foxy 0.4.7 的 1Hz 路径更新会同时重置 `SimpleGoalChecker` 与 DWB critics；`pos1_middle` 短暂进入 `0.20m` 后因终点状态被重置再次进入极限环。按用户确认实施两阶段 NavigateToPose：远端保留周期重规划，进入终点邻域后取消并确认零速，再以无重规划、无运动恢复 BT 发送同一目标。

### Phase 60: 终点稳定调向 BT 切换
- **Status:** complete（L0/L1 软件实现和契约验证完成；尚未部署 Jetson 或真机复跑）
- [x] 新增只规划一次且无 Spin/BackUp 的终点 Behavior Tree，并纳入安装数据。
- [x] 在航点 probe 中实现终点邻域取消、零速确认和同目标无重规划重发。
- [x] 增加参数/结果证据与 L0/L1 契约测试，完成静态检查和 PWF 同步。

### Phase 60 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| PowerShell 路线距离表再次把 `foreach` 结果直接接入管道，触发 `An empty pipe element is not allowed` | 1 | 未修改文件；改为先赋值 `$rows` 再单独格式化，后续沿用该写法 |

### Current Update — 2026-08-10 Phase 59 同配置完整路线快速复跑
用户确认机器狗再次位于官方起点，要求不改参数、不重复软件测试和诊断，以最快速度重跑 Phase 58 相同的 `ObstacleFootprint + 双向 upper_corner_clear + 0.20m` 完整 13 点路线。仅执行临时部署、启动完成门禁、`full_interleaved --stop-on-failure` 与结束清理。

### Phase 59: 同配置 13 航点快速复跑
- **Status:** complete（完成同配置快速复跑；前 2 点成功，第 3 点 `pos1_middle` 超时，第 4–13 点未发送）
- [x] 临时部署同一三文件修复并快速启动完整链。
- [x] 启动完成后立即执行 13 点 `full_interleaved --stop-on-failure`。
- [x] 成功或明确失败后停栈、恢复部署并记录结果。

### Current Update — 2026-08-10 Phase 58 `ObstacleFootprint` + 13 航点完整实跑
用户确认机器狗已人工搬回官方起点，要求完整运行 Phase 57 修复后的 13 航点路线。保持 `ObstacleFootprint.scale=0.02`、双向 `upper_corner_clear`、local static layer、两处 `xy_goal_tolerance=0.20m`、`robot + custom + 640x360x30 + backend true`、无运动恢复 BT 和其余控制参数不变；通过空栈、部署一致性、插件/路线、Nav2 active、末端零速门禁后执行 `full_interleaved --stop-on-failure`，任何失败立即阻止后续 goal 并清理。

### Phase 58: 矩形足迹 13 航点 L6 验收
- **Status:** complete（完成完整路线尝试；前 2 点成功，第 3 点 `pos1_middle` 末端极限环超时，第 4–13 点未发送）
- [x] 核对本机修复、Jetson 空栈/部署状态并临时同步最小文件。
- [x] 验证运行时 `ObstacleFootprint`、13 点路线、Nav2 active 与末端零速。
- [x] 运行完整 `full_interleaved --stop-on-failure` 并看护到成功或明确失败。
- [x] 安全停栈、恢复 Jetson 部署和锁频，解析结果并同步 PWF。

### Phase 58 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 只读 sysfs 脚本最后一行被 PowerShell CRLF 带入远端路径，`cur_freq\r` 不存在 | 1 | 前五项 CPU/GPU min/max/current 读数有效且未改状态；改用 root `jetson_clocks --show` 完成只读核验，不重复同一脚本 |
| 备份准备脚本的远端 `tr -d "\r"` 引号被错误解释为删除字母 `r`，`mkdir` 变成 `mkdi` | 1 | 脚本在创建目录前退出、部署文件未变；后续多行远端脚本统一改为 UTF-8 Base64 传输 |
| PowerShell 把 Base64 经 SSH stdin 传输时在尾部附加无效字节，远端脚本执行后报 `base64: invalid input` | 1 | 备份主体和哈希已完整生成；后续把 Base64 放入 SSH 远端命令参数，不再走 PowerShell stdin |
| 首次启动状态读取中的 `$(cat ...)` 被本机 PowerShell 提前解释，产生无效 `STATE=exited` | 1 | 启动日志仍在正常写入、未重复启动；后续使用固定 PID 或 Base64 远端脚本读取状态 |
| 路线控制脚本只等待 1 秒就读取 `route_dir.txt`，文件尚未生成导致外层 rc=1 | 1 | 唯一 wrapper/probe PID 正常运行且随后生成目录；未重复启动或发送第二组 goal，改按实际 PID/日志看护 |

### Current Update — 2026-08-10 Phase 57 DWB 矩形足迹与双向墙角过渡修复
用户确认 Phase 56 失败根因并要求先实施修复：将 DWB 的圆形/中心障碍 critic `BaseObstacle` 替换为矩形足迹 critic `ObstacleFootprint`，同时把上侧观察路线改为 `pos1_middle -> upper_corner_clear -> pos2a_upper_right -> upper_corner_clear -> pos1_middle_turned`。机器狗当前停在约 `(1.755,3.780,0.616)`，不在官方起点；本阶段只做本机 L0/L1 验证，不下发运动命令。

### Phase 57: 矩形足迹 critic 与对称过渡路线
- **Status:** complete（L0/L1 软件与离线几何验证完成；未在非官方起点部署或启动运动栈）
- [x] 将 DWB critic 和对应 scale 参数从 `BaseObstacle` 切换为 `ObstacleFootprint`。
- [x] 同步 preview、真实模板、默认路线常量和导航说明中的双向 `upper_corner_clear`。
- [x] 更新并运行 critic/路线/静态足迹扫掠回归测试。
- [x] 运行静态检查与 ROS 技能验证器，完成 PWF 同步。

### Phase 57 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 两次只读文件存在性检查把 PowerShell `foreach` 直接接管道，触发 `An empty pipe element is not allowed` | 2 | 未修改文件或设备；改为先把循环结果赋给 `$rows`，再单独送入管道 |
| 首次 PWF 增量补丁使用了不存在的 `progress.md` 末尾锚点 | 1 | 补丁被原子拒绝、三件套未变化；读取实际末尾后改用精确锚点分开追加 |
| 首次全量 unittest discovery 未设置 `PYTHONPATH=src`，且命中既有 Lite3 mock 缺少 `test_closed_yaw` 字段 | 1 | 本次相关 12 项仍通过；按既有仓库口径设置正确 `PYTHONPATH` 并排除 `test_lite3_udp_smoke.py` 后重跑扩展套件 |

### Current Update — 2026-08-10 Phase 56 静态墙修复后完整 12 航点实跑
用户确认机器狗已回官方起点，要求减少启动检查并快速运行修复后的完整导航。保持 Phase 55 的 local static layer、`upper_corner_clear`、两处 `xy_goal_tolerance=0.20m`、`robot + custom + 640x360x30 + backend true`、无运动恢复 BT 和其余控制参数不变；只做空栈、部署哈希、Nav2 active、末端零速四项必要门禁后运行 `full_interleaved` 12 航点，任一失败立即阻止后续 goal 并清理。

### Phase 56: 修复后完整路线 L6 验收
- **Status:** complete（完成修复版全路线尝试；前 3 点成功，第 4 点足迹切墙后 NavFn 重规划失败，第 5–12 点未发送）
- [x] 最小文件临时同步到 Jetson，并验证运行时 12 点路线与 local static layer。
- [x] 快速启动完整定位、Nav2、bridge 与 Lite3 执行链，确认 active/零速。
- [x] 运行 12 航点 `full_interleaved --stop-on-failure` 并看护到成功或明确失败。
- [x] 安全停栈、恢复 Jetson 干净部署和锁频，解析结果并同步 PWF。

### Phase 56 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 修复文件已安装且结构检查通过，但首次离线 `--describe-route` 未 source ROS 2，导入 `rclpy` 失败 | 1 | 不重复部署；补 source `/opt/ros/foxy/setup.bash` 后仅重跑路线描述与哈希核验 |
| Foxy `setup.bash` 在 `set -u` 下读取未定义的 `AMENT_TRACE_SETUP_FILES`，第二次路线描述在 source 阶段退出 | 2 | 将 ROS source 放在 `set -u` 之前，严格模式只作用于后续核验命令 |
| 首次锁频/启动的本机工具编排脚本语法错误，SSH 命令未发出 | 1 | Jetson 状态未改变；改为合法的 JavaScript 字符串封装同一 Base64 远端脚本 |
| 完整路线第 4 点 `pos2a_upper_right` 运动途中 NavFn 周期重规划失败 | 1 | `--stop-on-failure` 阻止第 5–12 点；controller/bridge 归零后停栈。几何复算确认矩形足迹先切入静态墙，当前 DWB 仅有 `BaseObstacle` 而缺少已安装的 `ObstacleFootprint` critic |

### Current Update — 2026-08-10 Phase 55 第 5 段静态墙与过渡航点修复
用户授权按 Phase 54 结论实施修复。本阶段为 DWB local costmap 增加静态地图层，在 `pos2a_upper_right` 与 `pos1_middle_turned` 之间加入 `upper_corner_clear=(2.60,3.25,pi)`，同步 preview/真实标定路线契约并增加静态足迹扫掠回归；保持 `xy_goal_tolerance=0.20m`、速度、backend 与 inflation 参数不变。机器狗当前不在官方起点，本阶段只完成 L0/L1 软件验证，不启动运动栈。

### Phase 55: local costmap 静态墙与安全过渡路线
- **Status:** complete（L0/L1 软件修复完成；机器狗回官方起点后的前六点 L6 验证另开阶段）
- [x] local costmap 增加 `static_layer`，保留现有 inflation 参数。
- [x] preview/真实标定路线及默认常量加入 `upper_corner_clear`。
- [x] 新增并运行静态地图、插件和足迹扫掠回归测试。
- [x] 完成 ROS 技能检查与 PWF 同步，等待机器狗回官方起点后再做前六点 L6 验证。

### Current Update — 2026-08-10 Phase 54 第 5 段 NavFn 失败根因复算
用户询问 Phase 53 完整路线第 5 点失败原因。本阶段只读核对 ROS/Nav2 配置、远端路线产物、Phase 1 PGM 与实际第 5 段轨迹，不启动 Jetson 软件栈或下发运动命令。

### Phase 54: 第 5 段静态地图/足迹几何诊断
- **Status:** complete（已确认 DWB 本地代价地图看不到静态墙，转弯足迹切入上巡检区墙角，随后 NavFn 从膨胀区内重规划失败）
- [x] 核对第 5 段起终位姿、目标净空和 NavFn 失败时序。
- [x] 按实际 PGM、`0.025m` 分辨率、`0.70x0.50m` 足迹及 `0.02m` padding 复算整段静态碰撞。
- [x] 核对 global/local costmap 插件与 `0.30m` inflation 配置，划分直接原因与修复方向。

### Current Update — 2026-08-10 Phase 53 `0.20m` 完整 11 航点实跑
用户确认机器狗已回官方起点，要求复用 Phase 52 成功版参数启动完整导航执行链并跑完 `full_interleaved` 全部 11 个航点，观察能否全部成功。本阶段保持两个 `xy_goal_tolerance=0.20m`、`robot + custom + 640x360x30 + backend true`、同一无运动恢复 BT 和其余运动参数不变；最小门禁后直接运行全路线，任一航点失败则 `--stop-on-failure` 阻止后续航点并安全清理。

### Phase 53: `0.20m` 完整全路线验收
- **Status:** complete（已完成全路线尝试；前 4 点成功，第 5 点运行中重规划失败，后 6 点未发送）
- [x] 临时同步 Jetson 两个 `xy_goal_tolerance=0.20m`，锁频并启动完整定位、桥接、Nav2 与 Lite3 执行链。
- [x] 确认 live 参数、实际 30 Hz/backend 配置、Nav2 active 与末端零速。
- [x] 运行 `waypoints_reordered_preview.yaml/full_interleaved` 全部 11 航点并看护到明确失败；`--stop-on-failure` 正确阻止后续航点。
- [x] 安全停栈、恢复 Jetson YAML 与锁频，解析分段结果并同步 PWF。

### Phase 53 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 首次冷启动的 lifecycle manager 卡在 `planner_server` 激活阶段，日志停于 StaticLayer resize 后且未发送 goal | 1 | bridge 持续零速；干净停止全栈与容器后冷重启，同参数第二次启动出现 `Managed nodes are active` |
| 首次合并 lifecycle 查询在 `planner_server` 响应处超时 | 1 | 该轮随后确认确为 planner 激活卡死；不把 CLI timeout 当成 active，停止后重启 |
| 完整路线第 5 点 `pos1_middle_turned` 运动途中 NavFn 周期重规划失败 | 1 | BT abort、controller cancel 后 bridge 归零；`--stop-on-failure` 阻止第 6–11 点，随后安全停栈并保留完整产物 |
| 最终远端空栈复核命令中的正则和 Docker format 被 Windows SSH 参数拆分 | 1 | 丢弃该次无效的进程/Docker输出，改用 Base64 传递远端 Bash 脚本后确认进程、Docker 均为空 |
| 最终复核发现两份 Phase 53 启动输出仍留在 `/tmp` | 1 | 精确删除 `/tmp/codex_phase53_start.out` 与 `/tmp/codex_phase53_retry_start.out` 并确认均不存在 |

### Current Update — 2026-08-10 Phase 52 `xy_goal_tolerance=0.20` 单变量实车验证
用户确认机器狗已回官方起点，要求减少重复预检后直接验证 `pos1_middle` 极限环是否由 `0.15m` 位置容差触发。本阶段只把 `goal_checker.xy_goal_tolerance` 与 `FollowPath.xy_goal_tolerance` 改为 `0.20m`，保持 `robot + 30 Hz + backend on` 及其余参数不变；启动完整导航执行链，但只发送 `full_interleaved` 前三个航点。若第三点进入容差则观察平移归零和最终原地调向；若再次出现绕圈则立即停止，不等待完整超时。

### Phase 52: `0.20m` 位置容差前三航点 A/B
- **Status:** complete（前三航点全部成功；第三点进入 `0.20m` 后平移归零并完成最终原地调向）
- [x] 同步修改本机与 Jetson 实际加载的两个 `xy_goal_tolerance`，做聚焦静态检查。
- [x] 以最小门禁启动 `robot + 30 Hz + backend on` 完整定位、桥接、Nav2 与 Lite3 执行链。
- [x] 只运行 `full_interleaved` 前三个航点，实时判断第三点是否进入 `0.20m` 并切换到最终原地调向。
- [x] 成功后安全清理，恢复临时部署状态并解析结果、同步 PWF。

### Phase 52 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 后台启动 SSH 因远端 wrapper 未完全脱离会话而在本机超时 | 1 | Jetson 启动进程正常存活；改用独立 SSH 读取启动日志并继续，不重复启动 |
| 合并式运行态门禁脚本误写为 `$DEPLOY=...`，导致只读 CLI 打印 Fast DDS XML 路径告警 | 1 | live 参数与 lifecycle 查询仍成功；后续远端多行脚本统一用正确变量赋值和 Base64 传输 |
| PowerShell 提前展开路线命令中的 `$RUN_DIR`，产物暂存到部署目录下的空格路径且 `tee /console.log` 无权限 | 1 | 航点与控制参数未受影响，probe 完成且 `ok=true`；将三份完整产物移动到标准日志目录并清除两个临时目录 |
| 首次结果读取再次因 PowerShell 展开远端变量与引号而失败 | 1 | 未改变运行态或产物；改用 Base64 传递结构化 Python 只读解析脚本 |

### Current Update — 2026-08-09 Phase 51 机器人 30 Hz 后端交错全路线
用户已将机器狗搬回官方起点，要求修复一键比赛启动的默认 cuVSLAM 配置为已验证的 `robot + custom + 640x360x30`，开启后端优化并快速重跑同一条 `full_interleaved`。本阶段先以最小代码改动固化默认值和低负载输出，做聚焦静态/契约验证；实车启动同时锁定 Jetson 频率并用 1 Hz tegrastats 记录 GR3D/CPU，实际生成配置、Nav2 active 与末端零速通过后立即发路线。成功或明确失败后停止全栈、恢复锁频并解析全路线与资源证据。

### Phase 51: `robot + 30 Hz + backend on` 全路线实跑
- **Status:** complete（30 Hz 后端路线仍在第 3 点超时，以明确失败结束并已安全清理）
- [x] 修复 `start_competition.sh` 默认 mount/profile/camera profile 与低负载启动参数，并增加聚焦契约测试。
- [x] 本机静态检查与聚焦测试通过后，用显式同值环境变量启动 Jetson，避免部署脚本尚未同步造成歧义。
- [x] 最小门禁确认空栈、D455/Lite3 在线、锁频、实际生成 `robot + 30 Hz + backend true`、Nav2 active 与零速。
- [x] 启动 1 Hz tegrastats 并运行同一 `full_interleaved --goal-timeout 130 --stop-on-failure`。
- [x] 第 3 点明确失败后安全清理、恢复锁频，解析分段结果、frame-delta/tracking/DDS 与 GR3D/CPU 数据并同步 PWF。

### Phase 51 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 首次新增 Phase 49 的补丁因 PWF 已被外部会话新增同编号 Phase 49/50 而锚点失配 | 1 | 补丁被原子拒绝、产品代码未变；保留外部新增内容并改用 Phase 51 |
| 本机 PowerShell 环境没有 `bash`，首次并行检查中的 `bash -n` 无法执行 | 1 | 其他并行结果未显示；改为把脚本内容通过 stdin 送到 Jetson `bash -n`，语法检查通过且未写远端文件 |
| `robot + 30 Hz + backend on` 的 `full_interleaved` 第 3 点 `pos1_middle` 仍在 130 秒后超时 | 1 | probe 取消 goal、阻止第 4–11 点；停止全栈与 telemetry、恢复测试前锁频，确认相关进程与 Docker 为空 |

### Current Update — 2026-08-09 Phase 50 安装 ROS 2 Engineering Skill
用户确认安装 Phase 49 的首选候选 `ros2-engineering-skills`。本阶段使用 Codex 官方 `skill-installer` 从指定 GitHub 仓库根目录安装到用户级 Codex skills，并验证 manifest、关键 references、scripts、hook 文件和手动校验器；不修改产品代码或 Jetson 状态。

### Phase 50: 安装与验证 `ros2-engineering-skills`
- **Status:** complete
- [x] 加载 `skill-installer` 并确认目标目录尚不存在。
- [x] 核验 GitHub 仓库根目录为技能根，包含 `SKILL.md`、references、scripts 与 hook 配置。
- [x] 使用官方 helper 安装到 `~/.codex/skills/ros2-engineering-skills`。
- [x] 验证版本、文件清单、关键 Nav2/实时/诊断/安全 references 和 SHA-256。
- [x] 运行手动验证器自检并确认 `status=pass`。

### Current Update — 2026-08-09 Phase 49 ROS 2 / Nav2 / SLAM 技能发现审计
用户明确要求调用 `find-skills`，寻找可用于当前导航、SLAM 和机器人工程工作的技能。本阶段仅执行技能生态发现、本机已安装技能内容审计、候选来源/活跃度/安全信号核验和适配性分级；不安装技能，不修改产品代码或 Jetson 状态。

### Phase 49: ROS 2 / Nav2 / SLAM 工程技能发现
- **Status:** complete
- [x] 加载并遵循 `find-skills`，先检查 skills.sh 排行榜。
- [x] 使用 ROS 2、Nav2、SLAM、RTAB-Map、VIO、DWB、传感器融合、性能分析等关键词搜索候选。
- [x] 审计本机已安装 ROS 2 技能及其引用材料。
- [x] 核验主要候选的技能内容、来源活跃度与安全审计信号。
- [x] 形成“建议采用 / 有条件参考 / 不建议安装”分级；本轮不安装。

### Phase 49 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 首次读取本机 `ros2-robotics` 时误把目录推断为 `engineering-skills/ros2-robotics` | 2 | 两个错误路径均不存在；按技能目录索引改读实际 `~/.codex/skills/ros2-robotics/SKILL.md`，随后完整读取三份 reference |
| 一次浏览器候选汇总代码误在无持久变量的外层工具隔离中引用 `skillsTab` | 1 | 没有网页或本地状态变化；改在已连接浏览器的持久会话中执行并完成核验 |
| 首次 PWF 三文件补丁仍以 Phase 46 为顶部锚点，但并发工作已将最新阶段推进到 Phase 48 | 1 | 补丁被原子拒绝，三件套均未变化；重新读取当前顶部与末尾，按 Phase 49 增量合并 |
| 最终只读 `rg` 核验的 PowerShell 双引号模式包含 Markdown 反引号，导致字符串未闭合 | 1 | 命令在解析阶段失败、文件未变化；改用单引号正则后核验三件套通过 |

### Current Update — 2026-08-09 Phase 48 后端优化开启的交错路线 A/B 对照
用户要求保持 2026-08-06 `full_interleaved` 航点顺序不变，重新开启 cuVSLAM 后端优化并实跑同一路线。实查确认 `enable_localization_n_mapping=True`，但现有 `start_competition.sh` 仍固定由 `/visual_slam/tracking/odometry` 驱动 Nav2，因此本轮检验的是“后端优化并行开启对既有前端导航链的影响”，不是 Nav2 直接跟随后端优化轨迹。事后运行时溯源进一步确认前端-only 与后端-on 两轮都因一键脚本默认值实际使用 `bench + planar_60fps`，不是已验证的 `robot + 30 Hz`；两轮观察输出均关闭，但 startup topic checks 开启且均无连续 GR3D/CPU 监控。后端开启结果仍为前两点成功、第 3 点 `pos1_middle` 超时；已安全清理。

### Phase 48: 后端开启的 `full_interleaved` 实车对照
- **Status:** complete（后端开启对照仍在第 3 点超时，以明确失败结束并已安全清理）
- [x] 核对 cuVSLAM 后端开关与 Nav2 实际消费的位姿/TF 链；确认后端计算开启，但 Nav2 继续消费 tracking odometry。
- [x] 完成最小只读预检：Jetson 空栈、D455/Lite3 在线、部署 `52d30d6` clean。
- [x] 用户确认机器狗已回官方起点并要求快速启动。
- [x] 冷启动后端开启的定位与 Nav2；生成配置为 backend true，5 个 lifecycle 均 active，启动日志末端三轴零速且 UDP errors=0。
- [x] 运行同一 `waypoints_reordered_preview.yaml/full_interleaved` 路线，保持 `--goal-timeout 130 --stop-on-failure`。
- [x] 第 3 点超时后立即运行 `stop_all.sh`、停止 cuVSLAM 容器，完成前后端分段对比并同步 PWF。

### Phase 48 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 本地 `rg` 在 Windows PowerShell 中把位置参数 `*.md` 当作无效路径通配符，检索批次返回 1 | 1 | 未连接 Jetson、未改变设备状态；移除该位置通配符，改为对 `scripts`、`configs` 目录级检索 |
| 启动监控等待旧文案“系统启动完成”，实际日志为“启动完成”，导致栈已就绪后被误报 timeout | 1 | 未发航点；直接核对启动日志、后端生成配置和 lifecycle，确认栈健康后继续 |
| 最小零速门禁引用不存在的旧路径 `/tmp/cmd_vel_bridge.log`，阻止第一次 route 启动命令 | 1 | 航点未发送；复用启动日志连续 `last_send=(0,0,0)`、`udp_errors=0` 证据后放行 |
| 第一次 probe 进程因手工覆盖 `PYTHONPATH` 时遗漏 deploy `src`，导入 `nodes.navigation` 失败 | 1 | 发生在 ROS 节点创建前、未发航点；加入 `$DEPLOY/src` 后启动成功 |
| 后端开启的 `full_interleaved` 第 3 点 `pos1_middle` 仍在 130 秒后超时 | 1 | probe 取消 goal 并阻止第 4–11 点；执行零速清理、停止容器，确认相关进程与 Docker 为空 |
| 后端对照启动未显式覆盖 `CUVSLAM_MOUNT_MODE/PROFILE`，实际回退到 `bench + planar_60fps`，且没有连续 GPU/CPU 监控 | 1 | 事后由精确运行目录的 `runtime_config.env`、生成 launch 和 launch.log 确认；本轮结果只保留为 60 Hz 条件下的 backend off/on 对照，不能外推到 `robot + 30 Hz` |

### Current Update — 2026-08-09 Phase 47 前端单独导航完整比赛路线
用户已将机器狗放在起点并授权随时开始。本阶段关闭已证实会恶化位姿结果的后端优化，仅使用视觉前端里程计链，复用上次调整航点位置后的 navigation-only 完整比赛流程。先核对干净部署目录、配置与航点版本，再执行静态门禁、冷启动、运行态验证和整条路线；任何 TF、传感器、Nav2 lifecycle、急停或唯一实例门禁失败都不放行运动。

### Phase 47: 前端单独 navigation-only 全路线实车验收
- **Status:** complete（正确的 `full_interleaved` 实跑在第 3 点 `pos1_middle` 超时，以明确失败结束）
- [x] 定位并核对上次调整后的航点文件、navigation-only 启动入口及前端/后端开关。
- [x] 只读预检 Jetson、D455、机器人连接、急停、零速度、相关进程、部署 HEAD 与配置。
- [x] 冷启动前端-only 定位与 Nav2，确认后端优化确实关闭且 TF/topic/lifecycle/定位健康。
- [x] 启动 navigation-only 完整比赛路线，并实时看护关键失败条件（第 2 段触发 0.300m 安全半径后停止）。
- [x] 等待完整路线成功或明确失败，随后安全停止、采集结果并同步 PWF。
- [x] 用户现场将机器狗搬回官方起点，并明确选择 2026-08-06 的 `full_interleaved` 受控 preview 路线。
- [x] 第二次只读复核远端空栈、D455、狗网络、deploy HEAD/clean、路线解析和算力门禁。
- [x] 以纯前端配置冷启动，并额外关闭 landmarks/observations/loop-metrics 非必要观察负载。
- [x] 运行 `full_interleaved --allow-preview-route --goal-timeout 130 --stop-on-failure` 的 11 航点完整路线（第 3 点超时，后续 8 点未发送）。
- [x] 安全清理、解析分段结果并同步 PWF。
- [ ] 用户将狗搬回官方起点后，决定是否先修正 `pos1_middle` 坐标/终端朝向再重跑；禁止原地自动重试。

### Phase 47 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 远端只读构建检查在 `set -u` 下 source Foxy setup，因 `AMENT_TRACE_SETUP_FILES` 未定义而提前退出 | 1 | 未启动 ROS/容器/运动；去掉 nounset 后重查 ROS prefix 与锁频状态 |
| 组合动作前门禁把多项 ROS 2 CLI 查询放在同一 SSH 会话，外层 124 秒超时 | 1 | waypoint 未启动、持续零速；改为直接读生成配置并对每项 ROS 查询加独立短超时 |
| PowerShell 内嵌 SSH 命令中的正则管道被本机误解析，容器文件检索未发出 | 2 | 远端无变化；后续所有含管道的远端脚本统一使用 UTF-8 Base64 传输 |
| Jetson Foxy `ros2 topic echo` 不支持 `--once` 或 `-n 1`，短 discovery 窗口也未截到样本 | 2 | 不再依赖该 CLI 采样；采用 bridge 连续诊断的末端零速，并由 route probe 在接管时强制验证 mode/lease/零速 |
| 前端-only `nav-only-full` 第 2 段 yaw-only 转身期间 XY 锚点位移 `0.3093m`，超过 `0.300m` 安全半径 | 1 | probe 正确标记 `TAKEOVER_ABORTED`、释放 precision lease、阻止后续 7 段；全栈与 Docker 已清理，不自动重试 |
| 最终日志校验预设 Jetson 安装了 `jq`，实际命令不存在 | 1 | 哈希/空栈/Git 验证不受影响；改用 `python3 -m json.tool`，确认 summary JSON 有效 |
| 第二次运行前批量 lifecycle 查询中 `controller_server` 未在 5 秒内返回，另有 active 查询打印结果后 CLI 仍未退出 | 1 | waypoint 尚未启动；改为单独延长 timeout 查询 controller，并用日志/节点/action/topic 交叉验证 |
| 第二次 PWF 多文件补丁的 task_plan 锚点未匹配 | 1 | 补丁被原子拒绝、三件套均未变化；读取准确锚点后拆分更新 |
| 正确的 `full_interleaved` 第 3 点 `pos1_middle` 在 130 秒后未进入容差并超时 | 1 | probe 正确取消 goal、`--stop-on-failure` 阻止第 4–11 点；全栈/Docker 已清理，需先调整该航点而非盲目重跑 |

### Current Update — 2026-08-09 Phase 46 Jetson DWB 干净部署工作区
用户确认 Windows DWB 已整理干净并授权通过 SSH 处理 Jetson；本阶段严格限定 `Stonefield/nav2-foxy-dwb-integration`。先实时复核本机/远端 commit 与旧工作区状态，完整保留旧 DWB 现场，不对其执行 reset/clean；随后建立直接跟踪 GitHub DWB 分支的干净部署 clone，并验证 branch/upstream/HEAD、clean 状态及 `pull --ff-only` 契约。不触碰 Jetson 的 main/stable/vision/Isaac ROS 工作区，不启动 ROS、Docker 或运动链。

### Phase 46: Jetson DWB 单向部署规范化
- **Status:** complete
- [x] 确认本机 DWB clean，`HEAD` 与 GitHub tracking ref 均为 `52d30d6`。
- [x] 实时只读复核 Jetson 旧 DWB 的路径、HEAD、dirty/untracked、运行进程和磁盘空间。
- [x] 保存旧 DWB 现场边界与可恢复信息，不删除或改写旧工作区。
- [x] 新建直接跟踪 `origin/Stonefield/nav2-foxy-dwb-integration` 的干净部署 clone。
- [x] 验证新 clone 的 HEAD/upstream/clean 状态和 `git pull --ff-only` 行为。
- [x] 同步 findings/progress，并报告新旧目录与后续部署命令。

### Phase 46 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 首次 PowerShell 文件统计把 `foreach` 结果直接接入管道，报 `An empty pipe element is not allowed` | 1 | 命令在本机解析阶段失败，未连接 Jetson；改用显式数组后完成统计 |
| 当前宿主未暴露 ByteRover MCP，且本机没有 `brv` CLI | 1 | 无法执行复杂部署任务前的 L1-3 主动检索；以已合并 PWF 审计证据和实时 Git 复核为准 |
| 首次多文件 PWF 状态补丁使用了只存在于 progress 的末尾锚点 | 1 | 补丁被原子拒绝、三件套均未变化；改为逐文件用稳定锚点增量更新 |
| 首次 `git bundle verify` 从非 Git 仓库的备份目录运行，返回 `need a repository` | 1 | 快照 SHA-256 已通过；改从旧 DWB 仓库上下文验证同一 bundle，确认包含 `72e3833` 完整历史 |

### Current Update — 2026-08-09 Phase 45 Jetson 远端 Git 工作区只读审计
用户要求厘清 Jetson 在“本机提交并推送、Jetson 只拉取部署”的模式下是否应保留本地 commit/改动，并盘点当前远端多个仓库的真实状态。本阶段只读检查仓库路径、branch/HEAD/upstream、tracked/staged/untracked 差异、worktree 与部署来源；不执行 fetch/pull/add/commit/reset/clean，不修改远端文件或运行态。

### Phase 45: Jetson 远端 Git 漂移与部署职责审计
- **Status:** complete（完成只读审计；发现审计期间存在外部并发 fetch/merge，已用 reflog 和最终快照校正；未实施清理或同步）
- [x] 验证普通用户/root 只读 SSH，并定位 Jetson 上全部相关 Git 仓库与 worktree。
- [x] 对每个仓库采集 branch、HEAD、upstream、本地 ahead/behind、tracked/staged/untracked 状态。
- [x] 将差异分类为源码修改、部署补丁、构建/日志/备份产物和可忽略环境文件。
- [x] 对照本机 main/DWB HEAD 与远端已知 refs，判断 Jetson 是否存在未回收的唯一代码。
- [x] 给出不丢改动的 GitHub 单向部署治理选项；本轮不实施清理或同步。

### Phase 45 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 当前宿主未暴露 ByteRover MCP，且本机没有 `brv` CLI | 1 | 无法执行复杂远端审计前的 L1-3 主动检索；明确记录限制，继续以合并 PWF 和远端 Git 只读证据为准 |
| 首次 PWF 补丁仍以旧主 worktree 为默认落点，progress 锚点不匹配 | 1 | 补丁被原子拒绝、两边文件均未变化；改用显式 DWB 相对路径写入 |
| 首次紧凑哈希脚本含未转义的 JavaScript template literal 反引号 | 1 | 脚本在工具编排层解析失败，PowerShell/SSH 均未启动；移除内嵌反引号后重试 |
| Windows OpenSSH 将远端 `python3 -c` 的未转义双引号剥离 | 1 | 远端 Bash 仅发生语法解析错误，没有执行审计 Python；改为向远端 shell 传递 `\\\"...\\\"` |
| 把三个本地文件内容内嵌到 SSH argv 超过 Windows 命令行长度 | 1 | 该命令未启动 SSH；改用受控临时目录 `scp` 只读副本并以 `git diff --no-index` 比较，完成后验证路径并清理临时文件 |
| 首次视觉 worktree 审计遗漏了路径中的 `worktrees/` 层级 | 1 | Git 只返回路径不存在，未产生写操作；通过只读 `find` 定位为 `/home/superwfx666/worktrees/quadruped-vision-yolo-refactor` 后重跑 |
| PowerShell `Sort-Object Count -Descending,Name` 参数组合语法错误 | 1 | 脚本在本机解析阶段退出，未连接远端；改为显式属性表达式后完成汇总 |
| 审计期间外部会话在视觉测试 worktree 执行 fetch/merge，HEAD/ref 发生变化 | 1 | 本轮未执行任何 Git 写命令；用 branch/ref reflog、live `ls-remote` 和最终状态重新取证，并将结论标记为时间点快照 |

### Current Update — 2026-08-09 Phase 44 多 worktree PWF 三件套合并
用户授权将主 worktree 与 DWB worktree 的 PWF 三件套语义合并，并以 `quadruped-robot-competition-nav2-dwb` 根目录中的三份文件为最终目标。先保存两套原件备份；主计划作为 Phase 1–43 主干，DWB 专项计划按历史支线映射，进度与发现按主题去重补入；不修改任何产品代码。

### Phase 44: 主/DWB PWF 三件套智能合并
- **Status:** complete
- [x] 核对两套三件套规模、结构、阶段与 Git ignore 状态。
- [x] 备份主/DWB 六份原件并记录哈希。
- [x] 合并 task_plan：保持主线阶段编号与当前 Phase 42，映射 DWB 历史支线和独有错误。
- [x] 合并 progress/findings：按时间与主题去重，补入 DWB 独有实测证据。
- [x] 写入 DWB 根目录并核验 UTF-8、结构、哈希、目标 Git 状态和原件可恢复性。

### Phase 44 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| PowerShell 双引号检索串包含 Markdown 反引号，出现 `The string is missing the terminator` | 1 | 命令在解析阶段失败、文件未修改；改用单个字面量模式分开检索 |

### DWB 专项计划合并映射 — 2026-08-09

原 DWB 计划《排查 cuVSLAM 30.5 秒周期性断帧》已从备份 `tmp/pwf_merge_backup_20260809-172504/dwb_before/task_plan.md` 语义并入本计划。为避免与项目主计划 Phase 1–43 冲突，不保留第二套数字阶段作为活跃阶段。

| DWB 原阶段 | 原状态 | 合并去向 |
|---|---|---|
| Phase 1–4：安全边界、125 秒隔离实验、归因与结论 | complete | 主计划 Phase 34–35；独有测量补入 findings/progress |
| Phase 5–7：轻量观察探针、静止 A/B、本地/Jetson 验证 | complete | 作为 2026-08-08 历史专项并入 findings/progress |
| Phase 8：完整导航数据连续性与漂移归因 | in_progress | 已由主计划 Phase 36–42 继续推进；当前活跃入口仍为 Phase 42 |
| Phase 9：全局纠漂方案验证 | pending | 由主计划 Phase 33 全局校正支线与 Phase 41 替代后端支线承接 |

#### DWB 原计划独有错误保留

| Error | Attempt | Resolution |
|---|---:|---|
| planning-with-files 路径不在 `.codex\\skills` | 1 | 使用 `.agents\\skills\\planning-with-files` |
| 远端启动脚本 runner 调用 `get_launch_description()` 缺少 context | 1 | 直接用 `ros2 launch` 生成的 launch 文件，避免修改用户脚本 |
| wrapper-only 初次探针订阅错误命名空间 | 1 | 依据实际 `/infra1`、`/infra2`、`/imu` topic 重跑 |
| cuVSLAM 镜像缺少 `pyrealsense2` Python binding | 1 | 改在 Jetson 主机直接运行 librealsense 探针 |
| USB autosuspend A/B 需要 sudo 密码 | 1 | 不代填密码；该早期候选后来由 GNOME 单变量 A/B 取代 |
| 扩大回归仍有 `test_lite3_udp_smoke` 夹具缺少 `test_closed_yaw` | 1 | 确认为既有错误；新增功能相关 25 项通过，不修改无关夹具 |
| 本机没有 Docker/ROS 2 Humble，不能执行新 C++ 包真实 `colcon build` | 1 | 新增隔离构建脚本，并把 Jetson 构建成功作为现场门禁 |
| 本机 `cppcheck` 自动加载损坏的 `R:` 配置 | 2 | 不把工具故障视为源码结论，改用其他静态/构建验证 |
| `uv run` 创建的仓库内 `.venv` 清理被宿主删除策略拦截 | 1 | 不绕过策略；保留为 Git 忽略的临时环境 |
| observer 首次启动因默认 `PROJECT_DIR` 指向另一 worktree | 1 | 启动未进入 Docker；wrapper 显式固定自身仓库根并补契约测试 |
| 正式 A/B 仅完成 A1 后 Jetson 非正常重启 | 1 | A1 保留但整轮作废；重跑前重新核对锁频与主机稳定性 |
| 重启后首次 cuVSLAM 出现 Motion Module force pause、IR start failure | 1 | 未进入 A/B；精确清理后用 librealsense 直连确认设备恢复 |
| SAX 优化在 Jetson 遇到旧版 nlohmann 无 `binary_t/binary()` | 1 | metadata 为文本 JSON，移除新版专属回调以兼容旧版 |
| 短筛选传入 `--duration 30` 被 ROS 推断为 integer | 1 | 改用 `30.0`；正式 runner 默认 `120.0` |
| 用户终止静止探针优化支线时短筛选已进入 A1 前 6 秒 | 1 | 立即清理；不完整窗口不作为证据 |

### Current Update — 2026-08-09 Phase 43 Codex Workspace / worktree 模式审计
用户要求评估主 worktree 保存 PWF、DWB worktree 承担最新代码开发所造成的根目录错位，并联网核验更合理的 Codex 开发模式。当前只做 Git/Workspace/PWF 只读审计与方案设计；不重置、删除、移动或覆盖任一 worktree 的代码和三件套。

### Phase 43: Codex Workspace / worktree 与 PWF 单写者方案
- **Status:** complete
- [x] 恢复主 worktree PWF 上下文并核对所有 Git worktree、分支和未提交状态。
- [x] 核验 OpenAI 官方 Codex Projects 与 Worktrees 文档。
- [x] 确认主/DWB 三件套均为 Git ignore 本地文件且已经分叉。
- [x] 完成主 worktree 未跟踪文件与 DWB 已跟踪代码的重叠/差异盘点。
- [x] 给出保留全部现有改动的 Workspace 主目录切换、PWF 语义合并和旧目录归档方案。

### Phase 43 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| PowerShell 将 `foreach` 结果直接接到管道时出现 `An empty pipe element is not allowed` | 1 | 命令在解析阶段失败、文件未修改；拆为显式结果数组后重新执行只读统计 |

### Current Update — 2026-08-09 Phase 42 完整遥控路线回环验收完成，禁止保存地图
完整遥控比赛路线已在独立冷启动 diagnostics 会话中完成并优雅清理。运动窗无 tracking lost/frame delta，前端 tracking 闭环为 `0.524702m/3.259704deg`；唯一一次 GetAllPoses 同窗后端却为 `9.753458m/159.003463deg`，约为前端 XY 误差的 `18.59x`，并在 PGO 状态下出现 `1.880393m` 单步跳变。LC/PGO 确实活跃，最终图有 `285` 节点、`361` 边，但时间分段和最终节点排名两套判定均为“早期段到最终回访段长程边 0 条”；最后四分之一只有局部回环，最终 57 秒无非相邻新边，旧节点修正接近零。结论为“局部 LC/PGO 工作，但未形成目标全局回环，后端输出灾难性恶化”。未调用 save_map；当前地图不满足保存条件。

### Phase 42: 完整遥控比赛路线 LC/PGO 端到端验收
- **Status:** complete
- [x] 核对完整路线 runbook、当前部署配置与采集脚本，明确禁用地图保存和 Nav2。
- [x] 完成 Jetson、D455、锁频、磁盘、Docker/相关进程、diagnostics 配置与日志目录只读预检。
- [x] 获取现场物理起点、路线净空、低速遥控、遥控器回中、看护人与急停确认。
- [x] 冷启动独立 cuVSLAM diagnostics 会话并核验 tracking/JSONL 基线；不启动地图保存脚本。
- [x] 用户遥控机器狗走完整比赛路线并返回早期相似视野，停稳后抓 tracking 终点和唯一一次 GetAllPoses。
- [x] 分析长程回环边、LC/PGO 事件、全局图修正及同窗前后端闭环误差，给出证据化结论。
- [x] 完整清理运行会话并同步 PWF；不遗留运动、Nav2、地图保存或采集进程。

### Phase 42 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 本机组合检索预设了不存在的 `scripts/run_cuvslam_mapping_session.sh`，`rg` 返回文件不存在并使该批汇总退出 1 | 1 | 未连接 Jetson、文件未修改；列出 DWB 工作树真实脚本后，改为读取已验证的 `scripts/start_cuvslam_rviz_gui.sh` 与正式 runbook |
| 当前宿主未暴露 ByteRover MCP，且本机仍没有 `brv` CLI | 1 | 无法执行本阶段主动 L1-3 检索；不伪造召回结果，继续以 PWF、正式 runbook 和已部署工具为证据 |
| 首次多文件 `apply_patch` 的 hunk 边界格式无效，补丁被原子拒绝 | 1 | 三个文件均未变化；读取准确锚点后拆分为合法的增量补丁 |
| 首次 SSH 只读握手批次约 19 秒超时 | 1 | 未登录 Jetson、无远端变化；核对 Tailscale、ICMP 与 TCP/22 均正常，用户恢复 SSH 后以严格非交互参数连接成功 |
| 远端只读脚本首次尝试在 JavaScript 编排层调用不可用的 `Buffer` | 1 | 命令在生成阶段失败、远端未执行；改由 PowerShell UTF-8 Base64 编码后成功运行 |
| tracking 起点成功保存后，摘要脚本读取不存在的 `stamp` 字段 | 1 | 原始快照字段为 `header_stamp_sec`；不重复抓起点，复用唯一快照修正摘要并在之后打开运动窗口 |
| 唯一 GetAllPoses 的首次命令准备尝试向容器 root 创建的宿主目录重定向日志，权限不足 | 1 | shell 在 `docker exec` 前即失败；证明采样进程为空、postrun 不存在、launch 服务计数为 0 后，改为容器内落日志并完成唯一一次真实服务调用 |
| 证明 GetAllPoses 未调用的首次 SSH 命令嵌套引号未闭合 | 1 | 命令未到达容器、无远端变化；恢复 UTF-8 Base64 传输后只读证明通过 |
| 后台 launcher PID `7169` 对普通 `SIGTERM` 未退出 | 1 | 不强制删除容器；读取容器进程树并核验 ROS launch PID `7398` 后，以 root 向该进程发送 `SIGINT`，容器正常析构并生成 `graph_final/session_stop` |
| 收尾哈希清单预设了不存在的 `slam_all_poses.csv` | 1 | 其他哈希与 JSONL 校验有效；只读列出真实文件名为 `slam_all_poses_latest.csv`，不修改原始日志 |
| 直接打印 JSONL head/tail 因单行完整 graph snapshot 过大而超时 | 1 | 文件未变化；停止肉眼展开，改用结构化解析器只输出汇总 |
| 分析器第二轮通过 `Select-Object -First 14` 截断输出，PowerShell 提前关闭管道使 Python 返回 1 | 1 | 分析产物已在打印前完整写出；不重复同一命令，后续用 `Out-Null` 消费完整 stdout 并验证产物 |

### Current Update — 2026-08-09 Phase 41 替代回环后端调研完成
Phase 40 已把问题定位到“cuVSLAM 纯 VO tracking 正常，但没有形成目标起终点长程回环约束”；因此单独替换图优化器不能闭合根因。当前最务实路线是保留 `/visual_slam/tracking/odometry` 作为纯 VO，先做 `cuVSLAM VO + RTAB-Map stereo 回环/位姿图` 的隔离 PoC：复用同一 D455 驱动和现有 IR stereo topic，关闭 cuVSLAM mapping 与 `map -> odom`，关闭 RTAB-Map 自带 odometry，由 RTAB-Map 独占 `map -> odom`。该方案只是最快可证伪候选，不是生产换型结论；半程和完整路线继续冻结，先完成构建、静止负载与短闭环四层验收。

### Phase 41: cuVSLAM 外接回环后端联网调研
- **Status:** complete
- [x] 核验 2026 工业 benchmark 中 `cuVSLAM front-end + in-house SLAM back-end` 的原始方法、结果与证据限制。
- [x] 核验 RTAB-Map ROS 2 外部 odometry、stereo/RGB-D、TF、数据库与优化器接口。
- [x] 区分 RTAB-Map 完整回环后端、GTSAM/Kimera-RPGO 纯优化器和 ORB-SLAM3/stella_vslam 完整替换的能力边界。
- [x] 结合 Phase 40 根因、Xavier NX、D455 单驱动与现有 Humble 容器形成首选 PoC 架构和 Go/No-Go 门槛。
- [x] 保持 Jetson、容器、Nav2 和机器人运动链关闭；未实施换型或真机运动。

### Current Update — 2026-08-09 Phase 40 短闭环回环验收完成，结果失败
一次真实低速短闭环已完成并完整清理。运动窗口视觉 tracking 正常，LC 候选、`lc_status=1`、`pgo_status=1`、局部非相邻边和中段全局图修正均实际出现；但全部可靠非相邻边最多只跨 7 个关键帧，最终回访事件只跨 2 个，没有建立“末端新位置连接路线早期位置”的长程回环边。中段 LC 曾让 `48/53` 个共同旧节点移动超过 1 cm、中位净 XY 修正 `0.0761m`，最终回访则 `0/84` 个超过 1 cm。一次性 GetAllPoses 同窗后端误差为 `0.520313m/5.216deg`，显著差于 tracking 的 `0.078694m/4.160deg`。结论为“候选已识别、局部约束已接受且后端确实修正，但没有目标长程回环，优化结果反而恶化”。半程和完整路线继续冻结。

### Phase 40: 真实短闭环 LC/PGO 端到端验收
- **Status:** complete
- [x] 将 Phase 39 exporter 的证据边界转换为四层验收口径，并更新短闭环 runbook；diagnostics 必须开启，其他重型观察负载保持关闭。
- [x] 完成 Jetson、D455、锁频、Docker/相关进程和部署配置的只读预检；D455、六核/GPU 锁频、空闲进程门禁、GNOME 门禁和三文件哈希均通过。
- [x] 用户现场确认物理起点/早期视角、短路线净空、低速遥控、遥控器回中、看护人与急停均就位。
- [x] 独立冷启动 cuVSLAM diagnostics 会话，核验运行配置、tracking 起点和 JSONL 基线后，低速走一条回到早期相似视野的短闭环。
- [x] 停稳后抓 tracking 终点，只调用一次 GetAllPoses，并保留 diagnostics JSONL、精确运动窗口和 launch log。
- [x] 分层判定视觉跟踪、候选、边、LC/PGO 与全局图修正；确认只有局部闭合而无目标长程回环，且后端结果恶化，本级失败。
- [x] 完整清理本会话并更新 PWF；Docker 与相关进程为空，半程和完整路线未解冻。

### Phase 40 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 当前宿主未暴露 ByteRover MCP，且本机没有 `brv` CLI | 1 | 无法执行本阶段主动 L1-3 检索；不伪造长期记忆结果，继续使用 PWF、已部署源码和 runbook 作为证据，并在 findings 记录该限制 |
| tracking 起点准备命令中的 PowerShell/JavaScript 模板文本被宿主误解析 | 1 | 命令未发送到 Jetson、远端无变化；去除 `${...}` 形式后重组命令 |
| 禁止进程正则把预期 launcher 路径中的 `nav2-dwb` 误判为 Nav2 进程 | 1 | 只读列出命中项确认仅 launcher；改为精确进程名和具体运动脚本名，未停止或重启会话 |
| 宿主用户向容器内 root 创建的 `acceptance/short` 目录写 baseline 文件时权限不足 | 1 | tracking 起点已成功且保留，不重复抓取；确认 motion marker 尚不存在后，改由容器内部写 baseline 与 motion_start |
| 终点命令两次包含被宿主误解析的 `${launch_end}` 文本 | 2 | 两次均在本机组装阶段失败、未发送到远端；去除所有花括号插值后补齐行号，未重复抓 tracking 终点或调用 GetAllPoses |
| tracking 终点已保存后摘要脚本读取不存在的 `dt_sec` | 1 | 原始工具字段为 `elapsed_header_sec`；保留唯一终点与 delta 文件，后续只读现有 JSON，不重复采样 |
| 后台 launcher 对 `SIGINT` 未退出 | 1 | 不使用 `docker rm -f`；先执行 `docker stop -t 20` 等待容器 TERM，再由 `docker logs -f` 自然结束 launcher，容器和进程清空 |
| 后台容器 stop 路径未写 `graph_final/session_stop`，最终 JSONL 停在 `graph_event` | 1 | 不伪造终止事件；176 行运动/事件数据严格解析有效，最终轨迹由唯一一次 GetAllPoses 提供；记录该证据缺口，未来仍优先前台 Ctrl+C 正常收尾 |

### Current Update — 2026-08-09 Phase 39 完成
Jetson aarch64 真实构建、C++/Python 回归、动态依赖与静止 diagnostics A/B 全部通过。有效 A/B 的 130 秒窗口均无 frame delta 或 tracking lost；A 不生成 JSONL，B 严格解析 10 条记录并包含 4 个关联完整图的 `graph_event`、1 个 `graph_final` 和正常 `session_stop`。A/B 运行配置仅 diagnostics 开关不同，B 相对 A 的单点 CPU 增量为 `1.26` 个百分点、内存约 `6.3 MiB`，无持续异常负载迹象。exporter 具备下一条诊断路线的低负载采集条件，但第三次短环、半程和完整路线仍冻结，等待用户另行决定。

### Current Update — 2026-08-09 Phase 39 Jetson 构建通过，静止 A 测量重跑
wrapper 与 DWB diagnostics 接线已在逐文件哈希匹配、远端备份和 staging 校验后部署；Jetson aarch64/ROS/cuVSLAM 真实构建、3 项 C++ gtest、23 项远端 Python 契约与动态依赖检查均通过。首次 A 轮虽然未移动机器人且已完整清理，但基线行号在 tracker 启动日志完全落盘前抓取、窗口文件误含关机行且正则漏匹配原生 Delta 文本，因此该轮作废，不用于 A/B 判定。下一步按修正后的 readiness、精确行区间和告警正则重跑 A；路线继续冻结。

### Current Update — 2026-08-09 Phase 39 本机复审通过
用户授权直接安装本机工具链后，已在仓库 `tmp/toolchains/` 安装并校验便携 LLVM/clang 22.1.8 与 ShellCheck 0.11.0；未修改系统 PATH、注册表或 WSL。wrapper 已按真实 `cuvslam.h` 将 metrics event ref 时间戳修正为 `int64_t`，并通过负值 JSON 保真、真实头文件 lifecycle/API 失败/高频限流 harness、严格 JSON、ASan+UBSan、Clang Static Analyzer、gtest 语法、ShellCheck、Bash 语法和 DWB 33 项回归。六项 `Request changes` 逐条复审通过。本机补丁现已具备进入 Jetson 隔离备份/构建的条件，但尚未部署；机器人路线继续冻结。

### Current Update — 2026-08-09 cuVSLAM 原生回环诊断出口实现启动
用户要求继续。新增 Phase 39：在 Isaac ROS Visual SLAM wrapper 内实现默认关闭、与 RViz/PointCloud/rosbag 解耦的原生诊断出口；采样 `CUVSLAM_SlamMetrics`，仅在 LC/PGO 事件变化时抓取原生 pose graph 并记录新增边的 ID、transform、covariance。先审计远端源码与工作区，随后构建和静止负载 A/B；不移动机器人，不执行第三次短环、半程或完整路线。

### Current Update — 2026-08-09 Phase 39 首版审查 Request changes
本机首版 exporter 暂停部署。审查确认六项阻断问题：metrics 事件时间戳未参与判定、PGO 无 edge ID 变化时图不落盘、异步图更新缺少事件后窗口、landmark 计数变化可把全图读取放大到约 30Hz、截断图污染 baseline/diff、`node_distance_m` 非有限值破坏 JSON。先在本机完成事件窗口、硬限频、强制事件快照、截断隔离、完整 JSON 守卫和单测；在再次审查通过前不得复制到 Jetson。

### Phase 39: cuVSLAM 原生 LC/PGO 与 edge diff exporter
- **Status:** complete
- [x] 核对 Jetson Isaac ROS 源码工作区状态、构建入口、回调/销毁线程模型与既有测试约定。
- [x] 设计并实现默认关闭的 diagnostics 参数与事件驱动 helper，保持现有 visualization=false 生产路径不变。
- [x] 输出可机器解析的 metrics、原生节点/边与新增 edge diff，覆盖异常、去重、终止快照和文件落盘边界。
- [x] 通过 Request changes 复审：独立事件不合并、事件后有界双快照、全图读取硬限频、PGO 无 edge diff 仍落完整图、截断不更新 baseline、所有浮点 JSON 合法。
- [x] 完成代码审查、格式/静态检查、单元测试和 Jetson 隔离构建；保留远端原文件备份与补丁。
- [x] 仅在空闲门禁通过后执行静止无运动负载 A/B，确认不新增 frame delta；未进入路线测试。
- [x] 更新 runbook/PWF；exporter 具备下一次诊断路线的低负载采集条件，路线继续等待用户决定。

### Phase 39 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 整包 `scp` 源码镜像包含测试 rosbag，60 秒内未完成并超时 | 1 | 远端未修改；保留独立临时目录，只核对/补取实现所需的文本文件，不再传输整包 |
| DWB launcher/test 首轮并行 `rg` 的 PowerShell 命令字符串因嵌套 `$`/引号未闭合 | 1 | 命令未执行且文件未修改；停止复杂内联正则，改用简单固定模式分开检索 |
| 本机 C++ 工具链并行探测因 `clang++/g++/cl` 全部缺失返回非零 | 1 | 已确认仅有 CMake/Ninja、无编译器或 clang-format；不重复探测，不以未编译首版部署 Jetson，先完成本机静态/契约复审 |
| WSL 编译器 fallback 返回“未安装 Linux 发行版”并以 UTF-16 控制台文本显示乱码 | 1 | 未安装/修改 WSL；停止本机真实 C++ 编译尝试，明确保留构建未验证状态且不部署 Jetson |
| `winget install LLVM.LLVM --scope user` 无适用安装器 | 1 | 系统未安装 LLVM；不重复该命令，改用无需管理员的便携 C++ 工具链 |
| 默认机器范围 `winget install LLVM.LLVM` 静默运行约两分钟无输出/不结束 | 1 | 主动终止单个 winget 会话；确认无 LLVM 文件和残留 installer 进程，改用仓库 tmp 内便携 llvm-mingw ZIP |
| standalone 首次编译把 fake graph 的 `std::array` 直接传给 vector-only 纯函数 | 1 | 产品 helper 未报错；仅将 harness fake edges 显式转换为 `std::vector` 后重新编译 |
| standalone EXE 首次运行未临时加入 llvm-mingw DLL 目录，静默退出 1 | 1 | EXE 已成功生成；仅在该命令进程内 prepend 便携 `bin` 后运行通过，不修改全局 PATH |
| clang-format dry-run 在镜像缺少 `.clang-format` 时用默认 LLVM 风格，将上游既有文件几乎全量判违规 | 1 | 不执行批量格式化，避免上游格式 churn；改用既有排版的长行/差异检查，正式环境后续用包自带 lint 约定 |
| ShellCheck latest release 首轮按 `x86_64-w64-mingw32.zip` 过滤未找到资产 | 1 | 未下载文件；改为先结构化列出 release 资产名，再选择实际 Windows x86_64 包 |
| ShellCheck 首次验证硬编码了错误的双层解压路径 | 1 | launcher 未执行；改为从已校验解压目录动态定位唯一 `shellcheck.exe`，并与 Python 测试分开运行 |
| ASan/UBSan 首次命令的逗号参数被 PowerShell 解析为列表 | 1 | 编译器未执行、源码未变；改用 PowerShell 参数数组传递 sanitizer flag |
| 两次 `scp` 把远端 Git 仓库根误当成 package 根，默认与 `-O` 均返回路径不存在 | 2 | 只读 `find` 确认真实包根多一层 `/isaac_ros_visual_slam/isaac_ros_visual_slam`；本地仅有空目录，改用准确路径下载 |
| 真实 `cuvslam.h` lifecycle harness 在 Windows 因 `CUVSLAM_API=dllimport` 与 fake 定义冲突，且 stub 错误码名不存在 | 1 | 产品 helper/gtest 对真实头文件的 `-Werror -fsyntax-only` 已通过；读取宏/状态定义后仅调整本地 harness 编译开关和 fake 返回码 |
| 记录上一错误时 `apply_patch` 使用了已被修正的旧表格行作为锚点 | 1 | PWF 未变化；读取 Phase 39 Errors 当前片段后用有效尾行增量追加 |
| 调整真实头文件 harness 时把 harness 函数锚点误放进 stub 文件补丁 | 1 | 两个测试文件均未变化；拆成各自文件的准确增量补丁 |
| lint 约定检查读取了不存在的示例 test/test_pose_cache.cpp | 1 | 命令其余只读结果有效；改以存在的 posegraph_vis_helper.cpp 和 CMake/package.xml 确认完整许可证与 ament lint 约定 |
| 许可证补丁的 JavaScript 模板字符串被 PWF 行内反引号提前终止 | 1 | apply_patch 未执行、文件未变；去除包装层反引号后重新应用 |
| 许可证补丁模板插值的后续行缺少 patch 加号 | 1 | apply_patch 校验失败、文件未变；改用显式逐行补丁 |
| 收尾检索误把 wrapper 包根下的源码目录写成 `isaac_ros_visual_slam/` | 1 | 只读 `rg` 部分返回；用 `rg --files` 确认实际目录为 `src/`、`include/` 与 `test/`，不重复错误路径 |
| 预验证并行批次包含 `git diff --no-index`，发现预期差异后退出 1 并中断结果汇总 | 1 | 文件未修改；不把有差异即非零的命令混入并行汇总，后续独立检查并显式解释退出码 |
| 负时间戳端到端 harness 补丁使用了不匹配的断言文本锚点 | 1 | apply_patch 原子校验失败、文件未变；读取准确函数片段后分别在 Reset 与 final 断言处增量修改 |
| Jetson 构建容器在 source ROS setup 前启用 `set -u`，因 `AMENT_TRACE_SETUP_FILES` 未定义立即退出 | 1 | 未进入编译；setup 阶段改用 `set -eo pipefail`，不对 ROS 环境脚本启用 nounset |
| colcon 默认递归扫描工作区 `tmp` 中的 backup/staging，报告三个同名 `isaac_ros_visual_slam` package | 1 | 未进入编译；保留备份，构建显式使用 `--base-paths /workspaces/isaac_ros-dev/src`，真实构建随后通过 |
| 性能脚本经 `sudo -n` 执行时需要密码 | 1 | 未改变频率；确认既有 root SSH 仍可用后，以 root 再次校验脚本 SHA-256 并只执行该已验证脚本，锁频门禁通过 |
| 首次 A 轮用 launcher 就绪文本而非 CreateTracker 日志做 readiness，且窗口提取包含关机行、告警正则漏匹配原生 Delta 文本 | 1 | 该轮作废、不进入 A/B 结论；改为等待 `CUVSLAM_CreateTracker()` 日志落盘后再稳定 10 秒，按 baseline/end 行号精确提取并匹配 `Delta between current and previous frame` |

### Current Update — 2026-08-09 cuVSLAM 回环边离线检查完成
Phase 38 判定为“现有证据不足”，不能把最终两轮写成“确认无回环边”或“确认错误回环边”。最终两轮均关闭 `enable_slam_visualization`，源码因此关闭 `enable_reading_slam_internals`；GetAllPoses 只返回 poses，VisualSlamStatus 无 LC 字段，现有日志也没有 bag、Marker、原生 metrics/edge/database/debug dump。6 个旧 visualization=true 轮次曾产生 `LL_LOOP_CLOSURE` 数据层更新，只能证明 cuVSLAM 在其他运行中触发过 LC-layer，不能证明最终短环有有效起终点约束。下一次最小诊断应先实现 wrapper 内事件驱动 exporter：低成本采样 `CUVSLAM_SlamMetrics`，仅在 LC/PGO 状态变化时抓取原生 pose graph 并输出新增边的节点 ID、transform、covariance；当前不执行新路线。

### Current Update — 2026-08-09 cuVSLAM 回环边离线检查启动
用户认为现场视角与物体丰富度没有明显问题，要求开始检查 cuVSLAM 是否建立有效起终点回环边。新增 Phase 38，全程只读离线：盘点两轮最终验收及历史可视化日志，确认 `pose_graph_edges/edges2`、`loop_closure_cloud` 的消息类型、保存状态与时间覆盖；若已有边数据则按 tracking 同窗分析跨时段边，若没有则明确现有证据边界和最小无运动/被动采集需求。冻结半程/完整路线，不启动 Jetson 软件栈、不移动机器人。

### Phase 38: cuVSLAM 有效回环边离线检查
- **Status:** complete
- [x] 盘点最终两轮及历史日志中 pose graph edge、loop closure cloud、topic/type 快照与 rosbag/CSV/JSON 证据。
- [x] 核对 launcher 中相关可视化 topic 的启用条件、消息类型和现有采集方式。
- [x] 确认最终两轮不存在 edge 载荷，故无法执行跨时段边统计；未用 pose 轨迹伪造边结论。
- [x] 证明现有 GetAllPoses 只能给优化 pose、不能反推出边集合，并设计最低负载的下一次被动诊断出口。
- [x] 更新 PWF，给出“现有证据不足”的证据化判定；未做第三次路线运动。

### Phase 38 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Jetson 源码/日志首轮搜索调用 `rg`，远端返回 `rg: command not found` | 1 | 未修改远端；改用 Jetson 现有的 `grep/find` 做等价只读搜索 |
| 同时递归扫描全部历史日志根目录在 30 秒内超时，导致该批并行结果未返回 | 1 | 缩小为最终两轮、已知完整路线轮及包含可视化/recorder 迹象的候选目录，分批读取 |
| SSH 参数层剥离 `grep` 正则引号，竖线后的模式被远端 shell 当成命令 | 1 | 不再传嵌套正则参数；改用 PowerShell here-string 经标准输入交给远端 `bash -s` |
| PowerShell here-string/原生管道在远端脚本参数尾部保留或重新编码 `\r`，两次批量读取被 CRLF 干扰 | 2 | 停止直接传文本，改为本机 UTF-8 base64 编码、远端 `base64 -d | bash -s` |

### Current Update — 2026-08-09 GetAllPoses 同窗分析工具修复完成
DWB worktree 的 `scripts/cuvslam_get_all_poses_once.py` 已显式将当前 cuVSLAM pose stamp `×1000` 对齐 tracking UNIX 秒，同时保留 raw stamp 与 scale；新增 tracking 起止 JSON 筛选、同窗路径/XY 闭环误差与误差率、yaw wrap 后角差，并让判定优先使用同窗 summary。第二轮真实日志离线复算得到 `5126` poses、`9.900975482m`、`0.356863406m`、`3.604326%`、`0.459030deg`，与用户校正一致。runbook 已冻结半程/完整路线并要求同窗字段；本机和 Jetson 测试均 `12/12`、编译/help/diff check 与四文件哈希通过。部署备份位于 Jetson `tmp/cuvslam_window_metrics_fix_20260809/`；Docker 和相关进程保持为空，未再次调用服务或移动机器人。

### Current Update — 2026-08-09 同窗指标校正与时间戳修复启动
用户确认本轮没有 Z 方向姿态变化，并按时间戳将 tracking 与 GetAllPoses 对齐到同一运动窗口：tracking XY/yaw 为 `0.031289m/1.398deg`，同窗后端为 `0.356863m/0.459deg`，同窗路径 `9.900975m`，XY 误差率 `3.604%`。准确结论修正为“后端改善 yaw，但把 XY 闭环从约 `3.1cm` 恶化到约 `35.7cm`”；此前整图首末点 `0.358549m/9.908336m` 只作为全图统计，不再作为同窗主指标。GetAllPoses pose stamp 原始值约为 tracking UNIX 秒的 `1/1000`，分析前必须 `×1000`。新增 Phase 37 修复工具并固化同窗回归；冻结 cuVSLAM 半程/完整建图，不做第三次短环。

### Phase 37: GetAllPoses 时间戳归一化与同窗指标
- **Status:** complete
- [x] 在 `cuvslam_get_all_poses_once.py` 中显式归一化 GetAllPoses 时间戳，并记录所用 scale。
- [x] 支持按 tracking 起止 JSON 筛选同一运动窗口，输出同窗路径、XY 闭环误差/误差率和 yaw 差。
- [x] 增加单位、窗口边界、yaw wrap 和报告字段的回归测试。
- [x] 用现有第二轮 CSV/JSON 离线复算，确认结果与 `0.356863m/0.459deg/9.900975m` 一致。
- [x] 更新 runbook/PWF，验证本机和 Jetson 测试、Python 编译、CLI help、diff check 与部署哈希；未启动 Jetson 软件栈或移动机器人。

### Phase 37 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 远端 `awk` 离线同窗复算的 printf 格式字符串被 SSH 引号层剥离，返回语法错误 | 1 | 命令只读且未修改文件；停止使用嵌套 awk，改由 Python 工具的结构化 CSV/JSON 解析和单元测试复算 |
| 本机真实日志复算的 Python `-c` 字符串引号被 PowerShell 剥离，返回 `NameError` | 1 | 临时文件已清理且源码/日志未受影响；改用 here-string 经标准输入传递 Python 程序 |
| Jetson 部署前组合空闲门禁返回空输出但退出码 1，无法判定条件分支 | 1 | 未部署；改为独立读取 Docker 与全量进程列表并在本机过滤，两者均为空后才继续 |
| 远端备份时 `tests/test_cuvslam_get_odometry_once.py` 原目标不存在，且末尾 `printf` 掩盖该项 `cp` 非零 | 1 | 其余三个既有目标备份成功；记录 absent-before 标记，随后以远端哈希、测试和编译核验四个部署目标 |

### Current Update — 2026-08-09 最终遥控短闭环确认性复测仍未通过
以相同最终低负载配置完成第二个独立冷启动 `short`。运动窗口前后 `launch.log` 保持 `59` 行，无新增 tracking lost/frame delta；tracking 前端为 `xy_drift_m=0.031289m`、`yaw_drift_deg=1.398deg`。本会话唯一一次 `GetAllPoses` 成功，返回 `11677` 个优化位姿、`xy_path_length_m=9.908336m`、`xy_closure_error_m=0.358549m`，超过 `<0.20m` 且约为 tracking XY 漂移的 `11.46x`，后端再次没有形成全局纠偏。两次独立短闭环的后端归一化误差分别为 `3.6833%` 和 `3.6187%`，路线长度虽不同但误差比例近似重复。查询后出现 `99.991/133.328ms` 两次负载断帧，不属于运动窗口。未保存地图、未进入半程；目标容器、launcher、残留 Host ROS daemon 与全部相关进程已清理，日志保留在 `/home/superwfx666/cuvslam_final_acceptance_logs/20260808-231407/`。

### Current Update — 2026-08-09 最终遥控短闭环确认性复测启动
用户要求在上一轮后端 `xy_closure_error_m=0.257547m` 失败后重新测试一次。本轮新增 Phase 36，仅以与上一轮完全相同的 `640x360@30fps`、六核/GPU 锁频、关闭 GNOME 设置及全部低负载约束执行一个独立冷启动 `short` 复测；仍使用运动前后各一次 tracking 快照和停稳后唯一一次 `GetAllPoses`，硬门槛保持 `<0.20m`。本轮不进入半程、不保存地图；若本轮通过，只能说明两轮结果存在波动，不能覆盖上一轮失败。

### Phase 36: 最终遥控短闭环确认性复测
- **Status:** complete
- [x] 完成 Jetson 只读预检：D455、六核/GPU 锁频、Docker/相关进程为空、GNOME 设置关闭。
- [x] 以最终低负载配置独立冷启动 `short`，核验运行时配置并抓取 tracking 起点。
- [x] 用户确认物理起点、站稳、路线净空、遥控器回中和急停就位后，低速完成短闭环并停稳。
- [x] 抓取 tracking 终点并比较；停稳后严格只调用一次 `GetAllPoses`。
- [x] 按 `<0.20m`、运动窗口无 tracking lost/frame delta 和前后端关系判定复测结果，清理全部目标进程并保留日志（后端 `0.358549m`，本级失败）。

### Phase 36 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 首组 SSH 预检的远端管道/正则被 PowerShell 与 SSH 引号拆分，出现 `command not found`，部分输出不可用 | 1 | 命令只读且未改变 Jetson；停止使用内联拼接，改用 PowerShell 参数数组把完整远端脚本作为单一参数传递 |
| 容器就绪检查的 `docker inspect` 模板中 `"/logs"` 引号在远端解析前丢失，返回 template parsing error | 1 | 不重复该模板；改为列出全部挂载并直接从容器内 `/logs` 读取运行配置与日志 |
| 首次 tracking 起点抓取的嵌套 `bash -lc` 双引号被 SSH 层剥离，ROS setup 只收到空 `source` 参数 | 1 | 起点文件和运动标记均未生成；改用单引号把完整容器内命令封装为一个 `bash -lc` 参数后重试 |

### Current Update — 2026-08-09 最终遥控短闭环未通过
在关闭 `gnome-control-center`、`640x360@30fps`、六核/GPU 锁频及全部低负载约束下完成正式独立冷启动短闭环。用户确认物理回到标记起点和原始朝向；期间机器人从趴下变为起立，因此 tracking `dz=0.239906m` 是真实高度变化，不计作平面漂移。前端 tracking 为 `xy_drift_m=0.134938m`、`yaw_drift_deg=13.486deg`。停稳后本会话唯一一次 `GetAllPoses` 成功，返回 `11283` 个优化位姿、`xy_path_length_m=6.992375m`、`xy_closure_error_m=0.257547m`，超过 `<0.20m` 硬门槛，且未比 tracking XY 误差更小，不能证明后端形成全局纠偏。运动窗口无新增 tracking lost/frame delta；唯一新增 `133.29ms` frame delta 出现在 `GetAllPoses` 后约 `3.42s`。本级判失败，未调用 `save_map`/`load_map_and_localize`，不进入半程；目标容器、launcher 和相关机器人进程已清理为空，日志保留在 `/home/superwfx666/cuvslam_final_acceptance_logs/20260808-225659/`。

### Current Update — 2026-08-08 `30.5s` 周期触发源单变量 A/B 完成
仅终止当前用户的 `gnome-control-center`，保留 `iio-sensor-proxy`、`systemd-timedated` 正常生命周期及其余 cuVSLAM 配置不变；无快照、ROS 订阅、recorder、daemon 或系统探针的 `130s` 稳定窗口内零新增原生日志，原先约 `30.5s` 周期 frame delta 消失。窗口后一次全量 `journalctl` 读取在 Docker stop 之前触发 `167.64ms` 瞬态，说明 GNOME 设置是已确认的周期触发源，而底层机制仍指向系统调度/资源竞争，并非 timedated 独占或历史运动漂移的完整根因。最终 runbook 已增加 GNOME 关闭预检和运行期禁止重型系统日志扫描的门禁，并部署到 Jetson；真实短闭环尚未开始。

### Current Update — 2026-08-08 GNOME 设置周期触发源 A/B 确认
核验 PID `3973` 为用户 `superwfx666` 的 `gnome-control-center` 后，仅发送一次 `SIGTERM` 正常关闭；`iio-sensor-proxy` 保持运行，未停止或修改 `systemd-timedated`。随后以与失败轮完全相同的最终低负载配置冷启动，tracker 稳定后等待 10 秒并进入 130 秒零观察负载窗口；`launch.log` 从 59 行保持到 59 行，没有新增 frame delta、tracking lost 或其他日志，确认关闭 GNOME 设置后 `30.5s` 周期断档消失，故 `gnome-control-center` 是当前环境的周期触发源。窗口结束后的全量 `journalctl` 扫描约 4 秒后又出现一次 `167.64ms` gap，发生在 Docker `SIGTERM` 之前，说明底层仍对系统查询/调度负载敏感，不能把 timedated 独占机制当作已证明根因。runbook 已增加 GNOME 关闭守卫和运行期禁用 journalctl 的约束并同步 Jetson；容器与相关进程已清理，GNOME 设置保持关闭。

### Current Update — 2026-08-08 cuVSLAM `30.5s` 周期断档复测确认
使用与上一轮完全相同的最终 `640x360@30fps` 低负载配置再次冷启动，GPU warm-up 后连续观察原生 launch log，期间不运行 tracking 快照、ROS 订阅、topic/rate checks、recorder、daemon 或系统探针。原生日志再次出现 `166.69/100.00/100.00+66.66/133.36/133.37/100.02ms` frame delta，连续主事件间隔约 `30.44/30.51/30.51/30.51/30.44s`，确认 `30.5s` 问题稳定复现且不是快照工具的观察者效应。本轮未出现 D455 `Motion Module failure`，说明该启动告警不是周期断档的必要条件。未调用服务或移动机器人，已清理全部容器和相关进程；短闭环继续禁止。

### Current Update — 2026-08-08 cuVSLAM 最终配置无运动冒烟未通过
最终 runbook 与轻量 tracking 快照工具已同步到 Jetson，远端/本机 SHA-256 一致，远端 `py_compile` 与 CLI help 通过。随后以最终 `640x360@30fps`、六核/GPU 锁频、关闭 visualization/landmarks/observations、recorder、topic/rate checks、RViz 和 ROS daemon 的配置冷启动无运动 smoke。两条 tracking odometry 相隔 `22.005s`，契约为 `odom -> base_link`，XY 漂移仅 `3.50e-6m`、yaw 漂移 `0.000101deg`；但 cuVSLAM 原生日志在稳定窗口约每 `30.5s` 出现 `66.64-167.08ms` 图像 frame delta，故整体运动门禁失败。未调用 `GetAllPoses`、`save_map` 或任何运动/导航出口；容器与相关进程已清理为空，真实短闭环禁止启动。

### Current Update — 2026-08-08 cuVSLAM 最终遥控建图验收重构
将下一轮真机建图固定为有判别力的三级独立冷启动验收：`640x360@30fps`、六核锁频、关闭 SLAM visualization/landmarks/observations、recorder、topic/rate checks 与 ROS daemon，不启动 Nav2、bridge、感知或重型探针。每一级均在物理标记起点和原始朝向闭环，运动前后各抓取一次轻量 tracking odometry，停稳后只调用一次 `GetAllPoses`；短闭环通过后才能新会话执行半程，半程通过后才能新会话执行完整路线。完整路线后端闭环误差必须 `<0.20m` 才允许 `save_map`，随后完全重启 cuVSLAM 并验证 `load_map_and_localize`。runbook、轻量快照工具、本地测试和 Jetson 只读预检均已完成；当前 D455 枚举、Docker/相关进程为空、`MODE_20W_6CORE`、CPU 六核与 GPU 锁频，尚未启动机器人软件栈或执行真实短闭环。

### Current Update — 2026-08-08 ROS 到 cuVSLAM 静止分层定位完成
已暂停 SLAM 换型，未更换 Hub、线缆或固件。Jetson 固定为 `MODE_20W_6CORE`（ID 8），六核及 CPU/GPU 频率门禁通过。Wrapper-only 与 Wrapper + cuVSLAM 低负载各完成 `120 秒 x 3` 且全部通过；加入 1 秒重型系统快照后，第三轮在 ROS metadata 与 cuVSLAM 同窗出现 `266.497ms` 断档，左右 IR hardware counter 各缺 5，故第一处丢帧位于 cuVSLAM 内部 odometry 计算之前。故障窗 CPU 六核负载高、GPU 仅 `1%`，xHCI IRQ 平稳而 UDP `RcvbufErrors` 突增，最强证据指向 CPU 调度尖峰使 Wrapper/发布链停顿并叠加 DDS 接收队列压力。仅把重型系统快照请求间隔从 `1s` 调为 `5s` 后，相同静止配置连续 `120 秒 x 3` 全部通过：IR hardware counter 零跳号、IMU 最大间隔 `8.52/8.15/8.98ms`、odometry 连续且每个图像区间均有 IMU。静止门禁完成；手持运动和机器狗低速短环仍须现场确认后另行执行。

### Current Update — 2026-08-08 SLAM 换型评审
用户提供的六核 30fps 静止输入门禁仍失败：图像/odom 最大约 `166.6ms`、IMU 最大约 `105.0ms`，探针按 `header.stamp` 统计；左右眼 `33.4ms` 是 CameraInfo 时间戳最近邻风险，不等同于已证明的硬件曝光异步。当前建议冻结 cuVSLAM 完整路线主线，保留其低负载配置作对照；优先验证 RTAB-Map Foxy `0.21.1` RGB-D localization + Lite3 腿部里程计/机身 IMU EKF。RTAB-Map 当前主线最低要求 Humble，ORB-SLAM3 官方 ROS 示例为 Melodic，二者都不是即插即用替换。下一步为不改现有生产栈的短周期 A/B：固化 Jetson 实际脚本哈希 → 构建/启动 RTAB-Map Foxy 隔离环境 → 静止输入、手持运动、低速短环三道门禁；未通过前不接 Nav2/不移动机器狗。

## Current Phase
### Phase 35: ROS 到 cuVSLAM 第一处丢帧点定位
- **Status:** complete
- [x] 增加 ROS 上游只读探针：同时记录 `/camera/infra1`、`/camera/infra2`、`/camera/imu` 的 header 时间戳、主机到达时间，以及 RealSense metadata 中的硬件 Frame Counter；不做图像转换。
- [x] 完成 Wrapper-only 静止 A/B：120 秒 x 3 轮。
- [x] 完成 Wrapper + cuVSLAM 低负载静止 A/B：关闭 visualization、recorder、ROS CLI 探针，120 秒 x 3 轮。
- [x] 在上一组基础上同步记录 CPU 线程、xHCI/USB IRQ、DDS/订阅队列可观测指标和 tegrastats，120 秒 x 3 轮。
- [x] 按第一处硬件跳号或时间断档分类：ROS metadata、DDS/订阅入口、cuVSLAM odometry 输出。
- [x] 仅在定位后实施一个变量的修复，并重复同一验收窗口。
- [x] 连续三轮满足：左右 IR 无硬件跳号、IMU 无成簇缺样、图像间隔不超过 2.5x、每个图像区间都有 IMU；通过后才允许手持运动和机器狗低速短环。

### Phase 35 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 独立镜像接口查询错误加载未挂载的 `/workspaces/isaac_ros-dev/install/setup.bash` | 1 | 改用镜像内 `/opt/ros/humble`；确认 `Metadata` 消息为 `header + json_data` |
| 首次 Wrapper-only Docker 命令被 SSH 外层引号拆开，`ros2` 未加载 | 1 | 容器自动退出删除；改用 PowerShell 参数数组传递完整远端命令，随后 Wrapper 正常启动 |
| ROS CLI daemon 无法发现相机 topic 且异常占用 CPU | 2 | 停止使用 ROS CLI 做正式探针；改用直接 rclpy/rclcpp 订阅并清理本轮 daemon |
| Python 完整 Image + metadata 单线程/多线程探针自身积压，IMU 仅约 79-169 Hz | 3 | 判定为观察者效应，不把结果归因 Wrapper；实现原生 C++ 探针，10 秒对照恢复 `199.65Hz` 并通过门禁 |
| C++ 首次构建因 `111@localhost` 不满足 ROS package 邮箱校验失败 | 1 | 改为合法占位邮箱后构建成功；源码编译无错误 |
| C++ 构建 SSH 命令超过 120 秒本地时限 | 1 | 单次检查确认远端产物已构建成功，不重复全量构建 |
| Tailscale SSH 要求额外网页登录检查，后续同步/正式 A/B 暂停 | 2 | 等待用户完成最新认证链接；当前仅有静止 Wrapper-only 容器，无 cuVSLAM/Nav2/运动进程 |
| launcher 收到 `SIGTERM` 后仍等待 `docker logs -f`，trap 未立即执行 | 1 | 精确终止本轮日志跟随子 PID `11289`，launcher 随即执行 EXIT trap 并删除目标容器；最终相关进程与 Docker 均为空 |

### Phase 34: D455 直连帧号缺口复现与 USB 运行时电源 A/B
- **Status:** complete
- [x] 固化低开销 pyrealsense2 直连基线：每个流记录硬件 Frame Number、设备时间戳与主机单调时钟。
- [x] 只读核对 D455 与上游 USB Hub 的拓扑、runtime-PM、LPM、内核 USB/UVC 错误及系统调度信号。
- [x] 以推流期 runtime-PM 连续采样完成 autosuspend 机制核验；`auto` 基线无故障且 140 次状态均为 active，故不执行无辨识力的 `control=on` 写入。
- [x] 当前无法复现 22 帧缺口，不进入供电 Hub、线缆或固件变更；需先取得原始失败命令/日志与当前基线做条件差分。

### Current Update — 2026-08-07 22:37 六核 30fps 静止输入探针仍未通过
新启动的低负载 `cuvslam_gui_20260807-223609` 已完成 GPU warm-up；容器内只运行只读输入时序探针，未启动 Nav2、运动出口或发送命令。20 秒窗口：IR1 `29.799Hz`、IR2 `29.799Hz`、odometry `29.779Hz`，三者均出现一次 `166.661ms` 帧间隔；IMU `199.311Hz`，最大 `104.990ms`、3 次超过 `2.5x`、估计缺失 42 个样本；8 个图像区间没有 IMU。判定 `clustered_gaps`，不满足运动门禁。已停止精确容器并复核 Docker、启动 PID、导航/运动/recorder 均为空；Phase 33 继续 `in_progress`。

### Current Update — 2026-08-07 22:22 Jetson 性能脚本已升级并部署
已核对用户提供的 `jetson_clocks --show`：当前 `MODE_20W_2CORE` 的两颗在线 CPU 均锁定 `1.9072GHz`，GPU `1.10925GHz`、EMC `1.866GHz`，DLA/PVA 也锁在当前模式上限。已在主仓库新增 `scripts/jetson_max_performance.sh`，默认选择 `MODE_20W_6CORE` 以保留六核最大并行吞吐，`--cpu-peak` 显式选择 `MODE_20W_2CORE` 最高配置 CPU 频率；脚本还调用 `jetson_clocks --fan` 并打印验证状态，不启动 ROS 或相机。Jetson 桌面原脚本已备份到 `Desktop/jetson_max_performance.sh.bak_20260807_2215`，新脚本已同步、设为可执行，远端 `bash -n` 与本机哈希校验通过。未改变当前 2-core 模式，未启动容器或发送运动命令。

### Session Errors — 2026-08-07 22:22
| Error | Attempt | Resolution |
|---|---:|---|
| 首次 `scp` 在 DWB worktree 查找主仓库脚本，返回本地文件不存在 | 1 | 使用主仓库绝对路径重传；远端文件随后通过 `bash -n`、可执行位和 SHA-256 校验 |

### Current Update — 2026-08-07 22:09 Jetson 电源模式上限已核对
用户提供的 `jetson_clocks --show` 证明当前锁频确实生效，但 `MODE_20W_6CORE` 配置本身将 6 个 CPU 的 `MAX_FREQ` 固定为 `1420800`。远端 `nvpmodel -p --verbose` 显示可用的 `MODE_20W_2CORE`（ID `6`）可将两颗 CPU 上限设为 `1907200`，GPU/EMC 仍为 `1109250000/1866000000`；`MODE_20W_4CORE` 和当前 6-core 均为 `1420800`。切换到 2-core 会减少并行 CPU，属于需用户确认的系统功耗/调度变量；当前 Docker/ROS/Nav2/运动环境为空，未执行切换或运动。

### Current Update — 2026-08-07 22:02 30fps 低负载三窗口仍有偶发丢帧，未进入运动
关闭全部 visualization、recorder、startup topic checks 和 rate probes 后，30fps 低负载连续静止窗口仍不稳定：窗口 1 IR/odom `29.995Hz` 且各无图像大间隔，IMU `199.66Hz` 但有一次 `12.55ms` 缺口；窗口 2 IR/odom `29.83Hz`、各一次 `133.35ms` 缺口，IMU `199.45Hz`、最大 `69.57ms`；窗口 3 IR/odom `29.78Hz`、各一次 `166.70ms` 缺口，IMU `199.50Hz`、最大 `88.68ms`。三次均每个图像区间有 IMU，但不能满足此前严格的无 `>2.5x` 大间隔门禁。当前 Jetson 为 `MODE_20W_6CORE`、CPU 约 `1.4208GHz`；`sudo -n jetson_clocks --show` 因需要密码未执行，也未改变功耗配置。已停止精确容器和启动 PID，Docker/ROS/Nav2/运动进程均为空。Phase 33 保持 `in_progress`，未发送运动命令。

### Session Errors — 2026-08-07 22:02
| Error | Attempt | Resolution |
|---|---:|---|
| `sudo -n jetson_clocks --show` 需要密码，无法读取锁频状态 | 1 | 不重复提权、不修改电源模式；改用无需提权的 `nvpmodel -q`，确认 `MODE_20W_6CORE` 并记录频率/负载 |

### Current Update — 2026-08-07 21:48 30fps + SLAM 图诊断发布静止复测未通过
使用 `CUVSLAM_CAMERA_PROFILE=640x360x30`、`CUVSLAM_IMAGE_JITTER_THRESHOLD_MS=40.0` 并开启 `ENABLE_SLAM_VISUALIZATION=true` 时，首个 20 秒窗口 IR/odom 出现一次约 `133ms` 缺口，IMU `195.93Hz`、最大 `44.78ms`；稳定复测仍出现 IR/odom 一次约 `133ms` 缺口、IMU `199.41Hz` 但最大 `53.49ms`，立体同步有一次 `33ms` 偏差。该额外图诊断负载不能通过静止输入门禁，不能在此配置下移动。下一步停止精确容器，关闭所有 cuVSLAM visualization，复测此前通过的低负载 30fps 基线；Phase 33 保持 `in_progress`。

### Current Update — 2026-08-07 19:46 Stage D 30fps 运动验收前软件收尾完成
`STARTUP_RATE_PROBES` 已确认默认关闭，避免启动阶段串行 `ros2 topic hz` 探针继续占用 Jetson 调度余量；需要诊断时仍可显式开启。本机相关测试 `11/11`、三个 Python 文件编译和 `git diff --check` 通过；Jetson 同步后原生 `bash -n` 与相关测试 `8/8` 通过，两个同步文件 SHA-256 与本机一致。远端旧版本备份在 `tmp/startup_rate_probes_backup_20260807_2005/`。最终 Docker 为空，无 ROS、cuVSLAM、Nav2、bridge、arbiter、motion sender 或残留日志探针进程。本轮没有启动机器人软件栈或发送运动命令。Phase 33 保持 `in_progress`；下一步等待现场再次确认官方起点、站稳、短环路线净空和急停就位，再启动 30fps 低速短环运动验收。

### Session Errors — 2026-08-07 19:46
| Error | Attempt | Resolution |
|---|---:|---|
| 30fps 首次启动把 `CUVSLAM_IMAGE_JITTER_THRESHOLD_MS=40` 生成成整型参数，cuVSLAM 拒绝加载要求的 double | 1 | 在机器狗保持静止时停止精确启动 PID/容器；下一次只把值改为 `40.0`，其余配置不变 |
| Windows 本机未安装可调用的 `bash`，并行本地 `bash -n` 失败且同批输出未保留 | 1 | 单独重跑 Python 验证；shell 语法改在 Jetson 原生 Bash 验证通过 |
| SSH 主机别名默认使用本机用户 `111`，被 Tailscale SSH 策略拒绝 | 1 | 显式使用 `superwfx666@superwfx666-desktop` 后连接成功，首条命令未进入 Jetson |
| 两次复合 SSH 只读检查被 PowerShell/SSH 拼接破坏，并暴露一组早先遗留的无文件输入 `grep/head` | 2 | 停止复合检查，改用独立远端命令；精确终止遗留 PID `10634-10636` 并确认无残留 |
| 并行进程查询以“无匹配”退出码 1，导致同批验证输出被包装器丢弃 | 1 | 将语法/测试/哈希与进程检查分组重跑，进程查询加入必然存在的 `systemd` 基准项后取得可审计输出 |

### Current Update — 2026-08-07 19:37 Stage D 无运动输入时序诊断完成
已完成 D455 → RealSense ROS → cuVSLAM 的分层无运动 A/B，全程未启动 Nav2、cmd_vel bridge/arbiter、final bridge 或 motion sender。librealsense 直连原始 IMU 为 accel `202.66Hz`、gyro `199.67Hz`，两路帧号缺口均为 0；仅 RealSense ROS wrapper 时 IR `59.81Hz`、IMU `199.66Hz`。加入 cuVSLAM 后，60fps 多个 20 秒窗口的 IMU 仅约 `178-196Hz`，纯 cuVSLAM、无 recorder/无 ROS daemon 的最终干净窗口仍为 `186.77Hz`、最大间隔 `54.98ms`；改为 30fps 后 IR/odometry 均约 `29.99Hz`、IMU `199.66Hz`、无 `>2.5x` 大间隔且每个图像区间均有 IMU。结论是 D455/USB/单独 wrapper 正常，当前 Xavier NX 上的 `640x360@60 + cuVSLAM` 组合存在稳定的处理/调度余量不足；30fps 只通过静止输入验收，尚未通过运动 tracking/闭环验收。启动脚本已修正 D455 validator 路径、缓存单次 topic list、增加诊断开关并收尾停止 ROS CLI daemon；在线 recorder 默认关闭 rolling Path 订阅并将 odometry CSV 降到 10Hz，但仍不适合作为最终闭环依据。新增 ROS 输入时序和 librealsense 原始 IMU 探针。本机 11 项相关测试、远端 8 项测试、Python 编译、`bash -n` 与 `git diff --check` 通过；扩大回归 66 项仅剩既有 `test_lite3_udp_smoke` 夹具错误。Jetson 最终 Docker 为空，无运动进程。Phase 33 保持 `in_progress`；下一步必须先做 30fps 低速短环运动验收并记录回环诊断 topic，不能直接重跑完整路线或保存地图。

### Session Errors — 2026-08-07 18:41-19:37
| Error | Attempt | Resolution |
|---|---:|---|
| Jetson host 无 `rs-enumerate-devices` | 1 | 不重复调用；改用修复后的 pyrealsense2 validator、RealSense ROS 启动日志和原始 IMU 回调探针获取设备/固件/时序证据 |
| OpenSSH 参数将 `ServerAliveInterval=5` 误作主机名 | 1 | 命令未到达 Jetson；补齐独立 `-o` 参数后运行成功 |
| PowerShell 提前展开远端 `$log`，导致读取 `/odometry_samples.csv` | 1 | 改用显式绝对远端路径，随后 CSV 与 metrics 读取成功 |
| 远端 `tests` 无 `__init__.py`，模块式 unittest 导入失败 | 1 | 改用 `unittest discover -s tests -p ...`，远端 8 项通过 |
| 原始 IMU 探针首轮遇到一次启动时间戳域切换，汇总出现超大跨度 | 1 | 增加启动 timestamp reset 裁剪并回归；复测 accel/gyro 均约 200Hz、零缺口 |
| 两次 PowerShell 嵌套引号在本机解析失败 | 2 | 两次均未发送到 Jetson；改成无嵌套双引号的精确 Docker 命令 |
| 暂停 launcher 前 topic-list 子进程 PID 已变化 | 1 | 先确认 launcher 为 `T` 状态，再终止当前精确子 PID，未影响 cuVSLAM 容器 |
| 全量本机 unittest 初次漏设 `PYTHONPATH=src` | 1 | 重跑正确环境后 66 项仅剩既有 `test_lite3_udp_smoke` mock 缺 `test_closed_yaw` |

### Current Update — 2026-08-07 Stage D 新一轮完整路线闭环判定
用户完成起点小环和正式路线并回到官方起点停稳后，本轮唯一一次 `/visual_slam/get_all_poses` 成功：返回 `33380` 个优化位姿，XY 路径 `48.045740m`，终点相对起点 `(0.816912,0.375257)`，XY 闭环误差 `0.898979m`，判定 `poor_optimized_pose_graph_return_to_start`。该结果明显超过 `<0.20m` 保存门槛，因此未调用 `save_map`，无 `save_result.json`。完整报告保留在 `/home/superwfx666/cuvslam_lite3_logs/20260807-154031/postrun_metrics_full/`；精确容器、启动 PID、recorder、运动进程和 root-owned 临时 PID 文件均已清理，Docker 为空。Phase 33 继续保持 `in_progress`。

### Current Update — 2026-08-07 Stage D 起点小环通过
用户已完成起点小环并停稳。在线轻量报告显示 odometry 路径 `7.069m`、前端 XY 回起点误差约 `0.0333m`，`robot_base_ready=True`、`base_frame_match=True`、`child_frame_id=base_link`、`all_poses_service=disabled_online`；容器 `cuvslam_gui_20260807-154031` 持续运行，最近日志未见 `Visual tracking is lost`。rolling `slam_path` 仅保留最近 1024 点，不用于最终闭环判定。已通知用户按低速、关键转角左右扫视、单向覆盖并沿场地边缘回起点的规则执行正式路线，回到官方起点停稳 10 秒后回复“路线完成”；当前未调用 GetAllPoses 或 save_map。Phase 33 继续保持 `in_progress`。

### Current Update — 2026-08-07 15:41 Stage D 新一轮建图已就绪
用户完成官方起点、站稳、路线净空、急停和 D455 支架/线缆现场确认后，已在 Jetson 冷启动新 cuVSLAM mapping 会话。当前容器为 `cuvslam_gui_20260807-154031`，日志目录为 `/home/superwfx666/cuvslam_lite3_logs/20260807-154031/`；只运行 D455、cuVSLAM 和在线轻量 recorder，两个 cuVSLAM TF 与可视化均关闭，Nav2 和全部运动出口保持关闭。就绪报告为 `robot_base_ready=True`、`base_frame_match=True`、`odom -> base_link`、`all_poses_service=disabled_online`。已通知用户先完成起点小环并停稳，回复“小环完成”后再检查轻量报告并进入正式路线。Phase 33 继续保持 `in_progress`。

### Current Update — 2026-08-07 15:38 Stage D 再次建图预检
用户要求再次协作建图。已恢复 PWF 上下文并复核中文建图规程；ByteRover MCP/CLI 在当前 Codex 会话均不可用，本轮以现有 PWF 历史为依据。Jetson `superwfx666-desktop` 在线，D455 `8086:0b5c` 已枚举，Docker 为空，未发现 Nav2、cmd_vel bridge/arbiter、final bridge、motion sender 或轻量 recorder 运行；本机 DWB 工作树与 Jetson 的启动脚本、轻量 recorder、单次 GetAllPoses 工具 SHA-256 完全一致。当前未启动 cuVSLAM、未发送运动命令，等待用户确认机器狗已在官方起点站稳、路线净空且急停就位后再冷启动新建图会话。Phase 33 继续保持 `in_progress`。

### Current Update — 2026-08-07 Stage D 第三轮真实路线闭环判定
本轮冷启动后由用户遥控完成正式路线和两次起点附近补拍。三次完整 pose graph 查询的 XY 闭环误差依次为 `0.720479m`、`0.559822m`、`0.692829m`；虽然首次补拍改善误差，但最终再次增大，未形成稳定后端闭环。全程未调用 `save_map`，最终无 `save_result.json`；cuVSLAM 容器、启动脚本和轻量 recorder 已停止，报告保留在 `/home/superwfx666/cuvslam_lite3_logs/20260807-150256/`。Phase 33 继续保持 `in_progress`。

### Current Update — 2026-08-07 13:25 Stage D 监测链本地修复
DWB 工作树已完成启动脚本与 recorder 参数错配修复：在线 recorder 明确不导入或调用 `GetAllPoses`，新增停稳后只调用一次 `/visual_slam/get_all_poses` 的独立后验工具，并在启动脚本中增加 recorder 存活门禁、旧 PID 清理和明确的 post-run 命令。新增 4 项回归、Python 编译、`bash -n`、CLI help 与 `git diff --check` 均通过；扩大回归 61 项通过，仅剩既有 `test_lite3_udp_smoke` 夹具错误。Jetson SSH 连接超时，当前尚未同步或运行，Phase 33 保持 `in_progress`。

### Current Update — 2026-08-07 13:40 Stage D 监测链 Jetson 无运动验收
Jetson 已开机并完成远端备份 `tmp/cuvslam_recorder_sync_backup_20260807_133100/`；4 个文件同步后 SHA-256 与本机一致。只启动 cuVSLAM（关闭可视化、mapping/localization=true、两个 cuVSLAM TF=false）和轻量 recorder，未启动 Nav2、cmd_vel bridge/arbiter、final bridge 或 motion sender。在线报告确认 `robot_base_ready=true`、`child_frame_id=base_link`、`all_poses_service=disabled_online`；停稳后独立工具对 `/visual_slam/get_all_poses` 成功调用 1 次，返回 15943 个 pose，输出判定为静止短轨迹 `insufficient_motion`。随后按 recorder→容器→启动脚本顺序清理，Docker、PID 和运动进程均为空，报告保留在 `/home/superwfx666/cuvslam_lite3_logs/20260807-132944/`。

### Current Update — 2026-08-07 Stage D 首轮真实地图闭环判定
机器狗物理回到起点后，Stage D 保存门禁仍未通过：当前视觉地图没有形成可接受的后端闭环，因此未调用 `save_map`。用户随后关闭 Jetson，本轮已完整结束且没有可恢复的未保存地图；明天必须从官方起点冷启动重建。Phase 33 继续保持 `in_progress`。

### Session Errors — 2026-08-07
| Error | Attempt | Resolution |
|---|---:|---|
| PWF 多文件 `apply_patch` hunk 格式错误 | 1 | 改为逐文件补丁，未改动任何业务文件 |
| 后台 `nohup` 启动脚本未响应 `SIGINT` | 1 | 对已确认的本轮 PID `15645` 发送 `SIGTERM`，脚本 trap 完成清理；随后按精确容器名兜底删除并验证无残留 |
| PowerShell 将远端校验中的 `$()` 在本机提前展开 | 1 | 该命令未到达 Jetson；改用不含命令替换的远端 `if` 条件重新执行，清理验证通过 |
| PowerShell 并行包装 OpenSSH 只读预检未返回可解析输出 | 1 | 未重复同一调用；改用已验证的 `cmd /c` 直接启动 OpenSSH，随后连通性、D455、容器、进程和文件哈希检查均成功 |
| `cmd /c` 启动字符串中的 `&&`、`<`、`&` 被本机 PowerShell 提前解析 | 1 | 解析阶段失败，Jetson 未收到命令；改用 PowerShell 参数数组把整段 Linux 命令作为单个 SSH 参数传递 |
| 后台启动 SSH 会话因远端包装 shell 保持连接而在本机超时 | 1 | 未重复启动；先只读检查发现容器与启动脚本已正常运行，再基于精确容器名继续就绪验收 |
| 起点小环 PWF 组合补丁两次使用了错误文件段或不精确锚点 | 2 | 两次补丁均校验失败且未改动文件；读取实际顶部和文件尾后改用精确、分文件增量锚点 |
| 首次后验 SSH 命令丢失 `bash -lc` 内层引号，`source` 无文件名退出 | 1 | 工具节点和服务均未调用；先用 `--help` 做无副作用环境验证，再用保留单引号的命令完成本轮唯一一次 GetAllPoses |
| 对本轮启动脚本 PID `4917` 发送 `SIGTERM` 后仍阻塞于 `docker logs -f` | 1 | 不重复信号；改为停止精确容器 `cuvslam_gui_20260807-154031`，日志跟随退出并触发脚本收尾 |
| 聚合清理复核中预期的空进程结果返回退出码 1 | 1 | 改用显式 `PRESENT/ABSENT` 状态分支，确认容器、启动 PID、运动进程和 recorder 均为空 |
| host `/tmp/cuvslam_loop_metrics_recorder.pid` 为 `root:root`，普通删除和 `sudo -n` 均失败 | 2 | 使用已有 cuVSLAM 镜像临时只挂载 `/tmp`，精确删除该单一 PID 文件；临时容器 `--rm`，最终 Docker 为空 |

### Current Update — 2026-08-04 手动测试指南同步
已将 `学习/Navigation-only 全航点手动测试.md` 更新为当前真机流程：记录显式 `nav2_yaw_takeover` 与 Jetson per-goal BT 重建补丁，强制每轮冷启动 cuVSLAM，增加 TF/costmap/arbiter/零速门禁，并改为 `nav-only-turn-validation` 通过后、人工复位并再次冷启动，才允许 `nav-only-full`。文档同步当前 9 个逻辑步骤和最新 `0.303m` yaw-only 定位漂移阻断结论。Markdown 40 个围栏成对，4 个相对源码链接均存在。

### Current Update — 2026-08-04 18:52
已确认第二段远距 `SUCCEEDED` 的直接行为是连续 goal 间复用旧 BT/path 状态。Jetson Nav2 overlay 已做最小修复：每个新 `NavigateToPose` 强制重建同名 BT，原文件备份于 `tmp/nav2_bt_force_reload_backup_20260804_1825/`；`nav2_behavior_tree`/`nav2_bt_navigator` 构建成功。无狗双目标回归中，第 1 个当前位姿目标成功，第 2 个远距目标持续收到新路径并在 5 秒后正常取消，没有再次假成功。验证栈已停止，仅保留既有 cuVSLAM 容器。下一步必须重新确认官方起点、站稳、路线净空、急停就位，然后先跑 `nav-only-turn-validation`，通过后再跑完整 `nav-only-full`。

### Current Update — 2026-08-04 18:06
现场确认四项物理门禁后已启动生产 `nav-only-full`。初始 TF `(4.722,0.729,yaw≈-3.13)`、Nav2 action server、四个实际 lifecycle、速度拓扑、arbiter=`idle`、最终三轴零速和 Lite3 `errors=0` 均通过。第 1 段 `obstacle_cross_target` 成功；第 2 个 `nav2_yaw_takeover` 的 Nav2 approach 在距 `(1.50,3.25)` 仍约 `2.519m` 时异常返回 `SUCCEEDED`，安全状态机以 `TAKEOVER_ABORTED` 拒绝接管并停止后续路线。precision lease、cancel 和 yaw-only 均未触发。已执行 `stop_all.sh`，当前无导航/bridge/arbiter/probe/motion 进程，仅保留 cuVSLAM 容器；正在离线区分 Nav2/BT 假成功与未采样到的瞬时 TF 跳变。

### Current Update — 2026-08-04 17:50
用户再次要求直接运行完整真机 Nav。远端只读预检确认 D455 已通过 USB 枚举、仅保留既有 cuVSLAM 容器、生产 `nav-only-full` 的第 2 个复合段为 `nav2_yaw_takeover(0.22m)`，未发现实际导航或运动进程。由于 `base_start` 无法识别机器人的物理场地偏移，仍等待现场明确确认“已回官方起点、已站稳、全路线净空、急停就位”；确认前不冷启动、不发送 goal。

### Current Update — 2026-08-04 17:47
用户授权完整 Nav 真机测试后，已停止 Jetson 旧导航栈，备份并同步显式接管实现，远端 Python 3.8 测试 19/19、route 描述和限定路径 `colcon build` 通过。动作前检查发现旧栈最后有效 TF 约 `(4.079,0.791,3.09)`，相对官方起点约偏移 `0.57m`；因 `base_start` 冷启动会把当前位置重置为地图起点，必须先由现场手动放回官方起点并确认全路线净空、急停就位。当前 Nav2/bridge/arbiter/probe/motion sender 均已停止，仅保留 cuVSLAM 容器，未发送 waypoint goal。

### Current Update — 2026-08-04 17:32
显式 DWB → yaw-only 接管已在本地导航 worktree 实现：生产 route 在距 `pos1_middle` `0.22m` 时先确认 precision lease 与最终 `/cmd_vel` 连续零速，再取消 Nav2 action，以接管后实时 TF 为固定 XY 锚点，仅输出 `|wz|<=0.08rad/s`；yaw 连续稳定 1 秒后零速并确认 arbiter 回到 idle。旧同点 DWB 路线保留为 `*-dwb-baseline`。本机相关 20/20 测试通过，Jetson `/tmp` 隔离 Python 3.8 测试 19/19 和三类 route 描述通过。Jetson 当前有生产 Navigation 栈运行，因此未覆盖生产 worktree、未 build、未发 goal；隔离目录已删除。

### Current Update — 2026-08-04 17:07
开始从 `1efbcd6` 恢复后的导航基线实现显式 DWB → yaw-only 接管：在 `pos1_middle` XY 距离进入阈值后，precision 先以三轴零速取得 lease 并确认停稳，再取消当前 NavigateToPose，随后以实时锚点固定 XY、仅输出受限 `angular.z` 完成 180° 转身。保留刚完成的 `0.12m/s` 三层限速改动，不开放 DWB 横移/后退，不启动真机运动。

### Current Update — 2026-08-04 16:16
已重写 `学习/未命名 3.md` 为当前可执行的 Navigation-only 全航点手动测试教程。文档明确当前是 `1efbcd6 + 0.12m/s`、限定 base path 构建、五项速度核验、10 航点列表、第三段已知风险、动作前门禁、结果读取和失败清理；加入危险 callout 禁止使用 armed UDP smoke 归零。Markdown 代码围栏成对，4 个相对源码链接均解析成功。

### Current Update — 2026-08-04 16:05
按用户要求将 Nav2 基线前进速度上限从 `0.10m/s` 保守提高 20% 至 `0.12m/s`：DWB `max_vel_x/max_speed_xy`、arbiter `max_vx`、bridge `hard_max_vx/hard_max_speed_xy` 五项已统一；加速度、转向速度、横移和航点均未修改。新增静态一致性测试，本机和 Jetson 均通过；Jetson `colcon build` 成功，当前全栈停止。该调整只缩短直线段时间，不修复第三段 DWB 边走边转，且可能放大该段漂移，下一次真机需重点监控。

### Current Update — 2026-08-04 15:54
`1efbcd6` 基线 `nav-only-full` 已真机运行：第 1 段 `obstacle_cross_target`、第 2 段 `pos1_middle` 成功；第 3 段 `pos1_middle_turned` 130 秒超时后正常取消，未运行第 4-10 段。第三段从 `(1.520,3.153,1.310)` 到 `(1.128,3.204,0.845)`，5240 条 cmd 中 2785 条含 `linear.x`、5199 条含 `angular.z`，重现 DWB 边走边转的基线问题。已停止全栈和 Docker，Lite3 `motion_state=0`。收尾时误调用默认 UDP smoke 序列，额外发送 1 秒 `vx=0.04` 与 1 秒 `wz=0.12`；随后已连续发送 3 秒三轴零速。下一步必须先由用户现场确认额外短时移动影响，再决定是否继续。

### Current Update — 2026-08-04 15:31
Jetson 基线文件已与 `1efbcd6` 对齐：仅覆盖后续实验改过的 probe、SE(2) controller 和对应测试，并移除基线中不存在的 callback stress test；原文件备份在远端 `tmp/baseline_restore_1efbcd6_20260804_1530/`。`nav-only-full` 已断言为 10 个旧 DWB 基线航点，限定 base path 的 `colcon build` 成功。离线测试 10 pass、1 fail；失败是 `test_lite3_udp_smoke` 的旧 mock 缺少 `test_closed_yaw` 字段，生产启动链不引用该工具，未修改基线。当前等待用户明确确认官方起点、站稳、全路线净空和急停人员就位后，才允许运行实体路线。

### Current Update — 2026-08-04 15:18
已按用户要求在导航 worktree 使用非改写历史的 `git revert` 回到 `1efbcd6` 源码状态：依次创建 `aafa17f`（revert split-Y）、`9580616`（revert callback/thread 改动）、`88b4eeb`（revert yaw-only）。当前 `HEAD` tree 与 `1efbcd6` tree 均为 `9c3dd6222f275fcaaad40d5cecfac0db94249204`，工作区干净，原提交历史全部保留。下一步改动必须从当前恢复后的基线单变量推进。

### Current Update — 2026-08-04 14:57
只读复核确认导航最佳历史基线为 `753f5b3`；若包含后续漂移诊断工具则取 `1efbcd6`。该基线在 2026-08-02 的 `nav-only-full` 前 5 段成功，第 6 段 `grab_area_approach` 超时。当前导航 worktree `quadruped-robot-competition-nav2-dwb` 位于 `1991aa4`，并有两个未提交文件改动；未提交 split-Y 实验的最新摘要显示第 1-4 段成功，第 5 段在 130 秒后超时，终点 `(2.640,3.424,-0.728)`。下一步不得继续在当前实验状态叠加修改，应先从 `753f5b3`/`1efbcd6` 建立干净恢复点，再一次只验证一个改动。

Phase 23 当前：2026-08-03 clean 真机运行包含 `pos1_left_clear` 的完整 11 航点路线。第 1 段成功；新增第 2 段成功，机器人在箱体纵向范围内保持 `x=0.411..0.480`，明显远离此前最高约 `x=0.76` 的贴箱轨迹，终点 `(0.559,2.878,1.291)`。第 3 段 `pos1_middle` 运行 130 秒后安全取消，终点 `(1.115,3.166,0.957)`，仍有约 `0.394m` XY 误差，未进入 yaw-only。全栈已零速清理。下一步应处理 clear 点到 middle 点的非完整运动学/DWB 收敛，不再修改已验证有效的通道航点。

Phase 20 当前：UDP `final_bridge.py` 已验明 raw/Host 严格一致，`base_link` 输入走 `base_passthrough`，不再存在旧 X/Y translation-only flip。2026-07-11 趴地拖行显示 X/Z 强相关后，已核对 D455/Lite3 frame 语义并确认 `base_link -> camera_link` 的 pitch 符号写反：ROS `pitch=-30°` 会让 camera X 轴上仰，向下 30° 应使用 `pitch=+30°`。robot-mode cuVSLAM 暂未稳定发布 odometry，官方 camera-link baseline 可发布 odometry，Host `camera_to_base` bridge 正常。已在 checkpoint `867c8ff` 后新增并验证 `--camera-world-rebase base_start --planarize-output`，Host 输出 `dist_xy=1.144m`、`dz=0`、`z_span=0`。2026-07-12 已将 Stonefield `start_competition.sh` 切到 camera-link + Host rebase/planar bridge，默认关闭 task_manager、auto_advance、cmd_vel_bridge 和 Host depth_publisher；Jetson dry-run 显示 `map->base_link` 约 `(5.351, 0.751, z=0, yaw=pi)`，Nav2 lifecycle 全 active，0.22m yaw=pi goal 的 `/cmd_vel` 为 `max_linear_x=0.10m/s`、`max_abs_angular_z=0.0079rad/s`。随后发现 transfer workspace 未构建，新增显式 `--cmd-vel-bridge` fallback；用 `--dog --cmd-vel-bridge` 进行 0.18m live 尝试，Nav2 accepted 并输出 40 条非零 `/cmd_vel`，`max_linear_x=0.0733m/s`、`max_abs_angular_z=0.0079rad/s`，但 `map->base_link`/`odom_latest` 未显示可观测位移。下一步需根据现场观察确认狗是否实际轻微移动；若没有移动，优先排查 Lite3 UDP 下发/姿态模式，而不是扩大 Nav2 目标距离。

### Current Update — 2026-08-02 18:05
再次 clean 执行 `nav-only-full` 完整基线路线：前 5 段全部 `SUCCEEDED`，包括此前困难的同点 180 度 `pos1_middle_turned`；第 6 段 `grab_area_approach` 在 130 秒后正常取消，未进入 A/B/C/D 放置点。第 3 段转向中 `linear.x` 与 `angular.z` 同时非零占 58.5%，XY 位移 0.281m；第 6 段重叠占 41.7%，从 `(2.701,1.965,-2.876)` 到 `(3.228,2.139,-0.223)`，最终 XY 误差 0.193m，始终未进入 0.15m 容差。日志显示 `GridBased failed to generate a valid path to (3.10,2.00)`；UDP `errors=0`、定位 bridge 延迟约 17-23ms。测试后已三轴零速、停止全部进程和 Docker；Lite3 `motion_state=0`、三轴目标 0、电量 39%。

### Current Update — 2026-08-03 15:36
已将生产 `nav-only-full` / `nav-only-inspection` 的 `pos1_middle_turned` 从 DWB 同点终端转向改为显式 `yaw_only` precision 接管：大角度阶段固定 `vx=0, vy=0`，仅发布限速/限加速度 `wz`；旧行为保留为 `*-dwb-baseline`。本机与 Jetson 15/15 控制/仲裁测试、Python 语法、Python 3.8 AST 和 `git diff --check` 通过，Jetson `colcon build` 通过；`--describe-route` 断言前三段为 `nav2, nav2, yaw_only`。无狗 ROS 图确认 `/cmd_vel` 唯一发布者为 `cmd_vel_arbiter`，`/cmd_vel_precision` 有唯一仲裁订阅者，且未启动 bridge/motion sender/goal。dry-run 已清理，仅保留测试前既有的 cuVSLAM 容器；尚未做真机运动。

### Current Update — 2026-08-03 16:04
最新真机日志 `20260803_155627_full_nav_manual`：前两段 Nav2 均 `SUCCEEDED`；第三段进入 `kind=yaw_only`，precision lease 正常取得，`linear_x/y_nonzero_count=0/0`、`max_abs_wz=0.12`，顺时针转约 `0.164rad` 后以 `yaw-only TF unavailable: map TF is stale (age 0.210s)` 安全退出。Nav2 trace 已显示 TF age 间歇峰值 `1.913s/3.877s`，但 `final_bridge` 同期仍持续发布且 UDP errors=0。Jetson Foxy 源码确认 `rclpy.spin_once()` 每次只处理一个 callback、`TransformListener(... spin_thread=False)` 为默认；probe 同时接收高频 cmd/odom/tf，导致 TF callback 饥饿。测试后运动栈已退出，仅 cuVSLAM 容器保留。

### Current Update — 2026-08-03 callback 调度修复
`nav2_waypoint_sequence_probe.py` 已将 TF listener 放入独立 spin thread，并将 odom subscription 放入第二个独立 `SingleThreadedExecutor` 线程；主节点只处理 action 与 `/cmd_vel` 安全监视，退出时显式关闭后台 listener/executor。新增隔离话题压力测试和 `nav-only-turn-validation` 三段最小路线；trace 增加 `tf_error`、`hold_elapsed_sec`。本机 16 项通过（无 ROS 环境的压力项正确 skip），Jetson 16/16 通过，压力测试末段最大 TF age `0.0225s`；Jetson 构建通过。当前仍需清理一次短时真实反馈验证留下的 exporter 子进程并完成最终复核，未启动 Nav2/arbiter/cmd bridge/motion sender，也未发送运动命令。

### Current Update — 2026-08-03 17:01 full route retry
用户确认机器狗人工放回官方起点后，clean 启动 Navigation-only 真机栈；初始 `map -> base_link=(4.650,0.750,yaw≈pi)`，五个 lifecycle 均 active，`/cmd_vel` 为 arbiter 唯一发布者和 Lite3 bridge 唯一订阅者，motion prepare `errors=0`。随后按用户明确要求运行 `nav-only-full`：第 1 段成功，第 2 段在约 `(0.764,2.380,1.456)` 处 `ABORTED`，日志为 `GridBased failed to generate a valid path to (1.50, 3.25)`；未进入 yaw-only 或后续航点。失败后 controller 下发零速，全栈与 cuVSLAM 容器已清理。

### Current Update — 2026-08-04 14:07 full route requested
按用户明确要求清理正在占用 D455 的 YOLO 标定容器及宿主残留后，clean 运行生产 `nav-only-full`。五个 lifecycle、初始 TF、`/cmd_vel` 单发布/单订阅和 UDP 门禁均通过；第 1-3 段全部成功。第 4 段 `yaw_only` 严格保持 `vx=vy=0`，但 cuVSLAM 报告 anchor 位移达到 `0.302m`，触发安全半径退出，未进入第 5-11 段。本轮已再次三轴零速、停栈并删除 cuVSLAM 容器；当前下一步应改跑隔离的 split-Y 六点实验来验证用户提出的空间回环方案，而不是重复生产 yaw-only 路线。

### Current Update — 2026-07-15
Clean single-shot 0.5m Nav2 真机闭环已由用户现场确认 OK。当前主线从“验证 0.5m 是否能跑通”切换为“固化该规程并推进更长距离/分段场地导航测试”。

### Current Update — 2026-07-26
Navigation-only 最小链路已恢复：`start_competition.sh` 默认跳过 camera/depth relay，只保留 cuVSLAM odom bridge；无运动启动下 `planar_60fps` 成功发布 `/visual_slam/tracking/odometry`，Host `/tmp/odom_latest.json` 与 `map -> base_link=(4.65,0.75,yaw=pi)` 正常，Nav2 lifecycle 全 active。无狗 dry-run goal `(4.15,0.75,yaw=pi)` 返回 `accepted=true`、`cmd_count=80`、`nonzero_count=80`，且 `/cmd_vel` subscription count 为 0。下一步需现场确认狗站稳和路径安全后，clean 启动 `--dog --cmd-vel-bridge --prepare-lite3-motion`，先跑 0.3-0.5m single-shot。

### Current Update — 2026-07-26 20:27
Navigation-only 0.3m 真机 single-shot 已通过：clean 启动 `--dog --cmd-vel-bridge --prepare-lite3-motion`，仍保持 YOLO/WHZ/camera relay/depth relay/task_manager 全关；`nav2_waypoint_sequence_probe.py --forward-distances 0.3` 返回 `action_status=SUCCEEDED`，`cmd_count=108`、`nonzero_count=107`，bridge `udp_simple=486`、`udp_complex=486`、`udp_errors=0`，TF delta 约 `x=-0.1609m,y=+0.0057m`，方向符合 yaw≈pi 前方。远端已清理无残留。下一步根据现场观察，选择 clean single-shot 0.5m 或 `0.3m + 等待 + 0.3m` 连续航点。

### Current Update — 2026-07-26 20:42
按用户要求直接跑起点到任务首目标 `obstacle_cross_target`，clean 启动 Navigation-only 真机栈后发送绝对 goal `(0.5,0.75,pi)`。本轮 Nav2 goal 被接受并产生 `/cmd_vel`：`cmd_count=31`、`nonzero_count=31`、`max_linear_x=0.1m/s`、`max_abs_angular_z≈0.0868rad/s`，但 action 很快 `ABORTED`。TF 从 `(4.6499,0.7502,yaw≈pi)` 变为 `(4.7355,0.7313,yaw≈3.070)`，delta `x=+0.0856m,y=-0.0189m`；目标方向应为 x 减小，因此当前问题收窄为长距离点到点 goal 开始跟踪时的控制/方向一致性问题，不是 cuVSLAM 首包、Nav2 action 接收、`/cmd_vel` subscription 或 Lite3 bridge 零输出问题。远端已停栈清理。

### Current Update — 2026-07-26 22:00
根据现场“狗确实前进而非原地转”的观察，修正 `cmd_vel_bridge.py`：默认 `send_combined_axes=True`，每周期发送 FWD/LAT/YAW 三轴完整状态；stale 后持续三轴零速；退出时发送三轴零速 burst。Jetson 已同步并 `colcon build --symlink-install`。真机复测：0.3m forward goal `SUCCEEDED`，delta `x=-0.1587m`；随后 direct `obstacle_cross_target` 从 `x=4.575` 走到 `x=1.049`，delta `x=-3.526m`，方向和连续运动明显改善，但在距目标约 `0.551m` 处 `ABORTED`。远端已停栈清理。下一问题从“起步方向/bridge 速度状态”转为“目标前 0.5m 左右的 Nav2 abort/局部规划或终点可达性”。

### Current Update — 2026-07-27 00:35
按“目标中心点内移”假设做 clean Navigation-only 真机验证：启动 `BRIDGE_INIT_DOG=false CUVSLAM_PROFILE=planar_60fps bash scripts/start_competition.sh --dog --cmd-vel-bridge --prepare-lite3-motion`，发送绝对 goal `(1.05,0.75,pi)`。结果 `SUCCEEDED`，从 `x=4.640,y=0.743,yaw≈3.135` 到 `x=1.189,y=0.764,yaw≈-3.040`，delta `x=-3.451m`，`cmd_count=361`、`linear_x_nonzero_count=360`、`max_linear_x=0.1m/s`。这基本确认 `(0.5,0.75)` 作为 `base_link` 中心 goal 太靠左边界；后续应把该任务航点改为约 `(1.05,0.75,pi)` 或把 `(0.5,0.75)` 仅作为“前缘/通过区域”判定点，而不是 Nav2 中心目标。远端已发零速并清理 Nav2/bridge/cuVSLAM 容器残留。

### Current Update — 2026-07-27 Navigation-only 全路线准备
用户明确希望先跑通整个 Nav 流程，到达所有目标点后再接 RGB/depth/YOLO/仪表等相机感知链路（cuVSLAM 所需 IR+IMU 保留）。已在 Nav2 worktree 将 waypoint 统一改为 `base_link` 可达中心/接近点：`obstacle_cross_target=(1.05,0.75,pi)`，抓取区改为左侧接近点，放置 A/B/C/D 改为纸箱下方接近点，右侧观察位从 x=2.20m 右移到 x=2.60m；同时修正场地 mm 坐标 yaw 到 ROS yaw 的符号转换。新增 `nav2_waypoint_sequence_probe.py --route-preset nav-only-full` / `nav-only-inspection`，并将 task_manager 的 Phase2 地图切换推迟到到达 `pos1_middle` 后，避免在 `obstacle_cross_target` 接近点立即切图导致当前 pose 落入封闭 obstacle 区。

### Current Update — 2026-07-27 14:21
按用户要求重复刚才的完整启动/运行流程：clean 启动 Navigation-only 真机栈后再次执行 `nav-only-inspection`。本轮第 1 段 `obstacle_cross_target=(1.05,0.75,pi)` 成功，`cmd_count=365`、`nonzero=364`，TF delta `dx=-3.570m,dy=+0.0068m`，终点 `(1.080,0.757,yaw≈-3.001)`。第 2 段 `pos1_middle=(1.5,3.25,pi/2)` accepted 且有 `/cmd_vel`，`cmd_count=144`、`nonzero=144`，但最终 `ABORTED`，移动约 `0.871m`，终点 `(0.570,1.469,yaw≈1.407)`。远端已发零速、`stop_all.sh` 并清理 cuVSLAM Docker 残留，当前无相关进程/容器。

### Current Update — 2026-07-30 13:05
使用无恢复 BT clean 复测三段移动式转身，输出为 `/home/superwfx666/competition_logs/nav2_waypoint_sequence/20260730_130157`。`obstacle_cross_target`、`pos1_left_clear`、`pos1_middle` 连续 `SUCCEEDED`；第 4 段 `pos1_turn_quarter_1=(1.72,3.50,0)` 在 13.34s 后 `ABORTED`。该段从 `(1.369,3.134,1.841)` 漂到 `(1.494,3.781,-0.129)`，最近目标仍有 `0.352m`，下一轮 1Hz 重规划报 `GridBased failed to generate a valid path`。无 `send_goal failed`、无 Spin recovery，abort 后 controller 被取消并持续下发零速。Nav2、bridge、probe、cuVSLAM 容器均已清理。下一步需选择对 `pos1_middle` 实际终点波动更鲁棒的转向方式，固定近距离绝对 waypoint 已不足以约束 Lite3 的转向漂移。

### Current Update — 2026-07-30 16:40
已完成混合闭环最小实现：Nav2 继续负责全局规划与长距离移动，新增基于实时 `map -> base_link` 的三轴 SE(2) 低速精调，并通过 `/cmd_vel_nav2 + /cmd_vel_precision -> cmd_vel_arbiter -> /cmd_vel` 保证唯一速度出口。本机 11/11 单元测试、`py_compile`、`git diff --check` 通过；Jetson 已完成此前 9 项控制/仲裁测试、`colcon build` 和 ROS 图 dry-run，确认 `/cmd_vel` 唯一发布者为 `cmd_vel_arbiter`。上一轮 dry-run 遗留的 8 个 Nav2 PID 已精确 `SIGTERM` 清理，未发现 `cmd_vel_bridge` 或 `motion_sender`。真机前仍需只做一次低速 `CODE_LAT` 正方向脉冲确认横移符号，然后运行 `nav-only-inspection-se2`。

## Phases

### Phase 1: 初始化 PWF 三件套
- [x] 创建 `task_plan.md`
- [x] 创建 `progress.md`
- [x] 创建 `findings.md`
- [x] 记录当前仓库初始观察结果
- **Status:** complete

### Phase 2: 下一项具体任务规划
- [x] 根据用户下一步目标拆分任务
- [x] 必要时查询 L1-3 长期记忆
- [x] 更新本计划的 Current Phase 和阶段状态
- **Status:** complete

### Phase 3: stable 分支远端测试
- [x] 等远端 Ubuntu/Tailscale SSH 恢复可达
- [x] 在 Ubuntu 上用独立 worktree 或独立目录检出 `stable/jetson-gauge-ok`
- [x] 运行 Python 语法检查和样例测试
- [x] 如有 D455，运行 live gauge 测试
- [ ] 测试通过后再决定是否回填本机第一任务目录
- **Status:** in_progress

### Phase 4: 第一部分任务一交付整理
- [x] 明确源码包目标目录：`文档与源码/源码包/视觉相关/`
- [x] 选择要放入提交包的表计识别脚本或功能包
- [x] 确认代码无硬编码答案、无人工交互依赖
- [x] 准备官方赛题 PDF 截图/提取出的表计素材
- [x] 准备一条可复现实运行命令
- [x] 实时识别脚本启动后自动弹出相机画面窗口，并保留终端状态输出
- [x] 录制 `第一部分/第一部分-任务1.mp4`
- [x] 确认视频不超过 5 分钟、正常速度、左下角水印全程可见
- **Status:** complete

### Phase 5: 选择性导入 camera/IMU/cuVSLAM 分支
- [x] 确认远端 `feature/camera-imu-cuvslam` 是无共同祖先的 root commit 分支
- [x] 从当前 `main` 创建正常本地分支 `codex/import-camera-imu-cuvslam`
- [x] 下载远端分支快照，不直接 merge unrelated history
- [x] 选择性导入 RealSense camera wrapper、IMU、红外双目、cuVSLAM 相关文件
- [x] 添加 `pyproject.toml` / `setup.py` 支持 `src/` 包化导入
- [x] 添加 `scripts/realsense_viewer.py` 和 `docs/pyrealsense2_api_reference.md`
- [x] 修正文档示例中的构造函数参数名
- [x] 将导入模块中的 Python 3.10 类型注解改为 Jetson Python 3.8 兼容写法
- [x] 运行本地语法、Python 3.8 AST 兼容和 whitespace 检查
- [x] 将 GitHub `feature/camera-imu-cuvslam` 中有价值内容选择性合入本地 `main`
- [x] 导入 `InstanceSegmentation/` YOLOv8-seg 工作区但排除 `.pt` 权重文件
- [x] 修正文档中的 D455 IMU 状态：视觉流通过，IMU 仍待 udev/root 权限处理后复测
- [x] 创建协作分支 `codex/import-camera-imu-cuvslam-segmentation` 并提交 PR #1
- [x] 在 Jetson 上运行 `python3 -m pip install -e .` 后做 D455 实机验证
- **Status:** complete

### Phase 6: Jetson 平台版本 SSH 探针
- [x] 尝试用户给出的 `superwfx666-desktop@100.126.48.49`
- [x] 识别 `superwfx666-desktop` 是远端 hostname，不是可登录用户名
- [x] 使用 `superwfx666@100.126.48.49` 并完成 Tailscale SSH 浏览器认证
- [x] 查询 Jetson 型号、Ubuntu、L4T、kernel、CUDA、ROS、Docker/container runtime、Python 依赖
- [x] 将可复用 SSH 探针流程整理到 `findings.md`
- [x] 将执行过程和错误处理整理到 `progress.md`
- **Status:** complete

### Phase 7: 创建项目学习文档
- [x] 创建 `学习/` 目录
- [x] 创建 Obsidian 索引笔记
- [x] 整理调试时间线
- [x] 整理 D455 仪表识别调试复盘
- [x] 整理 Jetson 与 ROS 环境确认笔记
- [x] 整理 cuVSLAM 导航方案学习笔记
- [x] 整理 Git 分支与交付包经验
- [x] 整理 SSH 与远程调试经验
- [x] 补充 D455 输入验证脚本和 Jetson GitHub SSH 凭据配置学习笔记
- [x] 补充 cuVSLAM 比赛级定位精度调试学习笔记
- [x] 补充 GitLab/GitHub 仓库协同管理与团队工作流学习笔记
- **Status:** complete

### Phase 8: cuVSLAM 现有硬件可运行性验证
- [x] 通过 SSH 重新确认 D455 是否被 Jetson 枚举
- [x] 短时验证 D455 infrared 1/2 双目流
- [x] 修复 RealSense IMU udev/IIO 权限
- [x] 短时验证 D455 accel/gyro IMU 流
- [x] 在 GitHub 最新 `main` 的 Jetson 独立 worktree 中验证 `RealsenseCamera.for_cuvslam()`
- [x] 保护 Jetson 原仓库本地 `scripts/realsense_gauge_live.py` 改动并将原仓库更新到最新 `main`
- [x] 新增一键 D455 输入验证脚本并在 Jetson 原仓库测试分支跑通
- [x] 创建 PR #2：`test: add D455 cuVSLAM input validator`
- [x] PR #2 合并后配置 Jetson 账号级 GitHub SSH 凭据
- [x] 将 Jetson 原仓库 `main` 快进到 `82512c6`
- [x] 检查当前系统是否已有 Isaac ROS/cuVSLAM 运行依赖
- [x] 给出“硬件是否满足、现状能否直接跑、还缺什么”的结论
- **Status:** complete for hardware input short-test; Isaac ROS/cuVSLAM runtime stack still pending

### Phase 9: Isaac ROS Visual SLAM/cuVSLAM runtime 验证
- [x] 复跑 Jetson D455 一键输入短测，确认硬件回归后 RGB/depth/IR/IMU/wrapper 全部 PASS
- [x] 确认继续使用 Isaac ROS `release-2.1` / ROS2 Humble 容器路线，不污染 host Foxy
- [x] 定位上一轮 `isaac_ros_nitros` 构建失败根因：缺 `nvToolsExt.h` 和 `libnvToolsExt.so`
- [x] 在 Jetson host 安装最小 CUDA 组件 `cuda-nvtx-11-4` 补齐 NVTX
- [x] 补齐 Jetson host CUDA runtime libraries：`cuda-libraries-11-4`、`cuda-cupti-11-4`
- [x] 用 Isaac ROS Humble 基础镜像和必要 Jetson CUDA/tegra bind mounts 构建 `isaac_ros_visual_slam`
- [x] 验证容器内 package/launch 可见性，`ldd` 无 missing shared library
- [x] 构建 runtime 镜像 `isaac_ros_cuvslam_runtime:humble-rs`，通过二进制包补齐 `realsense2_camera`
- [x] 验证 RealSense ROS driver 可枚举 D455 并发布 `/camera/infra1/image_rect_raw`、`/camera/infra2/image_rect_raw`、`/camera/imu`
- [x] 启动 `isaac_ros_visual_slam_realsense.launch.py` 并检查关键 topic、TF、odometry/tracking 状态
- [x] 完成首轮 180 秒手持/装车轻微运动稳定性测试，记录 odom 连续性和 image delta warning
- [ ] 继续定位 image delta warning 和 `Visual tracking is lost` 根因，必要时降低 IR 频率/负载或调整 RealSense/cuVSLAM 参数后复测
- **Status:** complete for first motion probe; timing/lost-tracking mitigation pending

### Phase 10: cuVSLAM RViz/loop-closure 演示验证
- [x] 明确老师希望在 RViz 中观察 loop closure、长距离导航 tracking performance 和 cuVSLAM 输出 topic
- [x] 新增 Jetson GUI 启动脚本 `scripts/start_cuvslam_rviz_gui.sh`
- [x] RViz 配置覆盖 odometry、VO path、SLAM path、landmarks、loop closure cloud、pose graph nodes/edges、velocity/gravity、IR 左右图
- [x] 启动参数默认打开 SLAM visualization、landmarks view、observations view 和 localization-and-mapping
- [x] 记录 topic list、topic presence 和关键 topic hz 到日志目录
- [x] 将 `scripts/start_cuvslam_rviz_gui.sh` 基于 GitHub 最新 `main` 推送到远端，并直接拷贝到 Jetson 当前仓库
- [ ] 在 Jetson 桌面/VNC/NoMachine 上实跑 RViz，确认窗口可见、topic 全部出现
- [ ] 走 3-5 分钟大回环路径，观察 `vo_state`、odom/SLAM path 连续性、loop-closure cloud 和 pose graph 变化
- [ ] 保存日志/截图/录屏，整理给老师看的演示结论
- **Status:** in_progress

### Phase 11: cuVSLAM 比赛级定位稳定性调试
- [x] 明确用户目标：不是只启动 RViz，而是尽量降低 trajectory/回环误差，让机器人自身位置可用于比赛
- [x] 检查最新 Jetson 回环日志 `/home/superwfx666/cuvslam_lite3_logs/20260625-202512`
- [x] 确认 recorder 当前误判：`slam_path`/`vo_path` 为静态重复点时仍优先按 `slam_path` 输出 `insufficient_motion`，掩盖 odometry 已运动 `37.303 m` 且闭合误差 `2.719 m`
- [x] 确认 TF 语义问题：当前 `base_frame=camera_link`，且没有发布 `base_link -> camera_link` 静态外参
- [x] 开始修改 `scripts/cuvslam_loop_metrics_recorder.py`：已加入阈值参数、odometry `frame_id/child_frame_id`、primary source 选择逻辑雏形
- [x] 完成 recorder 输出格式修复，确保 `loop_metrics_latest.txt/json` 显示 `primary_source`、`robot_base_ready` 和 `path_topics_static_using_odometry`
- [x] 修改 `scripts/start_cuvslam_rviz_gui.sh`：将 `CUVSLAM_BASE_FRAME`、`base_link -> camera_link` 静态 TF、localization/mapping、ground constraint 等参数显式化
- [ ] 在 Jetson 同步脚本并运行 `bash -n`、`python3 -m py_compile`（当前卡在 Tailscale SSH 用户认证阶段；Jetson 在线且 Tailscale ping 正常）
- [ ] 做至少两轮固定路线 A/B 测试，记录 closure error、delta warning/min、`vo_state`、tracking lost、CPU/GPU 负载
- [ ] 根据测试结果选择比赛默认 profile 和启动命令
- **Status:** in_progress

### Phase 12: GitHub README 国赛技术栈整理
- [x] 基于 GitHub 最新 `main` 创建干净 worktree：`C:\Users\111\Desktop\比赛\quadruped-robot-competition-github-main-readme`
- [x] 阅读 GitHub 最新代码结构、国赛 PDF、导航/YOLO/OpenCV/cuVSLAM/任务管理相关入口
- [x] 明确本项目国赛主线：cuVSLAM + Nav2 导航，YOLO 识别锥桶/长条/物块类目标，OpenCV 识别仪表盘，任务管理串联语音播报接口
- [x] 新增根目录 `README.md`，讲清除机械臂外的国赛技术栈、模块边界、当前 SLAM 状态和下一步
- [x] 提交并推送到 GitHub `main`
- **Status:** complete

## Key Questions
1. 第一部分任务一最终提交包的本机目标根目录在哪里？
2. 官方赛题 PDF 的表计截图素材目前放在哪个目录？
3. 水印文本中的学校名称、队伍名称、组别分别应写成什么？
4. 是否使用 stable 分支的 `scripts/realsense_gauge_live.py` / `gauge_detector.py` 作为第一部分任务一源码基础？

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| 使用 PWF 三件套作为本仓库 L1-2 短期记忆 | 符合用户全局 L1 系统规则，便于跨 session 恢复上下文 |
| 初始化任务只创建记忆文件，不修改业务代码 | 用户当前请求是建立三件套，不要求功能变更 |
| `main` 继续面向国赛/ROS2 topic 通信，`stable/jetson-gauge-ok` 代表预赛第一天仪表识别稳定版本 | 用户说明当前 main 已在预赛基础上加入上下位机通信和 ROS2 节点封装，stable 更接近第一天交付内容 |
| 第一部分任务一当前只回填 `scripts/realsense_gauge_live.py` | 用户已在 Jetson 上验证该脚本可用，并明确其他文件暂不需要 |
| 不直接 merge `feature/camera-imu-cuvslam`，改为选择性导入文件 | 该分支 commit `8b713c2474ef5b67f9df85f1f2be3534f922bd75` 无 parent，GitHub compare 显示与 `main` 无共同祖先；直接 merge 会引入 unrelated history 风险 |
| cuVSLAM 验证不直接进入当前 Foxy 主环境 | SSH 探针确认 Jetson 是 Ubuntu 20.04 / ROS2 Foxy；当前 Isaac ROS Visual SLAM 目标栈与 Foxy 不匹配，应先走容器/独立环境验证 |
| D455 输入链路增加一键短测脚本 | 手工 SSH 片段不可复用；`scripts/realsense_cuvslam_input_test.py` 可用单条命令回归 RGB/depth、IR+depth、IMU 和 `for_cuvslam()` |
| Jetson 使用账号级 GitHub SSH key 而非 deploy key | 用户明确允许账号级通用 GitHub 权限；配置后 Jetson 可直接 `git fetch/pull` 账号可访问仓库 |
| cuVSLAM 比赛定位不能直接使用当前 `camera_link` 输出当作机器人本体位姿 | 最新运行确认 `base_frame=camera_link` 且无 `base_link -> camera_link` 静态外参；比赛导航需要机器人自身位姿，应补外参或改成 `base_frame=base_link` |
| 后续调参必须以数字指标为准，不以 RViz 观感为准 | 最新 recorder 误判 `insufficient_motion`，而 odometry 实际已有 37.303 m 路径和 2.719 m 闭合误差；必须先修评估逻辑再比较参数 |
| 根 README 以 GitHub 最新 `main` 为事实基准，而非当前不同步的本机 workspace | 用户明确说明本机 workspace 与 GitHub 不同步，GitHub 当前应视为最新；README 任务因此在干净 worktree 中完成 |
| README 中机械臂只保留接口边界，不写成已实现模块 | 用户说明机械臂抓取当前不在仓库里；避免文档误导 |
| README 中明确标注 YOLO 类别映射仍需统一 | GitHub 最新代码中 `configs/yolo/classes.yaml` 与 combined 模型 README/YOLO publisher 注释存在类别描述差异，后续需要统一模型、配置和 task_manager 解析 |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| Foxy `ros2 topic echo` 不支持 `--once` | 动作前读取 arbiter mode 和最终 `/cmd_vel` 单条消息 | 用 `head` 截取首条消息；确认 mode=`idle` 且三轴零速，截断导致的 BrokenPipe 仅是诊断 CLI 退出，不影响 ROS 节点 |
| `nav2_yaw_takeover` approach 在距目标约 `2.519m` 时返回 `SUCCEEDED` | 首次生产完整路线验证显式接管 | 接管状态机正确以 `TAKEOVER_ABORTED` 拒绝 precision/yaw-only 并由 `--stop-on-failure` 停止；已停栈，保留日志，离线诊断 action 假成功或瞬时定位跳变 |
| 远端非交互 shell 中 `rs-enumerate-devices` 不在 `PATH`，导致首轮并行只读预检的聚合调用失败 | 检查 Jetson 相机枚举和导航进程 | 将检查拆成独立 SSH 命令，使用 `lsusb -d 8086:0b5c` 确认 D455 已枚举；未启动任何运动组件 |
| PowerShell 中使用 Bash here-doc 写法 `python - <<'PY'` 失败 | 检查本地 Python/matplotlib/numpy 环境 | 改用 PowerShell here-string 管道到 `python -` |
| 内联 Python 通过 PowerShell 管道处理中文路径时变成 `????` | 统计 `技术报告/.../slam_all_poses_latest.csv` 数值概览 | 改用 Unicode 转义路径；正式绘图脚本通过 `__file__` 定位目录，不依赖内联中文路径 |
| `brv query` 不可用 | 按复杂任务规则尝试查询 DWB/RPP 相关长期记忆 | 当前 Windows PATH 无 `brv`；记录到 findings，继续使用 PWF 上下文和官方 Nav2 资料推进 |
| 远端 `git fetch origin --prune` 失败：HTTPS remote 在非交互 SSH 中无法输入 GitHub 凭据 | 在远端主仓库执行 fetch | 使用远端已有的 `origin/stable/jetson-gauge-ok` 引用创建独立 worktree |
| 本机 `python scripts\run_gauge_sample.py` 失败：缺少 `cv2` | 本地验证样例测试 | 记录为本机环境缺依赖；需在 Jetson 或安装 OpenCV 的 Python 环境运行 |
| 本机 `import pyrealsense2` 失败：缺少 `pyrealsense2` | 本地验证 RealSense 依赖 | 记录为本机环境缺依赖；RealSense wrapper 需在 Jetson/D455 环境验证 |
| Windows PowerShell 中远端 SSH one-liner 被本地解析 `|` 正则 | 初次执行远端查询命令 | 改用 PowerShell here-string，经 stdin 传给远端 `bash -s` |
| `ssh superwfx666-desktop@100.126.48.49` 失败：Tailscale 找不到本地用户 | 按用户原始 SSH target 连接 | 改用有效用户名 `superwfx666@100.126.48.49`；`superwfx666-desktop` 只是 hostname |
| PowerShell here-string 管道到 SSH 时远端 bash 看到 UTF-8 BOM / here-doc 未结束 | cuVSLAM D455 探针 | 改用本地无 BOM、LF 换行临时脚本，并通过 `cmd.exe /c type ... \| ssh ... bash -s` 原样传输 |
| Jetson 当前 `lsusb`、`/dev/video*`、`pyrealsense2` 均未枚举到 D455 | cuVSLAM 硬件输入验证 | 先检查 D455 是否插到 Jetson USB3 口、线缆/供电/占用；未枚举前不能继续 IR 双目和 IMU 流验证 |
| `pyrealsense2` 启动 IMU 时报 `Failed to set frequency ... Permission denied` | D455 IR+IMU 流测试 | 已确认 D455 枚举和 IR/depth 出帧正常；IMU 的 IIO sampling_frequency 节点为 `root:root 600`，需安装/生效 RealSense udev 规则或用 root 权限复测 |
| Jetson 原仓库无法直接 `git fetch origin --prune` | 用户要求在 Jetson pull GitHub 最新代码 | Jetson 没有 GitHub HTTPS/SSH 凭据，且原仓库有 `scripts/realsense_gauge_live.py` 本地未提交改动；改用本机从 GitHub 拉取 `origin/main=11b783e` 后生成 git bundle，导入 Jetson 独立 worktree `/home/superwfx666/quadruped-robot-competition-main-latest-test` 测试，未覆盖原仓库 |
| D455 IMU IIO `sampling_frequency` 节点权限为 `root:root 600` | 普通用户启动 accel/gyro 失败 | 使用 `root@100.126.48.49` 安装官方 RealSense `99-realsense-libusb.rules`，执行 `udevadm control --reload-rules` 和 trigger 后节点变为可写，普通用户 IMU 测试通过 |
| 一键验证脚本首次 `IR stereo + depth` 检查超时 | 初版脚本在 `enable_color=False, enable_depth=True, enable_infrared=True` 的 wrapper 配置里调用 `get_depth_image()`，与 wrapper 的 color/depth 获取路径不匹配 | 改为该检查直接使用 `pyrealsense2` pipeline 同时打开 IR1/IR2/depth；wrapper 的 IR+IMU 由 `for_cuvslam()` 检查覆盖，Jetson 重测全部通过 |
| PR #2 合并后在 Jetson `main` 运行一键验证脚本失败：`No RealSense device found` | 验证 GitHub SSH 和最新 main 后顺手跑脚本 | 不是代码/凭据问题；USB 枚举确认当前 D455 未连接或未被系统识别：`lsusb` 无 `8086:0b5c`，`/dev/video*` 为空，`pyrealsense2 device_count=0`。重新插好 D455 后再运行脚本即可 |
| Isaac ROS 容器内 `isaac_ros_nitros` 构建失败：`nvToolsExt.h` 不存在且链接 `-lnvToolsExt` 失败 | 直接运行基础镜像构建 `isaac_ros_visual_slam` | Jetson host 只装了 CUDA 子集，缺 `cuda-nvtx-11-4`；用 root 安装该包后补齐 `/usr/local/cuda-11.4/targets/aarch64-linux/include/nvToolsExt.h` 和 `lib/libnvToolsExt.so*`，下一步重跑容器构建 |
| 本机 L1-3 检索命令 `brv query` 不存在 | runtime 复杂任务开始前主动查长期记忆 | 当前宿主未暴露 ByteRover MCP，Windows 本机 PATH 也无 `brv`；已记录为工具不可用，继续使用 PWF 和当前上下文推进 |
| `isaac_ros_visual_slam` 最终链接失败：`libcusolver.so.11` missing | NVTX 修复后重跑构建 | Jetson host 同样缺官方 `run_dev.sh` 预期挂载的 CUDA runtime libraries；安装 `cuda-libraries-11-4` 和 `cuda-cupti-11-4` 后补齐 `libcusolver/libcusparse/libcurand/libcufft/libcupti`，构建成功 |
| 构建 runtime 镜像时 `apt-get update` 被过期 Isaac apt repo 打断 | 尝试安装 `ros-humble-realsense2-camera` | 基础镜像内已有可用 package list，改为不执行 `apt-get update`，直接 `apt-get install` 成功安装 RealSense ROS 二进制包 |
| cuVSLAM launch 日志出现 `Delta between current and previous frame ... above threshold [22.000000]` | 运行官方 RealSense launch | 短测仍有 `vo_state=1`、status/odom 输出；该 warning 记录为后续稳定性/时间同步风险，需要运动场景下继续观察 |
| 本机 `git push origin main` 失败：无法连接 `github.com:443` | 尝试从 Windows 本机推送 RViz 启动脚本 | 改用 Git bundle + Jetson 已配置的 GitHub SSH 凭据推送 |
| 本机新增脚本提交基于已过期的 `origin/main=2f5e60d`，Jetson fetch 显示 GitHub `main` 已强制更新到 `0347fbc` | 尝试在 Jetson 导入本机 bundle 并推送同一提交 | 放弃推送旧基底提交；在 Jetson 临时 worktree 基于最新 `origin/main` 重新提交同一脚本并推送为 `4275300` |
| Nav2 smoke test 脚本在 `source /opt/ros/foxy/setup.bash` 时退出：`AMENT_TRACE_SETUP_FILES: unbound variable` | 远端 bash 脚本开了 `set -u` | 去掉 `set -u`，保留 `set -eo pipefail` 后重跑，Nav2 测试正常进入 |
| 远端 smoke test 最后打印 `exit: 0\r: numeric argument required` | PowerShell here-string 通过 SSH 传 bash 脚本时保留 CRLF | 测试主体已输出 `TEST_RC=0`，判定 Nav2 验证有效；后续远端脚本避免把带 CRLF 的变量直接传给 `exit` |

## Notes
- `progress.md` 是项目级 append-only 日志，常规更新不得清空。
- `findings.md` 用于记录阶段性发现；外部资料和搜索结果只允许写入 `findings.md`，不得写入 `task_plan.md`。
- `task_plan.md` 只维护任务阶段、状态、决策和错误。
### Phase 11: cuVSLAM 比赛级定位稳定性调试
- [x] 确认当前用户测试分为 bench 手持相机验证与 robot 装车验收两层
- [x] 修正 `scripts/start_cuvslam_rviz_gui.sh`，增加 `CUVSLAM_MOUNT_MODE=bench|robot` 双模式语义
- [x] 修正 `scripts/cuvslam_loop_metrics_recorder.py`，区分 bench/robot 输出与验收字段
- [x] 修正 README，避免把 `camera_link` 回环结果误当成最终导航合格
- [x] 本地完成 shell/python/diff 检查
- [x] 同步脚本到 Jetson 并完成 bench no-RViz smoke test，确认 recorder 开始采样 odometry
- [x] 完成多轮 bench/chair 带运动实测与官方 launch 对照，确认 cuVSLAM 单源闭合误差约 `0.50-0.57 m`
- [x] 确认官方 NVIDIA launch 未显著优于自定义 wrapper
- [x] 确认该误差量级无法满足用户提出的 `<=0.10 m` 国赛稳定/精确导航目标
- [x] 查 Jetson 上 Isaac ROS Visual SLAM 源码，确认 `slam_path`/`vo_path` 是 `path_max_size=1024` 的滚动 Path topic，不能单独当作完整全局优化轨迹
- [x] 修复启动脚本 false timeout / 自己退出问题：ROS daemon 有时只返回 `/parameter_events` 和 `/rosout`，两个 wrapper 已改用 `ros2 topic list --no-daemon --spin-time 2`
- [x] 扩展 recorder 记录 `/visual_slam/vis/slam_odometry`、`/visual_slam/tracking/vo_pose` 和官方 `visual_slam/get_all_poses` 输出
- [x] 下一次移动测试使用新版 `all_poses_service` / `slam_odometry` 字段判断 SLAM 后端优化轨迹是否真正移动
- [x] 检查带明显起终点标识的 5x6-ish 矩形复测日志 `/home/superwfx666/cuvslam_lite3_logs/20260627-204848`，确认 `slam_odometry` 后端轨迹移动且闭合优于前几轮
- [ ] 保留 robot 模式作为后续融合定位输入验证，不再把 cuVSLAM 单源调参作为达到 10cm 的主路径
- **Status:** backend trajectory instrumentation complete; moving-test validation and fused localization design pending

### Phase 13: 10cm 级融合定位方案设计与实现
- [ ] 梳理现有机器人本体可用定位输入：IMU、机身里程计/速度估计、关节/步态里程计、Nav2 当前 odom 入口
- [x] 检查仓库现有 `robot_localization` / EKF / Nav2 参数和 topic 接口
- [x] 设计 `map -> odom -> base_link` TF 架构，明确 cuVSLAM、EKF、Nav2 各自发布/订阅边界
- [ ] 测量或定义 `base_link -> camera_link` 外参（x/y/z/roll/pitch/yaw）
- [x] 新增或整理 `robot_localization` EKF 配置，优先开启 `two_d_mode`，抑制 Z/roll/pitch 对导航平面定位的污染
- [x] 调研/选择视觉锚点校正方案：AprilTag、ArUco、已知场地标志或 A/B/C/D/仪表盘位置校正
- [x] 固化 Docker cuVSLAM -> UDP localhost -> Host `/odom` bridge，并加入 BEST_EFFORT latency golden probe
- [x] 对 `/odom` bridge 实施 latest-only：QoS depth=1、UDP drain、stale drop
- [x] 制定 Jetson 实测流程：静态外参验证、小矩形 robot 模式、5x6 场地矩形、带锚点校正复测
- [ ] 用 `/odom` latency probe 对比 `planar_60fps` 与较低负载 profile，选择默认比赛 profile
- [ ] 以 `<=0.10 m` 为目标指标，记录每轮误差、轨迹形状、Z 漂移、丢帧/跟踪状态
- **Status:** in_progress

### Phase 14: Lite3/D455 45cm 俯视支架 CAD 调研
- [x] 查询 D455 官方机械安装孔信息
- [x] 查询 Lite3/Lite3-AI 官方载荷孔位信息
- [x] 调研 Agent 生成 3D 打印 CAD/STL 的主流方案
- [x] 给出适合本项目的建模路线和实机复测项
- [x] 按用户实测等腰倒三角孔位生成参数化 CAD/STL
- [x] 生成 PLA Tough 主支架 STL
- [x] 生成 TPU 底部隔振垫 STL 和 D455 背部隔振垫 STL
- [x] 生成结构预览图和设计说明
- [x] 将 PLA 主支架拆成上下两段，增加三销三孔胶粘定位结构
- [x] 为底部三孔增加从上往下插螺丝/螺丝刀的通道
- [x] 调用本地 CAD skill，将旧 STL-first 原型重画为 STEP-first build123d/cadpy 参数化模型
- [x] 生成上下 PLA Tough 主结构、Lite3 底部 TPU 垫、D455 背部 TPU 垫和装配参考的 STEP/STL 文件
- [x] 对 STEP 文件运行 CAD inspect refs/facts/planes/positioning 检查
- [x] 对 assembly、上下 PLA 和 TPU 零件运行 CAD snapshot 并人工检查关键 PNG
- [x] 根据用户反馈将底座改为圆角六角形：Lite3 三孔用于螺丝，180 度反向全等三角形用于三根实心主柱
- [x] 将上下分体插销/插孔移动到三根主柱中心线，并删除旧的中间三插销/插孔方案
- [x] 根据用户最新反馈撤销“顶板靠边”方案：顶部封顶板改为圆角矩形并放回三主柱横截面中心，D455 倾斜安装板居中，光轴向下 30 度，保留三片三角肋支撑
- [x] 将中间上下分体 split cap 从小三角片改为大号圆角六角片，尺寸接近底座轮廓
- [x] 按用户最新反馈仅移动顶部 D455 倾斜安装板和三片三角肋到顶板前缘，保持顶部圆角封顶矩形板及其下方结构不变
- [x] 新增 Lite3 底板螺丝 TPU 防松垫圈：单片 OD 10.0 / ID 2.5 / 厚 1.0 mm，并生成三孔排布 STEP/STL
- [x] 将三片垫圈加入完整装配参考，位置为底座沉孔底部 `z=5.0..6.0 mm`
- [x] 对垫圈和更新后的 assembly 运行 CAD inspect 与 snapshot 复核
- [ ] 实物打印前用切片软件复核孔位、支撑和螺丝长度
- [ ] 在 SolidWorks 2025 中导入 STEP，按实际螺丝、线缆和 D455 机身空间做最终人工复核
- **Status:** rev8 screw TPU washers tightened to ID 2.5 mm and regenerated; SolidWorks/import, slicing, and physical fit-check pending

### Phase 15: 比赛技术报告撰写与编译
- [x] 阅读 `技术报告/technical_report_scoring_rubric.md` 并提炼评分关注点
- [x] 梳理仓库当前 SLAM、导航、感知、任务管理、语音播报、机械结构与部署材料
- [x] 生成技术报告 LaTeX 主文件，明确机械臂部分待补
- [x] 按用户早期要求撤掉照片/截图类图片和 TikZ 内容
- [x] 根据用户最新要求新增单独封面，并用 Mermaid 绘制总体链路、并行感知/任务链路
- [x] 根据 Isaac ROS/cuVSLAM 版本约束修订 Docker 技术选择段落
- [x] 删除正式报告中评分细则、评分响应和工作区元叙述痕迹
- [x] 本地编译 PDF，保留日志和中间文件在 `技术报告/`
- [x] 检查 PDF 产物与源码目录结构，记录完成情况
- **Status:** complete

### Phase 16: Navigation/Nav2 恢复分支与 Jetson 当前状态评估
- [x] 读取 PWF 三件套并恢复 Navigation 历史上下文
- [x] 确认 GitHub 存在 `feature/nav2-restoration`，commit `72c23a3`
- [x] 确认 Jetson 当前工作区仍停在旧 `main` `82512c6`，且 `main...origin/main [ahead 20, behind 37]`、大量未跟踪集成文件存在
- [x] 确认 Jetson 当前 runtime 只有 cuVSLAM 容器和相机/SLAM topic，没有 host `/odom`、Nav2 lifecycle 节点或 competition launch
- [x] 确认 Jetson 已安装 ROS2 Foxy Nav2 官方包和 depth/image pipeline 依赖
- [x] 对 `feature/nav2-restoration` 做轻量静态检查：Python `compileall`、`bash -n scripts/start_competition.sh`、`bash -n scripts/stop_all.sh` 均通过
- [x] 识别 `feature/nav2-restoration` 的主要缺口：Foxy Nav2 参数不兼容、launch/package 路径与重复节点问题、分支未包含最新 `origin/main` 两个提交、提交中含 `tmp/` 调试输出
- [x] 基于最新 `origin/main` 新建干净 Nav2 集成分支 `Stonefield/nav2-foxy-dwb-integration`，选择性移植 `feature/nav2-restoration` 有效内容
- [x] 修正 Foxy 兼容 Nav2 参数和 launch：`recoveries_server`、Foxy BT 参数、controller goal checker、lifecycle `node_names`
- [x] 修正 package/install 路径，避免 package launch 引用源码 `src/` 路径或遗漏 `configs/ros`
- [x] 在隔离 `ROS_DOMAIN_ID`、假 `/odom`/TF 下完成 Nav2 纯软件 smoke test：lifecycle active、goal accepted、DWB 发布非零 `/cmd_vel`
- [x] 修正 `cuvslam_bridge.py`：输入为 `camera_link` 时应用 `base_link -> camera_link` 外参，输出真正的 `odom -> base_link`
- [x] 将 `base_link -> camera_link` 工程初始外参固化为 `x=0.080, y=0.000, z=0.493, roll=0, pitch=-0.523599, yaw=0`
- [x] 用真实 cuVSLAM host `/odom` bridge 替换假 `/odom`/TF，继续保持 `enable_cmd_vel_bridge:=false` 做 dry-run
- [x] 完成“无狗 dry-run”：真实 cuVSLAM `/odom` + Nav2 DWB goal accepted + `/cmd_vel` 非零输出
- [x] 新增轻量 `/plan` probe：发送 NavigateToPose goal 后抓取 Nav2 `/plan`，默认只捕获第一条非空 Path，保存 CSV/SVG 和 summary JSON
- [x] 在 Stonefield worktree 新增 Lite3 UDP smoke、`/odom` 方向 probe、depth safety gate probe，并将 `cmd_vel_bridge.py` 改为固定频率 ZOH 输出与超时 stop
- [x] 用户完成 SSH 授权后，将上述实测闭环工具同步到 Jetson Stonefield worktree，并完成远端 py_compile、脚本 help 与 SHA256 一致性验证
- [x] 执行 Lite3 UDP smoke dry-run：未加 `--armed`，未发送真实 UDP，脚本序列输出正常
- [x] 执行 Lite3 UDP 极低速 `--armed` smoke：`vx=0.02`、`az=0.05`、短时命令保持，脚本完整返回并发送 final stop；用户现场复测确认机器狗已动起来
- [x] 启动真实 cuVSLAM + Host final bridge 后执行 `/odom` 方向 probe；正向 Lite3 命令得到 `dx=-0.0398m`、`dy=0.0017m`、`dyaw=0.22deg`
- [x] 修正或补偿 Host `/odom` 前向轴符号/坐标系：`final_bridge.py` 最终默认只翻转 pose 平移 X/Y，保留 orientation，使正向运动 `dx` 为正且 Nav2 起点 yaw 保持约 180°
- [x] 在 Jetson Nav2 dry-run 场景实跑 `/plan` probe：目标 `(4.8, 0.75, 0)`，goal accepted，捕获 46 点路径，长度约 `0.585355m`
- [x] 在 Jetson Nav2 dry-run 场景实跑 `/cmd_vel` probe：clean session 下 goal accepted，`cmd_count=76`、`nonzero_count=76`、`max_linear_x=0.22m/s`、`max_abs_angular_z=0.07105rad/s`，`enable_cmd_vel_bridge=false`
- [x] 执行无障碍低速 live loop 首测：`enable_cmd_vel_bridge=true`，目标 `(4.85,0.75,0)`，goal accepted，`cmd_count=121`、`nonzero_count=120`、`max_linear_x=0.10m/s`；执行中 Nav2 报 robot out of global costmap 并 cancel
- [ ] 复核 DWB 角速度限制：配置已设 `max_vel_theta=0.15`，但 live probe 观测到 `max_abs_angular_z=0.45rad/s`
- [ ] 下一轮 live 只发 0.15-0.20m 短目标，并同时记录 `map->base_link` 轨迹，判断实机运动方向与 map 坐标变化是否一致
- [ ] 修正动态障碍/深度链路：不要让 Host `depth_publisher` 直接打开已被 Docker/cuVSLAM 占用的 D455，改走 Docker depth relay 或后续 local costmap 输入
- [ ] 按顺序执行 Lite3 UDP dry-run、上架低速 `--armed`、`/odom` 方向 probe、depth safety gate probe；每一步成功后再进入下一步
- [ ] 按“狗上架低速 -> 场地分阶段”执行 Nav2 实测
- **Status:** in_progress

### Phase 17: 技术报告 cuVSLAM 轨迹图替换
- [x] 核对 Jetson 最新 cuVSLAM 日志目录与本机 CSV 副本
- [x] 用 `vo_pose_samples.csv` 和 `slam_all_poses_latest.csv` 生成优化前/后轨迹图
- [x] 将原图 7 占位替换为实际轨迹图
- [x] 在正文中说明本次采集路线未回到起点，因此不以闭合误差作为该轮评价指标
- [x] 重新编译并目检技术报告 PDF
- **Status:** complete

### Phase 18: 技术报告指定图号 Eraser 重绘
- [x] 确认用户指定的是报告第 2、9、10、11、12 张图，而不是连续范围表达。
- [x] 从 `technical_report.pdf` 抽取真实图注编号，确认第 8 张为栅格地图，不在本次指定图号内。
- [x] 定位五张图的 Mermaid 源逻辑：`system_pipeline.mmd`、`astar_algorithm.mmd`、`dwb_algorithm.mmd`、`rpp_control_algorithm.mmd`、`robot_navigation_chain.mmd`。
- [ ] 调用 Eraser MCP 重画五张图并导出替换报告图源。
- **Status:** blocked by missing Eraser MCP tools in current Codex session

### Phase 19: 技术报告 DWB/RPP 理想轨迹图
- [x] 读取 PWF 三件套和最新 cuVSLAM CSV 记录。
- [x] 确认本图只以 `slam_all_poses_latest.csv` 的 SLAM path 作为基准，不再绘制 VO。
- [x] 调研 DWB 与 Regulated Pure Pursuit 在 Nav2 中的理想轨迹形态。
- [x] 生成 SLAM path + DWB 局部优化 + RPP 跟踪三线对比图。
- [x] 接入 `technical_report.tex` 的“地图、导航规划与控制算法”章节并重新编译检查。
- **Status:** complete

### Phase 20: Nav2 贴边起点安全复测
- [x] 核对实际 global/local footprint 是否仍有重复顶点
- [x] 将 recovery Spin 速度和加速度收紧到短距离诊断范围
- [x] 新增只读 `map -> base_link` 轨迹记录工具
- [x] 在 Jetson 执行 D455/cuVSLAM 输入短测，RGB/depth/IR/IMU 均通过
- [x] 修正运行判据：`/visual_slam/status` 缺失不等于 odometry 不可用；以 `/visual_slam/tracking/odometry` 和 Host `/odom` 为导航前提
- [x] 修复 cuVSLAM `/visual_slam/status` 启动健康检查超时：odometry 为必需条件，status 缺失仅告警
- [x] 执行两轮无 Nav2 goal 的 Lite3 正向方向采样（`0.02m/s`、`0.03m/s`，均 1 秒）
- [x] 用纯软件跨进程 probe 证明原版 bridge `/odom` 与 TF 发布正常；排除 executor starvation、heartbeat 和 QoS 固有缺陷
- [x] 按 NVIDIA 官方参数实测 D455 IR1/IR2 约 89.4Hz、IMU 约 180Hz，排除相机实际降到 30FPS
- [x] 确认官方 camera-link launch 可发布 odometry，delta warning 与可用 odometry可同时存在
- [ ] 按 NVIDIA 官方验证流程断开动力，人工直线移动 1m，验收平移 `0.95-1.05m` 与方向误差小于 15 度（2026-07-11 趴地拖行得到 XY 约 0.644m、3D 约 0.873m，但 Z 约 0.590m，未通过平面导航语义验收）
- [x] 将旧 bridge 的标准刚体位姿/twist转换迁移进 UDP final bridge：camera 转换、base 透传、未知 frame 拒绝
- [x] 删除默认 translation-only X/Y flip，并完成 Jetson 数值探针与 UDP/TF 跨进程回归
- [x] 只启动真实 cuVSLAM + final bridge，同步核对 Docker 原始 odometry 与 Host `/odom` 的 frame、位置、姿态和 transform mode
- [x] 修正 `base_link -> camera_link` pitch 符号：向下 30 度在 ROS camera_link 语义下应为 `+0.523599`，不是 `-0.523599`
- [x] 验证官方 camera-link cuVSLAM baseline 可出 `/visual_slam/tracking/odometry`
- [x] 验证 Host `final_bridge.py` 对官方 camera-link 输入走 `camera_to_base` 分支
- [x] 完成无动力拖行 CSV 分析，确认 camera-to-base 后仍有显著 Z 投影
- [x] 完成站立启动/推动复测，确认 X/Z 耦合未改善且 Z 泄漏比例更高
- [x] 创建 checkpoint commit `867c8ff`，便于回滚到已验证的 frame diagnostics 状态
- [x] 新增并实测 `--camera-world-rebase base_start --planarize-output` 平面 odom 输出
- [x] 将平面 odom 直接接入 Nav2 dry-run：`final_bridge.py --camera-world-rebase base_start --planarize-output` 发布唯一 `/odom` 与 `odom -> base_link`，EKF 暂缓
- [x] 修正 `start_competition.sh` 安全默认：关闭 task_manager/auto_advance、`cmd_vel_bridge` 和 Host `depth_publisher`，防止 dry-run 自动发任务 goal 或抢占 D455
- [x] 在 Jetson 用短距离、保持 `yaw=pi` 的目标做无下发 dry-run：0.22m goal accepted，`/plan` 长约 0.230m，`/cmd_vel` 有线速度且角速度很小
- [x] 新增 `--cmd-vel-bridge` 显式 fallback，用于 transfer workspace 未构建时启动直接 UDP `/cmd_vel` 桥接
- [x] 在 Jetson 上架/低速 live 尝试 0.18m 目标，保持 `yaw=pi`：Nav2 输出线速度、角速度很小且无原地转圈型命令
- [x] 发现 `cmd_vel_bridge` 默认自动初始化狗会带来姿态变化风险；已改为默认 `init_dog=false`，仅通过显式 `--bridge-init-dog` 进入 auto/motion 初始化
- [x] 给 `cmd_vel_bridge.py` 增加 ROS env、`/cmd_vel` 接收和 UDP 发送节流诊断日志，并在 Jetson `dog_ip=127.0.0.1` 假目标回归通过
- [x] Clean single-shot 0.5m Nav2 goal 诊断确认：`/cmd_vel_bridge_node` 收到非零 `/cmd_vel` 并持续发送 Lite3 UDP，`udp_errors=0`
- [x] 结合现场观察确认 Lite3 运动门槛：独立握手脚本发送 heartbeat + `0x21010C03` + `0x21010D06` + 官方三轴速度后，用户确认狗已移动
- [x] 将 Lite3 motion mode 握手封装成独立显式准备步骤，避免 `cmd_vel_bridge` 默认切模式或发送起立/趴下 toggle
- [x] 现场确认狗站稳后，运行 `start_competition.sh --dog --cmd-vel-bridge --prepare-lite3-motion` 并完成 0.5m 直发 `/cmd_vel` 闭环，用户确认狗实际前进约 0.5m
- [x] 按历史 clean single-shot 规程复测 `NavigateToPose` 0.5m：不混跑 `/plan`/direct FollowPath probe 后，`cmd_count=78`、`nonzero_count=77`，未复现 `cmd_count=0` 型 `send_goal failed`
- [x] 用户现场确认 clean single-shot 0.5m Nav2 真机闭环已 OK
- [ ] 将 clean single-shot 规程固化到后续 Nav2 真机测试步骤中，避免同 session 混跑 action/probe 污染 BT Navigator 状态
- [x] 推进下一档真机测试：按当前 `map->base_link≈(5.371,0.771,yaw≈pi)` 发布前方 1.0m 目标 `(4.371,0.771,yaw=pi)`，Nav2 accepted，`cmd_count=152`、`nonzero_count=151`、`max_linear_x=0.1m/s`、`max_abs_angular_z=0.15rad/s`，停止后 planar odom 约 `x=0.813m,y=0.026m,z=0`
- [x] 用户现场确认 1.0m 目标测试的实际行走距离/方向正确
- [x] 分段航点首测：同一启动栈内连续发布 `0.8m + 0.8m`，第一段 accepted 且 `/cmd_vel` 正常输出，第二段 accepted 但 `cmd_count=0`、`nonzero_count=0`
- [x] 新增连续航点自然完成 probe：避免用固定采样后 cancel 的旧脚本模拟连续任务
- [x] 将连续航点自然完成 probe 同步到 Jetson Stonefield worktree，并完成 ROS 环境下 `--help`/SHA256 无运动验证
- [x] 在 Jetson clean 启动栈下运行连续航点自然完成 probe，确认第二段已能进入 controller 并输出非零 `/cmd_vel`
- [x] 给连续航点 probe 增加逐条 `/cmd_vel` CSV，并复测 `0.5m + 等待 + 0.25m`
- [ ] 定位连续航点第二段自然 goal 中途 `ABORTED` 的原因：优先检查 DWB progress/oscillation、第一段 success 后 TF/yaw 稳定等待、第二段目标距离和 BT/controller 详细日志
- [ ] 先复核 clean 启动后 `linear.x > 0` 对 `map->base_link` 的方向，确认本轮 Nav2 命令前进但 map `x` 反向变化的根因
- **Status:** in_progress

### Phase 21: Navigation-only 全目标路线跑通
- [x] 明确策略：先只跑 Navigation-only，全目标可达后再接 RGB/depth/YOLO/仪表链路；cuVSLAM IR+IMU 保留
- [x] 将任务 waypoint 改为 Nav2 `base_link` 中心/接近点，而不是物体/区域语义中心
- [x] 修正场地坐标 yaw 到 ROS map yaw 的符号转换，避免上下观察位朝向反掉
- [x] 新增 `nav2_waypoint_sequence_probe.py --route-preset nav-only-full` 与 `nav-only-inspection`
- [x] 将 task_manager 的 Phase2 地图切换推迟到到达 `pos1_middle` 后
- [x] 本地完成 `py_compile`、waypoint 坐标打印和 footprint 静态墙体检查
- [x] 同步 Nav2 worktree 改动到 Jetson 并执行 `py_compile` / `colcon build`
- [ ] 先跑无狗 dry-run：`--route-preset nav-only-inspection`
- [ ] 用户现场确认狗站稳和路线安全后，跑真机 `nav-only-inspection`
- [x] 根据 2026-07-27 14:21 结果调整/分段 `pos1_middle` 进场：第 1 段已成功，第 2 段中途 abort
- [x] 按 2026-07-27 Navigation-only 规程真机执行 `--route-preset nav-only-full` 一次：第 1 段 `obstacle_cross_target` 和第 2 段 `pos1_middle` 成功，第 3 段 `pos1_middle_turned` 近原地转身 `ABORTED`
- [x] 定位第 3 段 abort 根因：DWB `RotateToGoal` 进入末端旋转状态后禁止平移纠偏，Lite3 转身 XY 漂移导致越转越偏，最终 abort
- [x] 在 `nav2_waypoint_sequence_probe.py` 中用 staged turn 路线替换同点 180° 转身，默认 `nav-only-full` / `nav-only-inspection` preset 已切换，并保留 `*-legacy-same-spot-turn` 诊断 preset
- [x] 在 `navigation_client.py` 中新增 `pos1_turnout_right` 过渡航点 `(1900,2550,0°)` → ROS `(1.90,3.45,0)`，`pos1_middle_turned` 改为 `(1900,2750,90°)` → ROS `(1.90,3.25,-π/2)`
- [x] 在 `task_manager.py` 中 `_inspection_steps` 插入 `pos1_turnout_right` 过渡步骤（`transit=True` 跳过拍照识别），修正硬编码 `/4` 为动态长度，并确保发出 Nav2 goal 后等待 result 成功才识别或推进
- [x] 本地 `py_compile` 三文件全部通过，离线 PGM footprint 采样显示 staged waypoint 在 phase1/phase2 均 clear
- [x] Jetson SSH 恢复后，同步 staged-turn 改动到 `/home/superwfx666/quadruped-robot-competition-nav2-dwb` 并执行远端 `python3 -m py_compile` / 必要时 `colcon build`
- [x] 2026-07-27 21:00 复跑真机 `nav-only-full` 当前 staged preset：第 1 段成功，第 2 段 `pos1_middle` 在约 `0.213m` 位移后 `ABORTED`，未进入 `pos1_turnout_right`
- [x] 按用户要求 revert 提交 `09d4609ca14438bba84ba1b5c53b618994a6a3bf`，生成本地提交 `43c2015`，默认 route 恢复到第一段/第二段基线，第三段同点转身问题保留为待定位对象
- [x] 将本地 revert `43c2015` 同步到 Jetson 并重新 build 后，复测基线 `nav-only-full`：第 1 段成功，第 2 段仍 `ABORTED`，本轮未进入第 3 段
- [ ] 定位为何 `5f1fb59` 文件基线下第 2 段仍会偶发/复现 `ABORTED`：优先检查起点姿态、第二段路径/local costmap、DWB critic/progress 日志和柜体左下角 inflation 余量
- [x] 按用户要求先将 local/global Nav2 footprint 从 `0.70m x 0.50m` 进一步收为 `0.60m x 0.50m`，并同步 Jetson、完成远端 build；暂未复测
- [x] 2026-07-29 以 `0.60m x 0.50m` footprint clean 复测 `nav-only-full`：第 1 段即 `ABORTED`；route probe 采样 `/cmd_vel=0`，但 bridge 日志显示实际收到并下发 62 条非零命令，需后续对齐 action/controller/probe 时序
- [x] 2026-07-29 discard footprint 实验并恢复 `0.70m x 0.50m` 后 clean 复跑 `nav-only-full`：第 1 段 `obstacle_cross_target` 成功，第 2 段 `pos1_middle` accepted 后立即 `ABORTED`；已零速停栈并清理远端残留，本轮未改其他参数或代码
- [ ] 跑真机 `nav-only-inspection` staged turn 路线，确认第 3-4 段不再 abort
- [x] 在保持 legacy preset 不变的前提下新增独立 `nav-only-inspection-staged` / `nav-only-full-staged`，使用显式 yaw 的两段移动转弯
- [x] 本地完成语法、preset 回归和 phase1/phase2 footprint 静态检查，并同步单个 probe 脚本到 Jetson 做无运动加载验证
- [ ] 按 clean 规程真机运行 `nav-only-inspection-staged`，重点验证 `pos1_turnout_right` 与新的 `pos1_middle_turned`
- [x] 首次真机尝试 `nav-only-inspection-staged`：第 1 段成功，第 2 段已到目标附近但随机 `send_goal failed`，未进入 staged 转弯点
- [x] 从源码 overlay 修复 Foxy BT 子 action 10ms timeout，并回移异常后的 action halt/清理
- [x] Jetson 独立 overlay 完成两包 Release 构建、新增异常回归测试及 copyright/cpplint/uncrustify 检查
- [x] 无运动 smoke 验证 overlay 可执行文件/动态库实际加载、100ms 参数生效、goal accepted 且 cancel 正常
- [x] action 修复验证通过后重新 clean 运行 `nav-only-inspection-staged`：第 1 段成功，第 2 段 120s 超时取消；本轮无 `send_goal failed`，action overlay 修复通过真机压力验证
- [x] 在 staged 测试路线中给第 2 段增加柜体左侧净空航点 `pos1_left_clear=(0.60,2.90,pi/2)`，绕开本轮首次规划失败位置 `(0.77, 2.59)`；本地/Jetson 静态验证通过
- [x] 机器狗回到起点且现场确认安全后，clean 复测更新后的 `nav-only-inspection-staged`：前三段全部成功，首次稳定进入 `pos1_turnout_right`
- [x] 根据 `pos1_turnout_right` 的实测越调轨迹重设计移动式 180 度转身：两段经验四分之一转向 + 一段朝南接近，并给 probe 增加可选无恢复 BT
- [x] 机器狗人工回到起点后，用无恢复 BT clean 复测新的三段移动式转身：前三段成功，第一个四分之一转向点因漂移后全局规划失败而 abort；确认无 Spin recovery
- [ ] 评估并选择下一版转向方式：基于实时起始位姿的闭环运动原语，或距离更长、对终点容差更鲁棒的 Nav2 路线；不要继续沿用固定近距离绝对转弯点
- [ ] inspection 段稳定后，跑真机 `nav-only-full` 到抓取区与 A/B/C/D 放置接近点
- **Status:** in_progress

### Phase 22: 最新真机路线地图可视化
- [x] 核对 2026-07-30 最新运行的逐点轨迹与目标点
- [x] 核对比赛场地图几何、坐标系和障碍物位置
- [x] 叠加计划路线、实际轨迹、成功段与失败点
- [x] 在对话中展示并验证路线图布局与交互
- [x] 更新为三视图交互图：当前 `nav-only-full-se2` 闭环路线、最新真机实测、叠加对比
- [x] 使用本机 Chrome 验证桌面与 390px 窄屏布局、按钮状态和无横向溢出
- **Status:** complete

## Visualization Task Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 追加阶段时使用了错误的 Phase 20 标题，`apply_patch` 未找到上下文 | 1 | 读取文件尾部确认现有 Phase 21 后，改为在文件末尾追加 Phase 22 |
| 全仓 `rg` 递归检索进入 `.cad-deps` 时遇到访问拒绝并以状态 1 退出 | 1 | 将后续检索收窄到 Nav2 worktree 的 `navi/`、`scripts/`、`src/` |
| 当前 Codex 网络权限拒绝 SSH 读取 Jetson 最新 `trace.csv` | 1 | 使用本地 PWF 的实测摘要，只画已确认关键点并明确不冒充 5 Hz 完整轨迹 |
| 首次调用 `render.py` 使用了错误的插件层级路径 | 1 | 定位到 `skills/visualize/scripts/render.py` 后成功生成预览 |
| 首轮并行 Edge headless 截图共享临时 GPU 缓存并异常退出 | 1 | 为桌面/窄屏分别使用独立 user-data-dir 和禁用 GPU 的参数，截图成功 |
| Playwright 包存在但默认 Chromium executable 未安装 | 1 | 改用系统已安装的 Chrome `chrome.exe` 做无网络预览验证 |
| standalone renderer 把 fragment 放在 iframe 中，顶层 locator 找不到按钮 | 1 | 定位子 frame 后验证三按钮切换、图层 opacity 和详情文本 |
| Playwright 页面级截图等待字体超过短 timeout | 1 | 改为对子 frame 内的可视化根节点截图，并在切换后等待 CSS transition 完成 |

### Phase 23: 四足机器人闭环转向与轨迹跟踪方案重构
- [x] 查询 L1-3 中与 Lite3 转向漂移、Nav2 控制器和闭环运动原语相关的历史（当前宿主无 ByteRover MCP/CLI，已记录不可用）
- [x] 联网核对 Nav2 官方控制器、四足机器人 ROS 2 导航实践和适用版本
- [x] 对比 DWB、MPPI、RPP、独立 SE(2) 闭环运动原语与路径跟踪器
- [x] 基于当前 Foxy/Jetson/Lite3 约束提出并选定混合闭环架构
- [x] 实现最小可验证版本并完成纯控制器、仲裁状态机、语法和静态检查
- [x] 在 Jetson 重建并验证 `/cmd_vel` 单发布者、仲裁 topic 图和无运动 dry-run
- [x] 将生产 `nav-only-full` / `nav-only-inspection` 的同点 U-turn 改为 `yaw_only` precision 接管，并保留显式 DWB baseline preset
- [x] 本机与 Jetson 完成 15/15 测试、Python 3.8 兼容、route kind 断言、`colcon build` 和无狗 ROS 图复核
- [ ] 现场确认机器狗位于官方起点、站稳且前两段及转向走廊完全净空后，只运行“前两段 + yaw-only”真机验证；不得直接继续完整 A/B/C/D 路线
- [x] 分析首轮 yaw-only 真机失败，确认控制/仲裁正确而 probe 单线程 callback 饥饿造成 TF 假陈旧
- [x] 将 TF 更新与高频 cmd/odom callback 解耦，增加调度压力回归测试和 stale hold trace，并在 Jetson 完成 60Hz TF/odom + 40Hz cmd 压力验证
- [x] 精确清理 callback 验证遗留的 cuVSLAM exporter，确认无 `final_bridge`、Nav2 probe、cmd bridge 或 motion sender 残留，并保持既有 cuVSLAM 容器运行
- [ ] 调度修复通过后，重新执行“前两段 + yaw-only”最小真机验证；在此之前不放宽安全门限直接重跑
- [x] clean 重跑三段验证与用户明确要求的完整路线；两轮均在第 2 段 `pos1_middle` 提前 abort，确认 callback 修复后当前阻塞已前移到第 2 段全局路径生成
- [ ] 分析 `obstacle_cross_target -> pos1_middle` 的 global costmap、规划失败位姿和可达走廊，设计中间航点后再做最小复测
- [x] 将两轮真实轨迹与 phase1 地图几何对照，选定左通道清障航点 `pos1_left_clear=(0.60,2.90,pi/2)`
- [x] 将清障航点接入 production / DWB baseline 前缀，更新 route 断言并完成本机与 Jetson 验证
- [ ] 从官方起点 clean 运行四段 `obstacle_cross_target -> pos1_left_clear -> pos1_middle -> yaw_only`，核对通道箱体实际间距与是否稳定通过第 2/3 段
- [x] 按用户要求运行完整 11 航点：确认 `pos1_left_clear` 成功并显著增加箱体间距；第 3 段 `pos1_middle` 130 秒超时，后续未执行
- [ ] 针对 `(0.60,2.90,yaw≈pi/2) -> (1.50,3.25,pi/2)` 设计不依赖 DWB 大弧线的位置过渡，再做第 3/4 段最小验证
- [x] 新增隔离的 `nav-only-split-y-validation` 实验路线：两个观察位沿 Y 分离 0.30m，并通过右侧矩形过渡把 180° 分解为不超过 90° 的相邻转向；不修改生产 `nav-only-full`
- [x] 用 phase1 占据地图验证实验路线和 0.70×0.50m footprint 的最小净距，并在 Jetson 完成 17/17 ROS 测试、路线/无 Spin BT 断言与构建
- [ ] 现场确认机器狗位于官方起点、站稳，且左侧通道、两柜中间走廊及 `x=2.60,y=3.10..3.40` 右侧矩形过渡路径全部净空后，运行 `nav-only-split-y-validation`；不得直接接后续全路线
- [x] 按用户明确要求 clean 运行生产 `nav-only-full`：前三段成功，第 4 段 yaw-only 因 cuVSLAM anchor 位移 `0.302m` 触发安全退出，未进入第 5-11 段；全栈与容器已清理
- [x] 场地净空后只做一次低速 `CODE_LAT` 正方向脉冲，确认使用 `--se2-vy-sign 1`
- [x] 首次 `nav-only-full-se2` 完成前三段，SE(2) 因 TF age `0.234s` 安全停止；resume 复测确认三轴控制方向正确、位置误差最低约 `0.027m`，但再次因 TF age `0.321s` 停止
- [x] Jetson 重启后从官方起点 clean 运行：前两段成功，第三段 `pos1_middle` 因 DWB 转向漂移在 130s 后取消；同栈 SE(2) 走廊恢复成功，右上/右下巡检点也成功
- [ ] 现场确认下巡检柜右侧净空后，设计并验证朝 `+X` 脱离及 `grab_area_approach` 的混合闭环过渡，再继续 A/B/C/D；当前停止位姿约 `(2.212,2.174,0.725)`
- [x] 用户现场报告机器狗已接触柜体后，立即执行三轮 Lite3 底层 UDP 三轴零速、`stop_all.sh`、停止 cuVSLAM Docker 容器，并核查无导航/运动进程或运行中容器残留
- [ ] 仅在人工确认机器狗完全静止、柜体不再受力并手动移回安全净空位置后，重新设计路线；禁止从当前接触位姿自动脱困或续跑
- [x] 在空旷区域执行一次开发接口最小纯 yaw 脉冲：`vx=0, vy=0, az=0.05rad/s` 持续 `0.5s`，动作前后均发送三轴零速；接口执行成功，待用户反馈肉眼运动现象
- [x] 按用户要求将同一开发接口纯 yaw 脉冲延长到 `5.0s`：`vx=0, vy=0, az=0.05rad/s`，理论转角约 `14.3deg`；动作和零速收尾成功，用户现场确认看起来是纯转弯、无明显漂移
- [x] 在 `DOG=false`、`CMD_VEL_BRIDGE=false`、`/cmd_vel` 无订阅者条件下开启 cuVSLAM，重复开发接口 5 秒纯 yaw 并保存 bridge 原始/Host 位姿：转角约 `14.9deg`，Host 在转动窗口报告约 `0.130m` 平移，停止后稳定偏移约 `0.172m`
- [ ] 优先区分 cuVSLAM 原始 camera pose 与 `camera_to_base + base_start` 外参转换各自引入的平移；当前不得把报告位移直接归因于 Lite3 底层或 Nav2 混入线速度
- [x] 用户现场确认 cuVSLAM 量化轮仍只有肉眼旋转、无约 `13-17cm` 实际平移；将问题正式收窄为定位 frame/外参链伪位移
- [x] 核对上一轮生成 launch：`force_planar_mode=True`、`base_frame=camera_link`、`input_base_frame=''`、`input_left_camera_frame=camera_link`、IMU fusion 开启；日志无 tracking lost/ERROR
- [x] 保持 `planar_60fps`、IMU、相机、bridge、外参和 5 秒 `az=0.05rad/s` 不变，仅设置 `CUVSLAM_FORCE_PLANAR_MODE=false` 做有效单变量 A/B；Lite3 底层确认实际转动约 `14.435deg`，cuVSLAM yaw 约 `14.911deg`
- [x] 完成 A/B 输入链路统计：false 轮 raw/Host 稳定净位移约 `0.1269/0.1295m`，tracking lost/ERROR 均为 0，frame-delta 约 `132.57/min`，D455 Motion Module failure 2 次；关闭 planar constraint 未消除伪平移
- [x] 增加 Lite3 `43897/UDP` 只读状态记录，按真机 212 字节 RobotState / 60 字节 HandleState ABI 保存 `rpy/pos_world/goal_vel_yaw`，本机与 Jetson 测试通过
- [x] 用底层状态独立复核一次 5 秒 yaw：`RobotState` yaw 只波动 `0.0384deg`、`HandleState.goal_vel_yaw` 始终为 0，确认 false 轮没有实际运动刺激
- [x] 不发送 stand/lie toggle，用正式 `prepare_lite3_motion_mode.py` 的长时 heartbeat + auto + motion + zero 序列记录 2400 帧状态；组合始终为 `basic=1,gait=0,motion=0`
- [x] 由现场在 Lite3 App/遥控端切换到可接受 SDK 速度命令的 Auto/Motion 状态并确认站稳；底层状态记录确认 `goal_vel_yaw` 非零持续约 5 秒、Lite3 yaw 变化约 `14.435deg`
- [x] 离线分解 Lite3 `pos_world + yaw`、`base_link -> camera_link=(0.08,0,0.493,pitch=+30deg)` 和 cuVSLAM raw pose：IMU-on 轮理论 camera 刚体位移约 `0.0655m`，只能解释 raw `0.1269m` 的约一半
- [x] 核对 NVIDIA `release-2.1` 的 IMU frame/外参要求，并以 `enable_imu_fusion=false` 完成单变量真机 A/B；IMU-off raw/Host 稳态位移约 `0.1497/0.1522m`，未消除伪平移
- [x] 核对官方 RealSense launch 留空 `input_left_camera_frame` 与当前显式 `camera_link` 的源码行为：两者均得到 identity base-to-left 和相同 IMU TF 路径，不做无效真机 A/B
- [x] 检索 NVIDIA 官方仓库 D455 drift/frame 已知问题；emitter 已关闭，下一项选择官方 `640x360x90` 帧率单变量 A/B
- [x] 保持 `force_planar_mode=false`、IMU fusion、frame/bridge 和纯 yaw 规格不变，只将 IR 从 60 FPS 改为 90 FPS；raw/Host 稳态位移降至约 `0.1175/0.1209m`，改善有限且 frame-delta 升至约 `189/min`
- [x] 在 90 FPS + IMU-on + planar-off 同一定位会话内完成 `+0.05rad/s 5s -> 零速 -> -0.05rad/s 5s` 闭合测试：Lite3 净 XY 位移 `10.53cm`、净 yaw `0.94deg`，cuVSLAM raw/Host 净位移 `23.69/23.66cm`、Host 净 yaw `1.56deg`；两种转向均累加同向平移，VSLAM 未闭合且步态/底层里程计漂移占显著部分
- [ ] 使用独立于 Lite3 `pos_world` 和 cuVSLAM 的外部物理基准量测同一正反 yaw 前后机身中心净位移；在真值确认前不按 `10.5cm` 或 `23.7cm` 直接写入控制补偿
- [ ] 遥控器纯 yaw A/B 降为后置标定项；仅在 frame/外参链路核清后仍需比较两种入口时再执行
- [x] 新增 `nav2_yaw_takeover` 复合段：距离 `pos1_middle` 进入 `0.20-0.25m` 阈值后由 precision 零速取得 lease，确认最终 `/cmd_vel` 停稳，再取消当前 Nav2 action
- [x] 新增固定实时 XY 锚点的 yaw-only 控制：大角度期间严格 `vx=vy=0`，首轮 `|wz|<=0.08rad/s`，yaw 连续稳定后保持零速并释放 lease
- [x] 将生产 `nav-only-full` / `nav-only-inspection` 切到显式复合接管，保留旧 `NavigateToPose` 同点转身为 `*-dwb-baseline`，增加三段最小验证 preset
- [x] 完成本机控制器/仲裁/路线静态回归、Python 3.8 语法检查和 diff 检查，并在 Jetson 隔离副本完成无运动 Python 3.8/route 验证；生产 worktree `colcon build` 因在线栈占用暂 pending，不运行旧 `nav-only-full`
- [x] 停止 Jetson 旧生产导航栈，备份并同步接管实现，完成远端 Python 3.8 测试与限定路径 `colcon build`
- [ ] 现场手动将 Lite3 放回官方起点约 `(4.65,0.75,pi)`，确认站稳、完整路线净空且急停人员就位后，冷启动新栈并验证 `/cmd_vel_arbiter/mode`、唯一速度出口，再运行完整 `nav-only-full`
- **Status:** in_progress

### Phase 23 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 对 `start_competition.sh --help` 的探测因脚本没有 help 分支而进入默认无狗/无 cmd bridge 启动 | 1 | 未发送 goal、`/cmd_vel` 无运动订阅；立即用 `stop_all.sh` 完整清理，后续按源码已确认参数启动 |
| 旧栈批量 lifecycle 查询在 ROS discovery 中超时 | 1 | 不复用旧栈；依据节点图、缺失 mode topic 和 TF 证据停止旧栈，重新部署构建 |
| 接管参数组首个补丁假设基线已含历史 yaw-only 参数，context 校验失败 | 1 | 未写入该补丁；按当前 `1efbcd6` 参数区拆分新增 `--describe-route`、takeover 和 yaw-only 参数 |
| 新增路线契约测试的 AST 求值器不支持既有 `_INSPECTION_PREFIX_SE2[3:]` 切片，2 项测试失败 | 1 | 生产代码未失败；为测试求值器补充 `Subscript/Slice` 支持后重跑 |
| 本机全量 26 项 unittest 的基线 `test_lite3_udp_smoke` 仍因 mock 缺少 `test_closed_yaw` 报错 | 1 | 与 15:31 Jetson 已知夹具缺口一致、生产链不引用该工具；不改基线，改跑接管/仲裁/限速相关集合 |
| Jetson `/tmp` 隔离测试首轮漏复制 `src/nodes/__init__.py` 包文件，Python 3.8 无法导入 `nodes.navigation` | 1 | 未触碰运行中的生产栈；补齐两个 `__init__.py` 后重跑隔离测试 |
| Jetson `/tmp` route 描述未继承 ROS 动态库路径，`librclpy_common.so` 无法加载 | 1 | 未初始化 ROS/未发 goal；为隔离命令显式设置 `/opt/ros/foxy/lib` 后重跑 |
| 仅添加 `/opt/ros/foxy/lib` 后 `tf2_py` 仍缺 `libconsole_bridge.so.1.0` | 2 | 不继续手工拼动态库路径；改由官方 `/opt/ros/foxy/setup.bash` 完整初始化隔离命令环境 |
| `BASH_ENV=/opt/ros/foxy/setup.bash` 未在远端 SSH 链中加载 `rclpy` | 3 | 停止重复环境拼接；最后改用 Bash `--init-file` 原生初始化，若失败则以 Python 3.8 编译和纯测试为本轮远端边界 |
| 接入 `pos1_left_clear` 的首个多文件 patch 因多余 hunk 标记校验失败 | 1 | 未写入任何文件；拆分为源码与测试两个独立 patch |
| Jetson Python 3.8 用 `tests.test_*` 导入时被同名第三方 `tests` 包遮蔽 | 1 | 测试正文未运行；改为将仓库 `tests/` 直接加入 `PYTHONPATH` 并使用顶层模块名 |
| Jetson ROS import 诊断的 `python -c` 经 SSH 双重引号转义后字符串未闭合 | 1 | 仅诊断命令未运行；已用 `printenv PYTHONPATH` 取得完整路径，改为显式合并路径后直接重跑测试 |
| Foxy `ros2 topic echo` 不支持 `--once` | 1 | 仅门禁辅助查询失败；改用 TF 三段查询和 final bridge 持续日志确认 odom/TF 链 |
| 远端 summary here-doc 的 `PY` 终止符带入 `\r`，末尾触发 `NameError` | 1 | summary 与轨迹统计已在报错前完整输出；不重复执行，后续避免 PowerShell 管道 here-doc |
| PowerShell 提前展开远端只读检查中的 `$(docker ...)`，本机报 `docker` 不存在且远端 shell 引号未闭合 | 1 | 未执行任何远端清理；改用 PowerShell 单引号封装远端脚本并拆分 host/container 查询 |
| SSH 将单引号远端脚本中的 `grep -E a|b` 模式拆成远端管道，host 进程查询无效 | 1 | 容器只读查询成功；后续改为逐项 `pgrep -af`，避免正则竖线和命令替换 |
| 本地收尾 `unittest` 指定了不存在的 `tests.test_nav2_waypoint_sequence_probe` 模块 | 1 | 压力测试正确 skip、语法检查通过；列出真实测试文件后用既有控制/仲裁模块名重跑完整集合 |
| 只读代码审查子代理返回 `403 INSUFFICIENT_BALANCE` | 1 | 用户要求继续；停止重复派遣，改由主代理本地完成控制数学、安全状态机和测试审查 |
| 同步最后一处 `lite3_udp_smoke.py` 安全改动时 Jetson SSH/Tailscale 超时 | 1 | `tailscale status` 确认设备 offline（last seen 43m）；本机 dry-run 和语法验证已完成，远端同步留待主机恢复后执行，未进行真机下发 |
| Jetson `unittest discover` 使用绝对 start/top 目录时报 `Start directory is not importable` | 1 | 改用显式测试模块并把 `src/tests/repo` 加入 `PYTHONPATH`，远端 11/11 通过 |
| 本机复测时未设置 `PYTHONPATH` 且误写模块名 `test_cmd_vel_arbiter` | 1 | 设置 `src/tests/repo` 路径并改用实际模块 `test_cmd_vel_arbitration`，11/11 通过 |
| 远端未 source ROS 环境直接运行 probe `--help` 报 `No module named rclpy` | 1 | source Foxy、Nav2 overlay 和项目 install 后复核 `ROS_HELP_OK` |
| 2026-07-31 Jetson 重启导致昨晚 cuVSLAM `base_start` 地图原点失效 | 1 | 禁止继续 resume；等待确认机器狗已回官方起点后从头 clean 运行 |
| PowerShell 提前展开远端 Bash 的 `$()`，预检未到达 Jetson | 1 | 后续多行远端脚本统一 UTF-8 Base64 后交给 Bash 解码执行 |
| ROS setup 在 `set -u` 下读取未定义的 `AMENT_TRACE_SETUP_FILES` | 1 | source ROS/overlay 时不启用 nounset；确认失败发生在启动前且无 UDP 下发 |
| Jetson 未安装 `jq`，精简 summary 命令无输出 | 1 | 改用 Python 标准库 JSON parser 做只读结构化汇总 |
| clean full run 第三段超时，恢复路线又在 `grab_area_approach` 规划失败 | 1 | 两次均安全归零；确认是相邻航点的大角度终点转向漂移，需要继续扩大混合 SE(2) 覆盖范围 |
| 首次 SSH 内联 `python3 -c` 的引号在远端丢失，底层零速未执行 | 1 | 立即改为经 SSH stdin 传入 Python 脚本，随后三次 `stop_burst()` 均返回成功；未重试失败的引号方案 |
| GitHub 元数据只读查询的 PowerShell 管道在 `foreach` 后出现空管道语法错误 | 1 | 改为先收集 `$rows` 再统一 `Format-Table`，成功取得官方仓库默认分支；未发生远端写入 |
| 只读获取 2026-07-31 最近真机 `cmd_vel` 明细时 Jetson SSH 连接超时 | 1 | 停止重复连接；保留“旧摘要不能证明纯 yaw”的事实边界，待设备在线后再读取日志，不据此下运动结论 |
| Jetson 预检 here-string 最后一行残留 CR，`sha256sum` 把文件名识别为带 `\r` | 1 | 后续不复用该传输方式；改用显式 SCP 和单行 SSH 校验命令 |
| Jetson Python 3.8 无法导入 `tests.test_lite3_udp_smoke` | 1 | 把 `tests` 加入 `PYTHONPATH`，改为直接运行 `test_lite3_udp_smoke`，3/3 通过 |
| 5 秒纯 yaw 后置只读核查的远端 `awk` 因 SSH 引号转义失败 | 1 | 未重复运动；改用 `ps -C python3 -o pid=,args=` 直接核查，确认无测试或运动控制进程残留 |
| `final_bridge_tf_probe.py` 使用了不存在的 `--rate-hz` 参数 | 1 | 读取实际 CLI 后改用 `--send-rate`，只读 TF 门禁通过，未发送运动 |
| `map_base_link_trace.py` 在 TF 初始缺失时把含额外键的 fallback 行写入固定字段 CSV，抛出 `ValueError` | 1 | 未重复运动；改用本轮已持续写入的 `/tmp/final_bridge_odom_compare.csv` 恢复完整原始/Host 位姿，并复制到持久化日志目录 |
| SSH 内联 `python3 -c` 补发零速时字符串引号再次被剥离 | 1 | 不重试内联方案；调用已验证的 `lite3_udp_smoke.py`，以 `yaw=0` 发送三轴零速并完成停栈核查 |
| 只读统计 cuVSLAM `launch.log` 时 PowerShell→SSH→awk 多层引号被破坏 | 1 | 不重复该写法；改为 SCP 下载日志到本机临时目录，再用 PowerShell `Select-String` 统计 |
| 后台启动的 SSH 会话在本地 19 秒超时 | 1 | 未重复启动；只读核查确认唯一 `force_planar_mode=false` 实例已正常运行，沿用该实例完成门禁 |
| PowerShell 把远端 grep 正则中的 `|` 当成本地管道解析 | 1 | 停止通过 SSH 传复杂正则，改用远端无管道命令或 SCP 后本机解析 |
| 复制仍持续增长的 comparison CSV 时 SCP 超时并残留本机进程 | 1 | 先按安全规程停栈冻结文件，精确终止目标为该临时 CSV 的残留 `scp.exe`，再从持久静态副本下载到新文件名 |
| `rg` 参数包含不存在的 Nav2 worktree `third_party/` | 1 | 不重复该目录组合；收窄到实际存在的 `scripts/` 与 `src/`，找到 `test_leg_odom_pid.py` |
| 首次同步 state recorder 测试时文件名漏写 `test_` 前缀 | 1 | 脚本已成功同步；只补传正确的 `tests/test_lite3_state_recorder.py` 并重新显示本机/Jetson 测试通过结果 |
| 按 `Lite3_ROS protocol.hpp` 局部 pragma 推导 RobotState 为 216 字节 | 1 | 真机无运动探针实测 code 2305 为 212 字节；停止假定 ABI，增加 code/length 与 raw hex，再核对官方 MotionSDK |
| GitHub REST API 查询官方 Lite3_MotionSDK 时匿名 rate limit exceeded | 1 | 改用 Git 官方只读协议浅克隆 `main@b30a3ec` 到全新本机临时目录，不重复 API 请求 |
| 多文件 `apply_patch` 在测试文件 hunk 边界处格式错误 | 1 | 补丁整体未应用；拆为代码与 PWF 两个补丁后成功，未覆盖现有文件内容 |
| 同步底层状态结论时多文件 PWF 补丁含空 hunk 标记 | 1 | 补丁整体未应用；停止合并三个 PWF 文件，改为逐文件增量应用 |
| 正反 yaw 闭合首轮自动化门禁误要求生成 launch 同时包含 `depth_module.infra_profile` | 1 | 动作前触发失败清理，三轴两次归零且空进程/空 Docker；确认实际有效字段为 `depth_module.profile='640x360x90'`，保留 FPS/planar/IMU 三项真实断言后重跑 |
| 正反 yaw 闭合 wrapper 在 `set -u` 下 source ROS，再次触发已知 `AMENT_TRACE_SETUP_FILES` 未定义错误 | 1 | 动作前触发失败清理；移除 wrapper 的 nounset 与非必要 `/cmd_vel` 图检查，保留运动进程缺失门禁，不再重复该组合 |
| 本机并行检查的 `rg` 正则使用嵌套双引号，被 PowerShell 解析为模块名 | 1 | 改用单引号包裹正则后整组检查通过 |
| 远端只读探针首次尝试使用工具环境不存在的 `btoa` | 1 | 改用 PowerShell `[Convert]::ToBase64String()` 编码 UTF-8 远端脚本 |
| 远端验证脚本中的 Bash `${PYTHONPATH...}` 被工具模板表达式提前解析 | 1 | 转义 `$` 后重发；首次失败发生在本机解析阶段，远端未执行 |
| 读取 Jetson executor 源码时继续访问不存在的 `SingleThreadedExecutor._spin_once` | 1 | 已从公开 `spin_once` 源码取得“一次一个 callback”的充分证据；去掉私有方法读取，不据失败后的空 topic-hz 输出做判断 |
| `web-search` skill 的 `infsh` 当前版本不接受 `--input -` | 1 | 两条查询均未产生网页内容；改用 CLI 帮助中明确支持的 stdin 直接传 JSON 方式重试，不把失败输出作为证据 |
| 预同步 SHA 校验误假定 Nav2 probe 位于 Jetson 主仓库目录 | 1 | `sha256sum` 只读失败，未写远端；改为列出 Jetson 的 git worktree 并定位实际 Nav2 worktree后再校验 |
| 远端验证 wrapper 再次误用工具运行时不存在的 `btoa` | 1 | 在本机生成 SSH 命令前失败，Jetson 未执行；改用已验证的 PowerShell `[Convert]::ToBase64String()` UTF-8 编码方式 |
| Base64 远端验证脚本中的 Bash `$repo` 变量在传输链中被剥离 | 1 | `cd` 失败后测试找不到文件，`colcon` 在 home 扫描到重复包并拒绝构建；无运动节点或 Docker 启动，改用绝对路径且 `set -eo pipefail` 遇错即停 |
| Jetson 验证脚本在 source Foxy 后覆盖了 ROS `PYTHONPATH` | 1 | 15 项纯 Python 测试通过、2 项 ROS 测试 skip，route 描述随即中止且构建未运行；确认 `rclpy` 位于 `/opt/ros/foxy/lib/python3.8/site-packages`，改为保留 ROS 路径并追加仓库路径 |
| split-Y 真机预检的 PowerShell here-string 把末尾 `CR` 带入远端参数 | 1 | `--describe-route\r` 与 `lsusb -t\r` 只读诊断失败；代码 SHA、空导航进程、D455 与 Lite3 连通性仍已确认，未启动或运动。后续先把脚本行尾归一化为 LF。 |
| 清理后的进程复核 wrapper 在最后一个 Bash `for` 循环报 unexpected EOF | 1 | YOLO 容器删除与 `stop_all.sh` 已先完成；改用独立精确 PID/进程检查确认仅剩 YOLO 宿主 bridge，并将其单独终止后再启动导航。 |
| TF 门禁中的 `tf2_echo` 子进程未随外层 `timeout` 及时退出，SSH 诊断命令返回 124 | 1 | lifecycle、topic、TF 与 bridge 门禁数据已完整取得；精确终止残留 `tf2_echo` 后才发送路线，不重复该诊断组合。 |

### Phase 24: 箱体视觉定位码方案调研
- [x] 审阅 D455、cuVSLAM、Nav2、仪表识别和依赖结构
- [x] 联网核对 AprilTag/ROS2 节点、姿态估计、标签族与检测调参资料
- [x] 形成每面贴码数量、码型、尺寸、可视面覆盖和接入边界建议
- **Status:** complete（仅调研，未改实现、未启动真机）

### Phase 25: feature/vision-change 视觉分支核查
- [x] 只读获取远端分支提交和浅克隆副本
- [x] 核对 Docker RealSense、RGB/Depth/CameraInfo/TF、YOLO UDP 和巡检状态机入口
- [x] 修正标签检测的部署位置与当前分支资源冲突边界
- **Status:** complete（未切换当前分支，未改业务代码）

### Phase 26: AprilTag 全局重定位与视觉闭环职责定义
- [x] 区分局部里程计闭环与全局绝对定位开环
- [x] 明确 Tag PnP、D455 深度、map→odom 校正和最终视觉伺服职责
- [x] 给出适配 feature/vision-change 的分层数据链
- **Status:** complete（架构分析，未实施）

### Phase 27: AprilTag 重定位与抓取闭环方案收敛
- [x] 明确唯一 ID 仅用于绝对锚点数据关联，不参与箱体巡检流程判断
- [x] 明确全局重定位与最终相对视觉伺服的控制模式和速度所有权
- [x] 重新评估单码、双码刚性板及 D455 深度冗余方案
- **Status:** complete（仅调研，未改业务代码、未启动真机）

### Phase 28: 仪表区无标记精确观察方案
- [x] 根据新比赛规则移除仪表区人工定位码假设
- [x] 复核历史导航漂移、观察位和仪表检测几何输出
- [x] 对比静态航点、宽容识别、自然目标视觉伺服和自然地标重定位
- [x] 形成适配现有 RGB-D、precision 控制与速度仲裁链的推荐架构
- **Status:** complete（仅调研，未改业务代码、未启动真机）

### Phase 29: 真实场地全路线航点标定器
- [x] 新增无 ROS 运动依赖的航点配置、稳定采样与路线解析模块
- [x] 新增只订阅 `map -> base_link` 的交互式航点标定脚本
- [x] 新增真实场地配置模板和交错巡检/完整路线定义
- [x] 让 Nav2 waypoint probe 仅在显式参数下加载标定路线，默认 preset 不变
- [x] 增加纯 Python 测试并完成语法、静态 diff 与离线路线描述验证
- **Status:** complete（已同步 Jetson 并通过 SHA、26 项测试、离线路线描述和限定包构建；未启动 ROS 导航或真机运动）

### Phase 29 Deployment Errors
| Error | Attempt | Resolution |
|---|---:|---|
| Jetson Foxy `setup.bash` 在预先启用 `set -u` 时读取未定义的 `AMENT_TRACE_SETUP_FILES` | 1 | 失败发生在测试前；改为先 source ROS 环境、再启用 nounset，完整验证通过 |
| PowerShell SSH stdin 给最后一个 `colcon --event-handlers` 参数附加 `\r` | 1 | 构建尚未开始；移除非必要输出参数并使用直接 SSH 命令，限定包构建通过 |

### Phase 30: 仪表区无人工标记的全局重定位架构
- [x] 复核当前 `map -> odom -> base_link` 发布职责与静态起点限制
- [x] 区分全场自然特征定位、仪表柜自然地标重定位和局部观察视觉伺服
- [x] 形成起点先验、仪表区自然观测、抓取/放置区 AprilTag 共用单一全局校正器的方案
- [x] 明确仪表柜位姿固定与随机两种规则条件下的不同实现路径
- **Status:** complete（仅架构分析，未改业务代码、未启动 ROS 或真机）

### Phase 30 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 当前宿主没有 ByteRover MCP，且 `brv` CLI 不在 PATH | 1 | 不重复调用；使用仓库现有 PWF 历史与源码只读复核完成架构分析 |

### Phase 31: 运动中全局重定位官方资料核验
- [x] 核对 NVIDIA Isaac ROS Visual SLAM `release-2.1` 的 SLAM、TF、地图保存与地图内定位接口
- [x] 核对 ROS REP-105 对 `map / odom / base_link` 连续性和漂移校正的职责定义
- [x] 交叉核对 NVIDIA Developer Forums 与 Isaac ROS GitHub Issues 中的持续定位行为、视角限制和加载故障
- [x] 核对 RTAB-Map Foxy localization、Nav2 AMCL 与 depthimage_to_laserscan 的官方实现边界
- [x] 对照当前与历史启动版本，确认动态 `map -> odom` 被关闭，并发现当前主工作目录脚本误将 SLAM map pose 重标为 `odom`
- [x] 形成优先复用 cuVSLAM 持久视觉地图、RTAB-Map 后端为备选、Depth+AMCL 为次选的验证顺序
- **Status:** complete（联网与源码核验；未改业务代码、未启动 ROS 或真机）

### Phase 31 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| `web-search` skill 的 inference.sh 搜索任务因账户余额不足被拒绝 | 1 | 按用户许可停止使用该 skill，直接读取官方网页、官方 GitHub 分支与源码 |
| PowerShell 向 `infsh --input` 传内联 JSON 时引号被原生参数解析剥离 | 1 | 未重复该传参方式；改用 stdin 后确认真正阻塞为账户余额，随后切换官方站点直读 |

### Phase 32: YAML 数据驱动的交错航点预演
- [x] 新增基于现有 PGM 坐标的本地预演 YAML，明确与真实标定配置隔离
- [x] 将四个观察位按 `middle(+向) -> upper-right -> middle(-向) -> lower-right` 写入路线
- [x] 增加路线顺序、动作和“无连续同点 180 度”回归测试
- [x] 完成离线 Navigation 路线解析、相关测试和地图路线预览
- [x] 保持 Jetson 不变，不启动 ROS、Nav2 或真机运动
- **Status:** complete（仅本地 YAML/测试/预览；未同步 Jetson，未运行真实 Nav2 或机器狗）

### Phase 32 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 追加 `findings.md` 的补丁锚点漏写 `Foxy 环境` 中的空格 | 1 | 补丁整体未应用；改用文件中的准确原句作为锚点重试 |
| 本机完整回归未先把导航 worktree 的 `src` 加入 `PYTHONPATH`，`test_se2_pose_control` 导入 `nodes` 失败 | 1 | 前 10 项已通过且代码未失败；按仓库既有测试方式显式设置 `src/tests/repo` 路径后重跑完整集合 |

### Phase 33: Jetson 交错巡检试跑
- [x] 本地验证 preview gate、配置和相关回归
- [x] 远端读取状态、备份并同步试跑所需文件
- [x] 通过 ROS/TF/costmap/速度仲裁/零速门禁后运行六点 `inspection_interleaved`（运行至第 3 点超时，按 `--stop-on-failure` 停止）
- [x] 试跑结束后确认动作结果、三轴归零、进程和日志，不进入抓取/放置段
- **Status:** complete（前两点成功；`pos1_middle` 超时并安全取消，第 4-6 点未发送；已执行 `stop_all.sh`）

### Phase 33 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 受管 PowerShell 将 `ssh -o` 的短参数误解析为 `-OutputFormat`，只读预检未到达 Jetson | 2 | 绝对路径仍被受管包装器误解析；改由 `cmd /c` 直接启动 OpenSSH 后连通 |
| `cmd /c` 内的远端 `&&` 被外层旧版 PowerShell 提前解析 | 1 | 整组未执行；改成每项一个无 shell 运算符的远端命令后预检成功 |
| `docker ps --format` 的嵌套引号被 Windows `cmd` 改写，Docker 只返回用法 | 1 | 不把该输出用于状态判断；后续使用无格式参数的 `docker ps` |
| Jetson 路线描述的手工 ROS 环境漏加 `/opt/ros/foxy/lib/aarch64-linux-gnu`，导入 `tf2_ros` 缺 `libconsole_bridge.so.1.0` | 1 | 失败发生在 ROS 初始化前；补齐 Foxy 两个库路径后重跑只读描述 |
| 非交互 SSH 未加载 Foxy 环境，组合 `ros2 lifecycle` 查询全部返回 `ros2: command not found` | 1 | 之后每个 ROS 查询显式 `source /opt/ros/foxy/setup.bash` 和目标 overlay |
| ROS lifecycle 组合查询在 DDS 发现层卡住并超过本地超时 | 1 | 改为独立 `timeout` 查询，并以 `/tmp/competition.log` 中 `Managed nodes are active` 交叉确认 |
| 通过 SSH 直接执行 Python/jq 精简摘要时嵌套引号被远端 shell 去除 | 2 | 不将失败输出用于结论；改用 `scp` 只读复制 `summary.json` 到本机临时目录后用 PowerShell JSON 解析 |

### Phase 33: cuVSLAM 后端全局校正接入
- [x] 复核 DWB worktree 当前以 `/visual_slam/tracking/odometry` 提供连续 `odom -> base_link`
- [x] 明确后端 SLAM 已运行但其 rectified pose 尚未用于动态 `map -> odom`
- [x] 将完整实施顺序、验收条件、回退方案和安全边界写入 `progress.md`
- [x] 只读审计 Jetson 实际部署版本、运行参数、topic 与 TF 所有权
- [x] 完成保留后端、关闭可视化输出前后的无运动资源 A/B 基线
- [x] 在不改动现有 VO bridge 契约的前提下增加独立 SLAM pose 桥接和离线测试
- [x] 实现唯一 `global_pose_manager` 核心、source-stamp 去重、校正分级和 pending alignment 启动门禁
- [x] 实现固定 SE(2) 多控制点校准器，绑定 Nav2 YAML/PGM、视觉地图、D455 外参和起点 prior 的 hash
- [ ] 使用至少两个远离起点的真实控制点生成 `status=complete` 的正式对齐 bundle
- [x] 按 Jetson 实际 Isaac ROS 2.1.0 接口实现 `save_map` / `load_map_and_localize` client、坐标转换和结果门禁
- [ ] 实际验证在线回环校正、地图保存/加载和带起点 prior 的重新定位
- [x] 实现只允许抓取/放置区的 AprilTag 绝对观测纯逻辑门禁
- [x] 本地修复 loop metrics recorder 参数错配，并将在线轻量记录与停稳后单次完整 pose-graph 查询分离
- [x] Jetson 开机后备份、同步并完成无运动 recorder 存活/参数/单次服务调用验证
- [x] 编写可直接照做的中文 cuVSLAM 真机建图操作规程，包含闭环门禁、单次后验查询、save_map 和失败清理
- [x] 将旧操作规程重构为 30fps、短闭环→半程→完整路线的三级独立冷启动最终验收
- [x] 增加运动前后各抓取一次 tracking odometry 的轻量工具，并与单次 `GetAllPoses` 后端结果分层判定
- [x] 完成最终验收前 Jetson 只读预检：D455、六核/GPU 锁频、Docker、ROS/Nav2/bridge/recorder/运动进程和部署文件哈希
- [x] 验证 runbook 关键约束、轻量工具测试、Python 编译与 `git diff --check`
- [x] 将最终 runbook 与轻量 tracking 快照工具同步到 Jetson，并完成无运动容器内冒烟验收与安全清理（快照工具通过；原生图像断档门禁失败）
- [x] 以相同最终配置、不运行 tracking 快照或其他探针，重复至少 130 秒无运动原生日志复测；`30.5s` 周期稳定复现并已安全清理
- [x] 仅关闭当前用户的 `gnome-control-center`，保持 timedated/iio-sensor-proxy 与 cuVSLAM 配置不变，执行 130 秒无探针静止单变量 A/B；周期断档消失并已安全清理
- [x] 在用户确认官方起点、路线净空、遥控器与急停就位后，执行正式独立冷启动短闭环并完成单次后验判定/安全清理（已执行并安全清理；后端 `xy_closure_error_m=0.257547m`，本级失败，不进入半程）
- [ ] 接入真实 AprilTag 检测/标定，并完成无运动、人工移动、低速单段和完整路线分级验收
- **Status:** in_progress（Stage A-C 与 Stage D/E/F/G 离线基础完成；等待真实控制点、视觉地图和分级物理验收）

### Phase 33 Errors
| Error | Attempt | Resolution |
|---|---:|---|
| 预期的 `C:\Users\111\.codex\skills\planning-with-files\SKILL.md` 不存在 | 1 | 未重复读取；按当前技能清单改读 `C:\Users\111\.agents\skills\planning-with-files\SKILL.md` 并继续 |
| PowerShell 构造 `cmd /c ssh` 远端命令时把转义反斜杠传给 Linux 参数 | 1 | 未复用该构造；改为绝对路径直接调用 OpenSSH，后续 Git/hash/ROS 查询正常 |
| Host Foxy 缺少 Isaac ROS 专用消息类型，且并发 `ros2` CLI 查询触发 DDS/daemon 阻塞 | 1 | 超时退出且未修改运行态；改用容器内单个只读 `rclpy` 订阅器一次采样 VO、SLAM 与 TF |
| 终止 B 组启动脚本 PID 会同时终止其前台 `docker run`，导致 cuVSLAM 容器退出、bridge exporter 返回 137 | 1 | 将该 B 组窗口作废；重新启动 B2，保留启动脚本到测试结束，仅在最后先 `docker stop` 容器 |
| `start_cuvslam_rviz_gui.sh` 第 900 行调用未定义的 `topic_list_cmd` | 1 | 现阶段脚本仍继续运行并完成后续 topic 检查；记录为生产切换前需修复的启动脚本缺陷 |
| Windows 本机没有 `bash`，无法执行本地 `bash -n` | 1 | 以 Jetson `bash -n`/Python 编译、远端 colcon 构建和 `git diff --check` 替代；不将该环境缺失误判为脚本语法失败 |
| 新增生命周期测试首次有 2 个断言失败：yaw 浮点尾差、尺度夹具残差本身超门限 | 1 | 改用 `assertAlmostEqual`，并将夹具调整为残差可过但 6% 尺度门禁必须拒绝；目标测试随后全绿 |
| Jetson Python 3.8 无法用 `tests.test_*` 导入无 `__init__.py` 的测试目录 | 1 | 改用 `unittest discover -s tests -p ...`，21+3 项测试通过 |
| PowerShell stdin 给远端最后一个 `py_compile` 文件名追加 `\r` | 1 | 改用单参数 SSH 远端命令；Jetson `py_compile` 通过 |
| Jetson 旧版 colcon 首次参数顺序拒绝 `--symlink-install`，第二次 stdin 又给包名追加 `\r` 导致 0 包构建 | 2 | 将 `--symlink-install` 前置并改用单参数 SSH；最终明确显示 `1 package finished` |
| 最终验收只读预检首次 SSH 连通性检查 10 秒超时 | 1 | 用户确认 SSH 恢复后再连接，随后一次成功；首次命令未到达 Jetson、无远端改动 |
| Tailscale SSH 对含 `|`/引号的格式化命令拆词，Docker/CPU 输出格式异常 | 1 | 不复用复合格式化命令；改为独立 `docker ps`、sysfs `cat` 与本地进程过滤，取得可审计结果 |
| `jetson_clocks --show` 要求 root，当前只读 SSH 会话不能直接执行 | 1 | 不提权、不修改性能状态；分别读取 CPU/GPU sysfs，确认 CPU 六核与 GPU min/max/current 均已锁定 |
| 无运动 smoke 临时包装脚本在 source ROS 环境前启用 `set -u`，Humble setup 读取未定义的 `AMENT_TRACE_SETUP_FILES` 后退出 | 1 | 未进入 ROS 订阅、未影响容器；临时脚本改为 `set -eo pipefail` 后两次单样本捕获与比较成功 |

### Phase 113: 障碍间距调整后的完整路线重跑
- [x] 在不修改 costmap、DWB、路线或任务参数的前提下启动一次 `--cone-to-whz-l6`
- [x] 确认第 1 航点 `obstacle_cross_target` 成功通过
- [x] 记录第 2 航点 `pos1_left_clear` 的规划失败与任务终态
- [x] 确认终止后容器、相关进程和控制 UDP 端口全部释放
- **Status:** complete（第 2 航点期间机器人位姿超出全局 costmap，越障巡航阶段在 120.1 秒超时后中止；未进入四次 WHZ 巡检）
