#!/usr/bin/env python3
# coding: utf-8

"""新版抓取规划器：显式区分单点位置 IK 和末端姿态约束 IK。

这个模块不修改 planner.py，方便把旧版作为备份保留。
这里复用旧版的配置、坐标投影、舵机映射和已经验证过的单点位置 IK；
同时新增一条专门用于 50x50 端面靠近的 IK 路径：既约束 TCP 目标点，
也约束末端工具轴俯仰角 phi。
"""

from __future__ import print_function

import math

from .common import INITIAL_POSITION_SERVOS, IKNoSolution, MotionStep, clamp
from .planner import (
    ArmGrabConfig,
    LocalGeometricArmIK,
    adapted_wrist_servo,
    arm_servos,
    interpolate_line,
)


class PoseConstrainedArmIK(LocalGeometricArmIK):
    """IK 求解器：保留旧单点 IK，并新增末端工具轴姿态约束。"""

    def solve_position_only(self, coordinate_data, used_pitch=None):
        """复用 planner.py 中已经验证过的 TCP 单点位置 IK。"""

        return super(PoseConstrainedArmIK, self).solve(
            coordinate_data,
            phi=0.0,
            used_pitch=used_pitch,
        )

    def solve_pose_constrained(self, coordinate_data, phi, previous_servo_data=None, used_pitch=None):
        """求解带末端姿态约束的 IK。

        phi 是机械臂竖直平面内的末端工具轴俯仰角，单位 rad。
        它相对于正径向方向定义：水平向外伸时 phi 约为 0。
        """

        x, y, z = [float(value) for value in coordinate_data]
        l1 = self.config.link_l1
        l2 = self.config.link_l2
        l3 = self.config.link_l3
        l4 = self.config.link_l4
        phi = float(phi)

        forward, lateral = self._project_to_arm_plane(x, y)
        base_rad = math.atan2(lateral, forward)
        radial = math.hypot(forward, lateral)
        height = z - l1

        # 先从 TCP 点按工具轴方向反推腕点。这样 L4 的绝对方向就被 phi 固定，
        # 后续只需要用 L2/L3 两连杆去够这个腕点。
        wrist_r = radial - l4 * math.cos(phi)
        wrist_h = height - l4 * math.sin(phi)
        wrist_distance = math.hypot(wrist_r, wrist_h)
        self._check_two_link_reachable(wrist_distance, l2, l3, coordinate_data, radial, phi)

        best = None
        best_score = None
        last_limit_error = None
        for elbow_mode, elbow_rad in self._two_link_elbow_candidates(wrist_r, wrist_h, l2, l3):
            shoulder_rad = self._solve_shoulder_for_wrist(wrist_r, wrist_h, elbow_rad, l2, l3)
            l3_abs_rad = shoulder_rad + elbow_rad
            wrist_rad = phi - l3_abs_rad

            raw_servo_data = self._joint_angles_to_raw_servos(
                wrist_deg=math.degrees(wrist_rad),
                elbow_deg=math.degrees(elbow_rad),
                shoulder_deg=math.degrees(shoulder_rad),
                base_deg=math.degrees(base_rad),
            )
            try:
                self._check_servo_limits(raw_servo_data, coordinate_data)
            except IKNoSolution as exc:
                last_limit_error = exc
                continue

            score = self._score_pose_solution(raw_servo_data, previous_servo_data, elbow_mode)
            if best_score is None or score > best_score:
                best_score = score
                best = (shoulder_rad, elbow_rad, wrist_rad, raw_servo_data, elbow_mode)

        if best is None:
            detail = ""
            if last_limit_error is not None:
                detail = "; last_limit_error={}".format(last_limit_error)
            raise IKNoSolution(
                "IK pose constrained no solution: coordinate={} phi={:.2f}deg{}".format(
                    coordinate_data,
                    math.degrees(phi),
                    detail,
                )
            )

        shoulder_rad, elbow_rad, wrist_rad, raw_servo_data, elbow_mode = best
        servo_data = {name: clamp(pulse) for name, pulse in raw_servo_data.items()}
        l3_abs_rad = shoulder_rad + elbow_rad
        wrist_point = (
            radial - l4 * math.cos(phi),
            l1 + height - l4 * math.sin(phi),
        )
        ik_angles = {
            "theta3": math.degrees(wrist_rad),
            "theta4": math.degrees(elbow_rad),
            "theta5": math.degrees(shoulder_rad),
            "theta6": math.degrees(base_rad),
            "phi": math.degrees(phi),
            "ik_mode": "pose_constrained",
            "elbow_mode": elbow_mode,
            "wrist_point_rz": wrist_point,
            "l3_abs_deg": math.degrees(l3_abs_rad),
            "l4_abs_deg": math.degrees(phi),
            "wrist_target_distance": wrist_distance,
            "unit": "deg",
        }
        return ik_angles, servo_data, used_pitch

    def solve_wrist_fixed(self, coordinate_data, wrist_deg, previous_servo_data=None, used_pitch=None):
        """Solve TCP position while preserving the relative wrist joint angle.

        ``wrist_deg`` is theta3, the joint commanded through servo ID3.  This
        is intentionally different from holding the tool-axis angle ``phi``:
        the placement descent must keep the physical wrist joint unchanged.
        """

        x, y, z = [float(value) for value in coordinate_data]
        l1 = self.config.link_l1
        l2 = self.config.link_l2
        l3 = self.config.link_l3
        l4 = self.config.link_l4
        wrist_rad = math.radians(float(wrist_deg))

        forward, lateral = self._project_to_arm_plane(x, y)
        base_rad = math.atan2(lateral, forward)
        radial = math.hypot(forward, lateral)
        height = z - l1

        # With theta3 fixed, L3 and L4 form one virtual link.  Solve L2 and
        # that virtual link, then recover the physical elbow angle.
        virtual_r = l3 + l4 * math.cos(wrist_rad)
        virtual_h = l4 * math.sin(wrist_rad)
        virtual_length = math.hypot(virtual_r, virtual_h)
        virtual_offset = math.atan2(virtual_h, virtual_r)
        distance = math.hypot(radial, height)
        self._check_two_link_reachable(distance, l2, virtual_length, coordinate_data, radial, wrist_rad)

        best = None
        best_score = None
        last_limit_error = None
        for elbow_mode, virtual_elbow_rad in self._two_link_elbow_candidates(
            radial, height, l2, virtual_length
        ):
            shoulder_rad = self._solve_shoulder_for_wrist(
                radial, height, virtual_elbow_rad, l2, virtual_length
            )
            elbow_rad = virtual_elbow_rad - virtual_offset
            raw_servo_data = self._joint_angles_to_raw_servos(
                wrist_deg=float(wrist_deg),
                elbow_deg=math.degrees(elbow_rad),
                shoulder_deg=math.degrees(shoulder_rad),
                base_deg=math.degrees(base_rad),
            )
            try:
                self._check_servo_limits(raw_servo_data, coordinate_data)
            except IKNoSolution as exc:
                last_limit_error = exc
                continue
            score = self._score_pose_solution(raw_servo_data, previous_servo_data, elbow_mode)
            if best_score is None or score > best_score:
                best_score = score
                best = (shoulder_rad, elbow_rad, raw_servo_data, elbow_mode)

        if best is None:
            detail = "" if last_limit_error is None else "; last_limit_error={}".format(last_limit_error)
            raise IKNoSolution(
                "IK wrist-fixed no solution: coordinate={} theta3={:.2f}deg{}".format(
                    coordinate_data, float(wrist_deg), detail
                )
            )

        shoulder_rad, elbow_rad, raw_servo_data, elbow_mode = best
        servo_data = {name: clamp(pulse) for name, pulse in raw_servo_data.items()}
        ik_angles = {
            "theta3": float(wrist_deg),
            "theta4": math.degrees(elbow_rad),
            "theta5": math.degrees(shoulder_rad),
            "theta6": math.degrees(base_rad),
            "ik_mode": "wrist_fixed",
            "elbow_mode": elbow_mode,
            "unit": "deg",
        }
        return ik_angles, servo_data, used_pitch

    def _two_link_elbow_candidates(self, wrist_r, wrist_h, l2, l3):
        cos_elbow = (
            wrist_r * wrist_r
            + wrist_h * wrist_h
            - l2 * l2
            - l3 * l3
        ) / (2.0 * l2 * l3)
        cos_elbow = max(-1.0, min(1.0, cos_elbow))
        elbow_abs = math.acos(cos_elbow)
        return (
            ("down", elbow_abs),
            ("up", -elbow_abs),
        )

    @staticmethod
    def _solve_shoulder_for_wrist(wrist_r, wrist_h, elbow_rad, l2, l3):
        beta = math.atan2(wrist_h, wrist_r)
        gamma = math.atan2(
            l3 * math.sin(elbow_rad),
            l2 + l3 * math.cos(elbow_rad),
        )
        return beta - gamma

    @staticmethod
    def _check_two_link_reachable(distance, l2, l3, coordinate_data, radial, phi):
        min_reach = abs(l2 - l3)
        max_reach = l2 + l3
        eps = 1e-9
        if distance <= eps or distance > max_reach + eps or distance < min_reach - eps:
            raise IKNoSolution(
                "IK pose constrained unreachable: coordinate={} r={:.4f}m phi={:.2f}deg "
                "wrist_distance={:.4f}m reachable=[{:.4f}, {:.4f}]m".format(
                    coordinate_data,
                    radial,
                    math.degrees(phi),
                    distance,
                    min_reach,
                    max_reach,
                )
            )

    def _score_pose_solution(self, raw_servo_data, previous_servo_data=None, elbow_mode="up"):
        # 先偏好远离舵机极限的解，再轻微偏好 elbow up；
        # 若传入上一帧 servo，则额外偏好更连续的解，减少 approach 过程跳变。
        min_margin = min(
            min(
                pulse - self.config.joint_min_pulse,
                self.config.joint_max_pulse - pulse,
            )
            for pulse in raw_servo_data.values()
        )
        score = min_margin
        if elbow_mode == "up":
            score += 20.0

        previous = _normalize_servo_data(previous_servo_data)
        if previous:
            delta = 0.0
            for name, pulse in raw_servo_data.items():
                old = previous.get(name)
                if old is not None:
                    delta += abs(float(pulse) - float(old))
            score -= 0.15 * delta
        return score


