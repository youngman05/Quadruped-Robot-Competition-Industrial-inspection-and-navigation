"""Contract tests for the shared dog/arm spatial calibration bundle."""

from __future__ import annotations

import math
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "calibration" / "competition_sites.yaml"
ARM_PARAMS_PATH = ROOT / "arm_new" / "config" / "arm_motion_params.yaml"

REQUIRED_DOG_POSES = {
    "start",
    "obstacle_cross_target",
    "inspection_pos1_middle",
    "inspection_pos1_middle_turned",
    "inspection_pos2a_upper_right",
    "inspection_pos2b_lower_right",
    "grasp_i0",
    "placement_A",
    "placement_B",
    "placement_C",
    "placement_D",
}


def _load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def _is_finite_pose(value) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 3
        and all(isinstance(item, (int, float)) and math.isfinite(item) for item in value)
    )


def test_competition_sites_schema_and_units_are_explicit():
    config = _load_config()
    assert config["schema_version"] == 1
    assert config["calibration_set"]["id"]
    assert config["calibration_set"]["map_id"]
    assert config["convention"]["dog_pose_frame"] == "map"
    assert config["convention"]["length_unit"] == "m"
    assert config["convention"]["angle_unit"] == "rad"


def test_required_dog_poses_exist_and_calibrated_poses_are_complete():
    config = _load_config()
    dog_poses = config["dog_poses"]
    assert REQUIRED_DOG_POSES <= set(dog_poses)

    for name, entry in dog_poses.items():
        assert entry["status"] in {
            "uncalibrated",
            "conflict",
            "provisional",
            "calibrated",
        }, name
        if entry["status"] == "calibrated":
            assert _is_finite_pose(entry["pose_map_m_rad"]), name


def test_i1_and_smoke_test_share_the_expected_dynamic_z_contract():
    config = _load_config()
    grasp_i1 = config["manipulation"]["grasp_i1"]
    assert grasp_i1["target_frame"] == "arm_base_link"
    assert grasp_i1["fixed_xy_m"] == [0.42, 0.00]
    assert grasp_i1["z_mode"] == "dynamic_service_request"

    z_min, z_max = grasp_i1["z_valid_range_m"]
    assert z_min <= config["smoke_test"]["grasp_z_m"] <= z_max


def test_arm_runtime_defaults_match_the_configured_i1_grasp_contract():
    sites = _load_config()
    arm_config = yaml.safe_load(ARM_PARAMS_PATH.read_text(encoding="utf-8"))
    arm_params = arm_config["arm_motion_node"]["ros__parameters"]

    assert arm_params["grasp_reference_arm_base"] == sites["manipulation"]["grasp_i1"]["fixed_xy_m"]
    assert arm_params["grasp_z_min_m"] == sites["manipulation"]["grasp_i1"]["z_valid_range_m"][0]
    assert arm_params["grasp_z_max_m"] == sites["manipulation"]["grasp_i1"]["z_valid_range_m"][1]
    assert arm_params["grasp_pre_distance"] == 0.05
    assert arm_params["grasp_lift_height"] == 0.08
    assert arm_params["grasp_duration_scale"] == 2.0
    assert arm_params["grasp_approach_steps"] == 8
    assert arm_params["grasp_approach_step_duration_ms"] == 180
    assert arm_params["grasp_include_home"] is False


def test_release_target_cannot_be_marked_calibrated_without_a_finite_point():
    release = _load_config()["manipulation"]["fixed_release"]
    if release["status"] == "calibrated":
        assert _is_finite_pose(release["target_m"])
