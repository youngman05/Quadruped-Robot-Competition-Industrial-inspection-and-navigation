# Work Log

## 2026-05-02

### Documentation sync

Completed:

- Updated `README.md` to document the current `/gauge/status` JSON interface.
- Updated `CONTRIBUTING.md` to clarify the gauge node test workflow and task-decision rule.
- Documented that `detected` is a single-frame validity signal.
- Documented that task logic should use stable fields:
  - `stable_detected`
  - `stable_color`
  - `stable_level`
  - `stable_status`
- Documented `stable_frame_count` ROS2 parameter usage.

Git:

```text
158a9b6 Update gauge status documentation
```

Current repository state:

- `main` is aligned with `origin/main`.
- No local uncommitted code changes at the time this log entry was created.

## 2026-05-01

### Gauge ROS2 status stabilization

Completed:

- Added `GaugeStabilityTracker` in `src/cv/gauge_detector/live_validation.py`.
- Added stable gauge fields to `/gauge/status` JSON output:
  - `stable_detected`
  - `stable_reason`
  - `stable_count`
  - `stable_required_count`
  - `stable_level`
  - `stable_status`
  - `stable_color`
  - `stable_angle`
- Added ROS2 parameter `stable_frame_count` to `scripts/gauge_status_node.py`.
  - Default: `3`
  - Meaning: publish stable state only after the same valid gauge state appears for 3 consecutive processed frames.
- Refactored `scripts/realsense_gauge_live.py` to reuse `GaugeValidationConfig` and `is_valid_gauge_result` from `live_validation.py`.
- Kept `/gauge/detected` as a single-frame debug/compatibility signal.

Validation run on Windows development machine:

```bash
python -m py_compile scripts/gauge_status_node.py src/cv/gauge_detector/live_validation.py scripts/realsense_gauge_live.py src/cv/gauge_detector/gauge_detector.py
git diff --check
```

Additional stability sanity check:

```text
[False, False, True]
False
```

Interpretation:

- Three consecutive identical valid frames produce `stable_detected=true` on the third frame.
- An invalid frame resets the stability tracker.

Git:

```text
5cbfb8a Add stable gauge status tracking
```

Pushed to GitHub `main`.

### Jetson next validation

Run on Jetson:

```bash
cd ~/quadruped-robot-competition
git pull --ff-only
bash scripts/check_jetson_env.sh
source /opt/ros/foxy/setup.bash
python3 scripts/gauge_status_node.py
```

In another terminal:

```bash
source /opt/ros/foxy/setup.bash
ros2 topic echo /gauge/status
```

Confirm:

- `/gauge/status` publishes JSON.
- `detected` changes according to single-frame validity.
- `stable_detected` becomes `true` only after consecutive stable frames.
- `stable_color`, `stable_level`, and `stable_status` are used for task decisions.

Safety note:

- Do not publish non-zero `/cmd_vel` before onsite safety confirmation.
- Current gauge node remains read-only and does not control robot motion.