class GeneratedFaceGraspPose(object):
    """由 planner_new 自动生成的端面抓取位姿。

    这个轻量对象和端面抓取位姿保持同样的关键字段，
    方便复用 plan_grasp_pose()/plan_face_grasp_pose()。
    """

    def __init__(
        self,
        position,
        pre_point,
        grasp_point,
        lift_point,
        face_normal,
        rotation_deg=0.0,
        phi=0.0,
    ):
        self.position = tuple(float(x) for x in position)
        self.rotation_deg = float(rotation_deg)
        self.pre_point = tuple(float(x) for x in pre_point)
        self.grasp_point = tuple(float(x) for x in grasp_point)
        self.lift_point = tuple(float(x) for x in lift_point)
        self.face_normal = tuple(float(x) for x in face_normal)
        self.approach_dir = _normalize_vector(
            (
                self.grasp_point[0] - self.pre_point[0],
                self.grasp_point[1] - self.pre_point[1],
                self.grasp_point[2] - self.pre_point[2],
            )
        )
        self.phi = float(phi)

    def has_approach_path(self):
        return True

    def to_dict(self):
        return {
            "position": self.position,
            "rotation_deg": self.rotation_deg,
            "pre_point": self.pre_point,
            "grasp_point": self.grasp_point,
            "lift_point": self.lift_point,
            "face_normal": self.face_normal,
            "approach_dir": self.approach_dir,
            "phi": self.phi,
        }

    def __repr__(self):
        return (
            "GeneratedFaceGraspPose(grasp_point={}, pre_point={}, lift_point={}, "
            "face_normal={}, rotation_deg={:.1f})"
        ).format(
            self.grasp_point,
            self.pre_point,
            self.lift_point,
            self.face_normal,
            self.rotation_deg,
        )


