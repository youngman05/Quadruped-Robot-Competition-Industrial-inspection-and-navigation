# Work Log

## 2026-06-23

### D455 Camera API + cuVSLAM Preparation

Completed:

- **D455 Python wrapper** (`src/cv/realsense_camera/`):
  - `RealsenseCamera` class with context manager, auto-alignment, warmup.
  - IMU support: `get_imu_data()`, `get_imu_samples()`, `get_imu_batch()`.
  - Infrared stereo: `get_infrared_frames()` for cuVSLAM input.
  - Projector control: `set_projector(on/off)`.
  - Factory presets: `for_cuvslam()`, `for_gauge()`.
  - Depth filter presets: light / balanced / max.
  - Tested: all 7 tests passed (IR, IMU, projector, combined, gauge).
- **D455 IMU verified**: BMI055 6-DoF (Accel 100/200/400 Hz, Gyro 200/400 Hz), confirmed via API.
- **cuVSLAM research**: NVIDIA GPU-accelerated VSLAM confirmed compatible with D455 (IR stereo + IMU).
- **Instance segmentation workspace**: YOLOv8-seg real-time segmentation with D455 support.
  - `scripts/camera_detect.py` with custom mask rendering.
  - `notebooks/quickstart.ipynb` migrated to segmentation.
- **Project packaging**: `setup.py develop` removes `sys.path.insert` hack; direct `from cv.realsense_camera import ...` now works.
- **Docs updated**: system_design (cuVSLAM, CV), slam/README (cuVSLAM deployment), pyrealsense2 API reference (IMU + IR sections).

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