class ArmGrabPlannerNew(object):
    """新版规划器：普通抓取和 50x50 端面抓取走不同流程。"""

    def __init__(self, config=None, arm_ik=None):
        self.config = config or ArmGrabConfig()
        self.arm_ik = arm_ik or PoseConstrainedArmIK(self.config)

    def solve_position_only(self, coordinate):
        ik_angles, servo_data, used_pitch = self.arm_ik.solve_position_only(
            coordinate,
            used_pitch=self.config.pitch,
        )
        return {
            "coordinate": tuple(float(x) for x in coordinate),
            "servo_pulses": servo_data,
            "ik_angles": ik_angles,
            "used_pitch": used_pitch,
        }

    def solve_pose_constrained(self, coordinate, phi, previous_servo_data=None):
        ik_angles, servo_data, used_pitch = self.arm_ik.solve_pose_constrained(
            coordinate,
            phi,
            previous_servo_data=previous_servo_data,
            used_pitch=self.config.pitch,
        )
        return {
            "coordinate": tuple(float(x) for x in coordinate),
            "servo_pulses": servo_data,
            "ik_angles": ik_angles,
            "used_pitch": used_pitch,
        }

    def solve_wrist_fixed(self, coordinate, wrist_deg, previous_servo_data=None):
        ik_angles, servo_data, used_pitch = self.arm_ik.solve_wrist_fixed(
            coordinate,
            wrist_deg=float(wrist_deg),
            previous_servo_data=previous_servo_data,
            used_pitch=self.config.pitch,
        )
        return {
            "coordinate": tuple(float(x) for x in coordinate),
            "servo_pulses": servo_data,
            "ik_angles": ik_angles,
            "used_pitch": used_pitch,
        }

    def solve_end_effector(self, coordinate, phi=0.0, pose_constrained=False, previous_servo_data=None):
        """兼容式入口：调用者可以通过 pose_constrained 选择 IK 类型。"""

        if pose_constrained:
            return self.solve_pose_constrained(
                coordinate,
                phi,
                previous_servo_data=previous_servo_data,
            )
        return self.solve_position_only(coordinate)

    def end_effector_points(self, object_position):
        x, y, z = object_position
        target = (float(x), float(y), float(z))
        approach = (
            target[0],
            target[1] + self.config.approach_y,
            target[2] + self.config.approach_z,
        )
        lift = (target[0], target[1], target[2] + self.config.lift_z)
        retreat = (target[0], target[1], target[2] + self.config.retreat_z)
        return {
            "approach": approach,
            "target": target,
            "lift": lift,
            "retreat": retreat,
        }

    def plan_grab(self, object_position, rotation_deg=0.0, include_home=False):
        """普通点位抓取：这里刻意使用 position-only IK，保持旧逻辑稳定。"""

        points = self.end_effector_points(object_position)
        solve_names = ["approach", "target", "lift"]
        if self.config.include_retreat:
            solve_names.append("retreat")

        solved = {}
        for name in solve_names:
            try:
                solved[name] = self.solve_position_only(points[name])
            except IKNoSolution as exc:
                raise IKNoSolution("{}, step={}".format(exc, name))

        wrist = adapted_wrist_servo(rotation_deg, self.config)
        steps = [
            MotionStep(
                "pre_grasp_open_and_rotate",
                None,
                500,
                ((1, self.config.grasp_open_gripper), (2, wrist)),
            ),
            MotionStep(
                "approach",
                points["approach"],
                1500,
                arm_servos(solved["approach"]["servo_pulses"]),
                solved["approach"]["ik_angles"],
                solved["approach"]["used_pitch"],
            ),
            MotionStep(
                "target",
                points["target"],
                800,
                arm_servos(solved["target"]["servo_pulses"]),
                solved["target"]["ik_angles"],
                solved["target"]["used_pitch"],
            ),
            MotionStep("close_gripper", None, 600, ((1, self.config.close_gripper),)),
            MotionStep(
                "lift",
                points["lift"],
                800,
                arm_servos(solved["lift"]["servo_pulses"]),
                solved["lift"]["ik_angles"],
                solved["lift"]["used_pitch"],
            ),
        ]

        if self.config.include_retreat:
            steps.append(
                MotionStep(
                    "retreat",
                    points["retreat"],
                    800,
                    arm_servos(solved["retreat"]["servo_pulses"]),
                    solved["retreat"]["ik_angles"],
                    solved["retreat"]["used_pitch"],
                )
            )

        if include_home:
            steps.append(self._home_step())
        return steps

    def plan_grasp_pose(self, grasp_pose, include_home=False):
        """根据 GraspPose 是否包含端面路径，分派到对应规划流程。"""

        if not getattr(grasp_pose, "has_approach_path", lambda: False)():
            return self.plan_grab(
                grasp_pose.position,
                rotation_deg=grasp_pose.rotation_deg,
                include_home=include_home,
            )
        return self.plan_face_grasp_pose(grasp_pose, include_home=include_home)

    def make_horizontal_face_grasp_pose(
        self,
        grasp_point,
        rotation_deg=0.0,
        pre_distance=0.05,
        lift_height=0.08,
    ):
        """只输入目标抓取点，自动生成 phi=0 的水平端面抓取位姿。

        工具方向取“基座指向目标点”的水平径向方向：
        - phi = 0；
        - pre_point = grasp_point - tool_dir * pre_distance；
        - face_normal = -tool_dir；
        - lift_point = grasp_point + (0, 0, lift_height)。
        """

        grasp_point = tuple(float(x) for x in grasp_point)
        tool_dir = self.horizontal_tool_dir_from_point(grasp_point)
        pre_distance = float(pre_distance)
        lift_height = float(lift_height)
        pre_point = (
            grasp_point[0] - tool_dir[0] * pre_distance,
            grasp_point[1] - tool_dir[1] * pre_distance,
            grasp_point[2] - tool_dir[2] * pre_distance,
        )
        lift_point = (
            grasp_point[0],
            grasp_point[1],
            grasp_point[2] + lift_height,
        )
        face_normal = (-tool_dir[0], -tool_dir[1], -tool_dir[2])
        return GeneratedFaceGraspPose(
            position=grasp_point,
            pre_point=pre_point,
            grasp_point=grasp_point,
            lift_point=lift_point,
            face_normal=face_normal,
            rotation_deg=rotation_deg,
            phi=0.0,
        )

    def horizontal_face_reach_hint(self, grasp_point, pre_distance=0.05):
        """返回 phi=0 自动端面抓取的水平可达性提示。

        这个函数只做几何层面的粗检查，主要用于报错时解释为什么
        pre/grasp 点在姿态约束 IK 下可能无解。
        """

        grasp_point = tuple(float(x) for x in grasp_point)
        tool_dir = self.horizontal_tool_dir_from_point(grasp_point)
        pre_distance = float(pre_distance)
        pre_point = (
            grasp_point[0] - tool_dir[0] * pre_distance,
            grasp_point[1] - tool_dir[1] * pre_distance,
            grasp_point[2],
        )
        return {
            "grasp": self._horizontal_pose_reach_info(grasp_point, phi=0.0),
            "pre": self._horizontal_pose_reach_info(pre_point, phi=0.0),
            "pre_point": pre_point,
            "tool_dir": tool_dir,
            "pre_distance": pre_distance,
        }

    def plan_horizontal_face_grab(
        self,
        grasp_point,
        rotation_deg=0.0,
        pre_distance=0.05,
        lift_height=0.08,
        include_home=False,
    ):
        """只输入目标点，按 phi=0 自动生成过程点并规划端面抓取。"""

        pose = self.make_horizontal_face_grasp_pose(
            grasp_point,
            rotation_deg=rotation_deg,
            pre_distance=pre_distance,
            lift_height=lift_height,
        )
        return self.plan_face_grasp_pose(pose, include_home=include_home)

    def plan_place(self, place_point, duration_ms=1200, include_home=False):
        """Plan a direct placement motion without a face-approach path.

        ``place_point`` is the TCP release point in the ArmPi base frame. The
        arm moves directly to that point using the established position-only
        IK, then opens the gripper. The caller can append the known home pose
        after release when the surrounding workspace is clear.
        """

        place_point = tuple(float(value) for value in place_point)
        if len(place_point) != 3:
            raise ValueError("place_point must contain exactly three values")
        solved = self.solve_position_only(place_point)
        steps = [
            self._motion_step_from_solution(
                "place_target",
                place_point,
                max(1, int(duration_ms)),
                solved,
            ),
            MotionStep(
                "open_gripper",
                None,
                600,
                ((1, self.config.open_gripper),),
            ),
        ]
        if include_home:
            steps.append(self._home_step())
        return steps

    def plan_place_from_lift(
        self,
        grasp_point,
        lift_height_m,
        descent_m,
        pose1_duration_ms=1200,
        descent_duration_ms=800,
    ):
        """Return to the grasp-end lift pose, descend with theta3 held, release."""

        grasp_point = tuple(float(value) for value in grasp_point)
        if len(grasp_point) != 3:
            raise ValueError("grasp_point must contain exactly three values")
        lift_height_m = float(lift_height_m)
        descent_m = float(descent_m)
        if lift_height_m <= 0.0 or descent_m <= 0.0 or descent_m > lift_height_m:
            raise ValueError("descent_m must be positive and no greater than lift_height_m")

        pose1_point = (grasp_point[0], grasp_point[1], grasp_point[2] + lift_height_m)
        release_point = (pose1_point[0], pose1_point[1], pose1_point[2] - descent_m)
        pose1 = self.solve_position_only(pose1_point)
        wrist_deg = float(pose1["ik_angles"]["theta3"])
        descent = self.solve_wrist_fixed(
            release_point,
            wrist_deg=wrist_deg,
            previous_servo_data=pose1["servo_pulses"],
        )
        return [
            self._motion_step_from_solution(
                "place_pose_1", pose1_point, max(1, int(pose1_duration_ms)), pose1
            ),
            self._motion_step_from_solution(
                "place_descend_2cm", release_point, max(1, int(descent_duration_ms)), descent
            ),
            MotionStep("open_gripper", None, 600, ((1, self.config.open_gripper),)),
        ]

    def plan_face_grasp_pose(self, grasp_pose, include_home=False):
        """规划 50x50 近端面靠近抓取，使用姿态约束 IK。"""

        pre_point, grasp_point, lift_point = self._validate_face_grasp_pose(grasp_pose)
        # arm_new 当前端面抓取固定水平工具姿态：phi 始终为 0。
        # pre/grasp/face_normal 只决定路径点，不再参与工具俯仰角计算。
        phi = 0.0
        wrist = adapted_wrist_servo(getattr(grasp_pose, "rotation_deg", 0.0), self.config)

        steps = [
            MotionStep(
                "pre_grasp_open_and_rotate",
                None,
                500,
                ((1, self.config.grasp_open_gripper), (2, wrist)),
            ),
            MotionStep(
                "safe_pose",
                None,
                800,
                self.config.safe_servos,
            ),
            MotionStep(
                "open_gripper_after_safe_pose",
                None,
                500,
                ((1, self.config.grasp_open_gripper),),
            ),
        ]

        previous_servo_data = None
        solved_pre = self.solve_pose_constrained(pre_point, phi, previous_servo_data)
        previous_servo_data = solved_pre["servo_pulses"]
        steps.append(self._motion_step_from_solution("pre_grasp", pre_point, 1000, solved_pre))

        points = interpolate_line(pre_point, grasp_point, self.config.approach_steps)
        for index, point in enumerate(points, 1):
            solved = self.solve_pose_constrained(point, phi, previous_servo_data)
            previous_servo_data = solved["servo_pulses"]
            steps.append(
                self._motion_step_from_solution(
                    "approach_{:02d}".format(index),
                    point,
                    self.config.approach_step_duration_ms,
                    solved,
                )
            )

        steps.append(MotionStep("close_gripper", None, 600, ((1, self.config.close_gripper),)))
        steps.append(MotionStep("hold_after_grasp", None, 300, ()))

        # 抬升阶段主要目标是离开物体，不再强制保持端面法向姿态；
        # 继续约束 phi 很容易让腕点落到不可达区域。
        solved_lift = self.solve_position_only(lift_point)
        steps.append(self._motion_step_from_solution("lift", lift_point, 800, solved_lift))

        if include_home:
            steps.append(self._home_step())
        return steps

    def approach_dir_from_points(self, pre_point, grasp_point):
        return _normalize_vector(
            (
                float(grasp_point[0]) - float(pre_point[0]),
                float(grasp_point[1]) - float(pre_point[1]),
                float(grasp_point[2]) - float(pre_point[2]),
            )
        )

    def horizontal_tool_dir_from_point(self, point):
        """计算 phi=0 时从基座水平指向目标点的工具方向。"""

        x, y, _z = [float(value) for value in point]
        forward, lateral = self.arm_ik._project_to_arm_plane(x, y)
        radial = math.hypot(forward, lateral)
        if radial <= 1e-9:
            raise ValueError("目标点太接近基座中心，无法自动确定水平靠近方向: {}".format(point))
        base_rad = math.atan2(lateral, forward)
        tool_x, tool_y = self.arm_ik._xy_from_arm_plane(1.0, base_rad)
        return _normalize_vector((tool_x, tool_y, 0.0))

    def _horizontal_pose_reach_info(self, point, phi=0.0):
        x, y, z = [float(value) for value in point]
        forward, lateral = self.arm_ik._project_to_arm_plane(x, y)
        radial = math.hypot(forward, lateral)
        height = z - self.config.link_l1
        wrist_r = radial - self.config.link_l4 * math.cos(phi)
        wrist_h = height - self.config.link_l4 * math.sin(phi)
        wrist_distance = math.hypot(wrist_r, wrist_h)
        min_reach = abs(self.config.link_l2 - self.config.link_l3)
        max_reach = self.config.link_l2 + self.config.link_l3
        return {
            "point": (x, y, z),
            "radial": radial,
            "height": height,
            "wrist_distance": wrist_distance,
            "min_reach": min_reach,
            "max_reach": max_reach,
            "ok": min_reach <= wrist_distance <= max_reach,
        }

    def tool_dir_from_face_normal(self, grasp_pose):
        """由端面外法向得到工具靠近方向。

        face_normal 定义为端面外法向，通常从物体指向机械臂外侧；
        夹爪靠近物体时，工具轴方向与外法向相反。
        """

        face_normal = getattr(grasp_pose, "face_normal", None)
        if face_normal is None:
            return None
        normal = _normalize_vector(face_normal)
        return (-normal[0], -normal[1], -normal[2])

    def face_normal_to_phi(self, face_normal, reference_point):
        """把端面外法向转换成工具靠近方向的 phi。"""

        normal = _normalize_vector(face_normal)
        tool_dir = (-normal[0], -normal[1], -normal[2])
        return self.approach_dir_to_phi(tool_dir, reference_point)

    def approach_dir_to_phi(self, approach_dir, reference_point):
        """把三维靠近方向投影到机械臂竖直平面，得到带符号的 phi。"""

        approach_dir = _normalize_vector(approach_dir)
        ref_forward, ref_lateral = self.arm_ik._project_to_arm_plane(
            float(reference_point[0]),
            float(reference_point[1]),
        )
        base_rad = math.atan2(ref_lateral, ref_forward)

        dir_forward, dir_lateral = self.arm_ik._project_to_arm_plane(
            approach_dir[0],
            approach_dir[1],
        )
        radial_component = (
            dir_forward * math.cos(base_rad)
            + dir_lateral * math.sin(base_rad)
        )
        vertical_component = approach_dir[2]
        return math.atan2(vertical_component, radial_component)

    def _validate_face_grasp_pose(self, grasp_pose):
        names = ("pre_point", "grasp_point", "lift_point")
        missing = [name for name in names if getattr(grasp_pose, name, None) is None]
        if missing:
            raise ValueError("face grasp pose missing fields: {}".format(", ".join(missing)))
        return (
            tuple(float(x) for x in grasp_pose.pre_point),
            tuple(float(x) for x in grasp_pose.grasp_point),
            tuple(float(x) for x in grasp_pose.lift_point),
        )

    @staticmethod
    def _motion_step_from_solution(name, coordinate, duration_ms, solved):
        return MotionStep(
            name,
            coordinate,
            duration_ms,
            arm_servos(solved["servo_pulses"]),
            solved["ik_angles"],
            solved["used_pitch"],
        )

    @staticmethod
    def _home_step():
        return MotionStep(
            "home_from_sorting_py",
            None,
            1200,
            INITIAL_POSITION_SERVOS,
        )


def plan_grab_motion_new(x, y, z, rotation_deg=0.0, config=None, include_home=False, arm_ik=None):
    """一次性普通抓取规划入口，使用 ArmGrabPlannerNew。"""

    planner = ArmGrabPlannerNew(config=config, arm_ik=arm_ik)
    return planner.plan_grab((x, y, z), rotation_deg=rotation_deg, include_home=include_home)


def plan_place_motion_new(x, y, z, duration_ms=1200, config=None, include_home=False, arm_ik=None):
    """One-shot direct placement planning entry point."""

    planner = ArmGrabPlannerNew(config=config, arm_ik=arm_ik)
    return planner.plan_place(
        (x, y, z),
        duration_ms=duration_ms,
        include_home=include_home,
    )


def _normalize_vector(vector):
    values = tuple(float(x) for x in vector)
    length = math.sqrt(sum(x * x for x in values))
    if length <= 1e-9:
        raise ValueError("zero-length vector")
    return tuple(x / length for x in values)


def _normalize_servo_data(servo_data):
    if not servo_data:
        return {}
    if isinstance(servo_data, dict):
        if any(isinstance(key, str) for key in servo_data.keys()):
            return {str(key): float(value) for key, value in servo_data.items()}
        id_to_name = {
            3: "servo3",
            4: "servo4",
            5: "servo5",
            6: "servo6",
        }
        return {
            id_to_name[int(key)]: float(value)
            for key, value in servo_data.items()
            if int(key) in id_to_name
        }

    id_to_name = {
        3: "servo3",
        4: "servo4",
        5: "servo5",
        6: "servo6",
    }
    out = {}
    for servo_id, pulse in servo_data:
        servo_id = int(servo_id)
        if servo_id in id_to_name:
            out[id_to_name[servo_id]] = float(pulse)
    return out
