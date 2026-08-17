#!/usr/bin/env python3
# coding: utf-8

"""抓取规划 API。

本模块只做计算，不打开串口，也不真实移动机械臂。

IK 使用当前讨论后的工程几何法：

1. 先由目标点水平投影确定底座 yaw；
2. 竖直平面内末端位置任务是冗余的，因此根据目标水平距离把肩关节角固定为近/中/远三档；
3. 肩关节固定后，肘关节和腕关节构成二维两连杆问题；
4. 理论上两连杆有肘上/肘下两解，本实现只取“肘部向上”的唯一工程解；
5. 从 50x50 端面抓取时，沿端面法向从预抓取点分段靠近到抓取点。
"""

from __future__ import print_function

import math

from .common import INITIAL_POSITION_SERVOS, IKNoSolution, MotionStep, clamp


class ArmGrabConfig(object):
    """抓取与本地 IK 参数。"""

    def __init__(
        self,
        pitch=-175.0,
        pitch_min=-180.0,
        pitch_max=0.0,
        pitch_step=1.0,
        approach_y=-0.01,
        approach_z=0.02,
        lift_z=0.045,
        open_gripper=400,
        grasp_open_gripper=900,
        close_gripper=10,
        include_retreat=False,
        retreat_z=0.04,
        link_l1=0.0610,
        link_l2=0.1016,
        link_l3=0.0964,
        link_l4=0.2700,
        base_forward_axis="y",
        api_x_sign=-1.0,
        gripper_rotation_sign=-1.0,
        approach_steps=8,
        approach_step_duration_ms=150,
        safe_servos=((3, 256), (4, 755), (5, 636), (6, 519)),
        shoulder_near_distance=0.12,
        shoulder_far_distance=0.20,
        shoulder_near_deg=75.0,
        shoulder_mid_deg=45.0,
        shoulder_far_deg=15.0,
        shoulder_search_step_deg=5.0,
        shoulder_search_span_deg=80.0,
        servo3_center=500.0,
        servo4_center=500.0,
        servo5_center=114.0,
        servo6_center=500.0,
        servo3_direction=1.0,
        servo4_direction=-1.0,
        servo5_direction=1.0,
        servo6_direction=1.0,
        joint_min_pulse=0,
        joint_max_pulse=1000,
    ):
        # pitch 相关字段保留兼容旧脚本；新 IK 用 approach_dir 计算工具角 phi。
        self.pitch = float(pitch)
        self.pitch_min = float(pitch_min)
        self.pitch_max = float(pitch_max)
        self.pitch_step = float(pitch_step)

        self.approach_y = float(approach_y)
        self.approach_z = float(approach_z)
        self.lift_z = float(lift_z)
        self.open_gripper = int(open_gripper)
        # Grasp preparation and placement release use separate calibrated
        # ID1 targets so each phase can be tuned independently.
        self.grasp_open_gripper = int(grasp_open_gripper)
        self.close_gripper = int(close_gripper)
        self.include_retreat = bool(include_retreat)
        self.retreat_z = float(retreat_z)

        # Link lengths in meters. L4 is the measured length of the current
        # extended end-effector assembly, not the original ArmPi value.
        self.link_l1 = float(link_l1)
        self.link_l2 = float(link_l2)
        self.link_l3 = float(link_l3)
        self.link_l4 = float(link_l4)

        # 当前工作空间约定：
        # 对外 API 使用右手系：+x 与旧 ArmPi/机械臂内部坐标相反，+y 为正前方，+z 向上。
        # 内部 IK 和舵机映射仍沿用已经验证过的旧机械臂坐标，只在投影边界做 x 镜像。
        self.api_x_sign = -1.0 if float(api_x_sign) < 0.0 else 1.0

        # base_forward_axis 表示 theta6=0 时，机械臂在基座坐标系中的实际正前方。
        # 支持 "x", "-x", "y", "-y"。
        self.base_forward_axis = str(base_forward_axis)

        # 对外右手系下的夹爪自转正方向与旧机械臂内部约定相反；保留配置便于实机校准。
        self.gripper_rotation_sign = -1.0 if float(gripper_rotation_sign) < 0.0 else 1.0

        self.approach_steps = int(approach_steps)
        self.approach_step_duration_ms = int(approach_step_duration_ms)
        self.safe_servos = tuple((int(servo_id), int(pulse)) for servo_id, pulse in safe_servos)

        # 肩关节距离分档。距离越近，肩角越大；距离越远，肩角越小。
        self.shoulder_near_distance = float(shoulder_near_distance)
        self.shoulder_far_distance = float(shoulder_far_distance)
        self.shoulder_near_deg = float(shoulder_near_deg)
        self.shoulder_mid_deg = float(shoulder_mid_deg)
        self.shoulder_far_deg = float(shoulder_far_deg)
        self.shoulder_search_step_deg = float(shoulder_search_step_deg)
        self.shoulder_search_span_deg = float(shoulder_search_span_deg)

        # 舵机映射默认对齐原 ArmPi kinematics/ik_transform.py：
        # servo3 = 500 + theta3 * 1000 / 240
        # servo4 = 500 - theta4 * 1000 / 240
        # servo5 = 500 + theta5 * 1000 / 240
        # servo6 = 500 + theta6 * 1000 / 240
        self.servo_centers = {
            "servo3": float(servo3_center),
            "servo4": float(servo4_center),
            "servo5": float(servo5_center),
            "servo6": float(servo6_center),
        }
        self.servo_directions = {
            "servo3": float(servo3_direction),
            "servo4": float(servo4_direction),
            "servo5": float(servo5_direction),
            "servo6": float(servo6_direction),
        }

        self.joint_min_pulse = int(joint_min_pulse)
        self.joint_max_pulse = int(joint_max_pulse)


def add_kinematics_path():
    """兼容旧检查脚本的占位函数。"""

    return None


def find_inverse_kinematics_so():
    """兼容旧检查脚本的占位函数。"""

    return None


def pulse_from_joint_deg(angle_deg, center=500.0, direction=1.0):
    """把几何关节角转换为 0..1000 pulse。"""

    return clamp(center + direction * float(angle_deg) * 1000.0 / 240.0)


def raw_pulse_from_joint_deg(angle_deg, center=500.0, direction=1.0):
    """返回未限幅的 pulse，用于 IK 可执行性检查。"""

    return center + direction * float(angle_deg) * 1000.0 / 240.0


def wrist_servo(rotation_deg):
    """夹爪自转角转 2 号舵机 pulse，500 为中位。"""

    return pulse_from_joint_deg(rotation_deg)


def adapted_wrist_servo(rotation_deg, config):
    """把对外 API 的夹爪自转角转换为 2 号舵机 pulse。"""

    sign = getattr(config, "gripper_rotation_sign", 1.0)
    return wrist_servo(float(sign) * float(rotation_deg))


def arm_servos(servo_data):
    """从 IK 输出中取出机械臂主体 3..6 号舵机。"""

    return (
        (3, servo_data["servo3"]),
        (4, servo_data["servo4"]),
        (5, servo_data["servo5"]),
        (6, servo_data["servo6"]),
    )


def interpolate_line(start, end, steps):
    """生成 start -> end 的直线插值点，不包含 start，包含 end。"""

    steps = max(1, int(steps))
    start = tuple(float(x) for x in start)
    end = tuple(float(x) for x in end)
    points = []
    for index in range(1, steps + 1):
        t = float(index) / float(steps)
        points.append(tuple((1.0 - t) * start[i] + t * end[i] for i in range(3)))
    return points


class LocalGeometricArmIK(object):
    """本地几何 IK：固定肩关节分档，肘部向上唯一解。"""

    def __init__(self, config=None):
        self.config = config or ArmGrabConfig()

    def setPitchRanges(self, coordinate_data, alpha, alpha1, alpha2, d=1.0):
        """兼容原 ArmIK.setPitchRanges 的接口。"""

        phi = math.radians(float(alpha)) if abs(float(alpha)) <= math.pi else 0.0
        return self.solve(coordinate_data, phi=phi, used_pitch=alpha)

    def solve(self, coordinate_data, phi=0.0, used_pitch=None):
        """把末端目标点解算成关节角和舵机 pulse。"""

        x, y, z = [float(value) for value in coordinate_data]
        l1 = self.config.link_l1
        l2 = self.config.link_l2
        l3 = self.config.link_l3
        l4 = self.config.link_l4

        radial, lateral = self._project_to_arm_plane(x, y)
        base_rad = math.atan2(lateral, radial)
        radial = math.hypot(radial, lateral)
        height = z - l1
        phi = float(phi)

        solution = self._solve_with_shoulder_candidates(
            coordinate_data,
            radial,
            height,
            base_rad,
            l2,
            l3,
            l4,
        )
        (
            shoulder_rad,
            elbow_rad,
            wrist_rad,
            l4_abs_rad,
            elbow_point,
            distance,
            servo_data,
            shoulder_selected_deg,
        ) = solution

        theta3 = math.degrees(wrist_rad)
        theta4 = math.degrees(elbow_rad)
        theta5 = math.degrees(shoulder_rad)
        theta6 = math.degrees(base_rad)

        ik_angles = {
            "theta3": theta3,
            "theta4": theta4,
            "theta5": theta5,
            "theta6": theta6,
            "phi": math.degrees(phi),
            "shoulder_mode": self._shoulder_mode(radial),
            "shoulder_selected_deg": shoulder_selected_deg,
            "elbow_mode": "up",
            "elbow_point_rz": (elbow_point[0], l1 + elbow_point[1]),
            "l4_abs_deg": math.degrees(l4_abs_rad),
            "residual_distance": distance,
            "unit": "deg",
        }
        return ik_angles, servo_data, used_pitch

    def _solve_with_shoulder_candidates(self, coordinate_data, radial, height, base_rad, l2, l3, l4):
        last_error = None
        best_solution = None
        best_score = None
        preferred_shoulder_deg = self._shoulder_angle_deg(radial)
        for shoulder_deg in self._shoulder_angle_candidates(radial):
            try:
                shoulder_rad = math.radians(shoulder_deg)
                shoulder_end_r = l2 * math.cos(shoulder_rad)
                shoulder_end_h = l2 * math.sin(shoulder_rad)
                target_r = radial - shoulder_end_r
                target_h = height - shoulder_end_h
                distance = math.hypot(target_r, target_h)
                self._check_reachable(distance, l3, l4, coordinate_data, radial)

                l3_abs_rad, l4_abs_rad, elbow_point = self._solve_l3_l4_elbow_up(
                    target_r,
                    target_h,
                    shoulder_end_r,
                    shoulder_end_h,
                    l3,
                    l4,
                    distance,
                )

                elbow_rad = l3_abs_rad - shoulder_rad
                wrist_rad = l4_abs_rad - l3_abs_rad
                raw_servo_data = self._joint_angles_to_raw_servos(
                    wrist_deg=math.degrees(wrist_rad),
                    elbow_deg=math.degrees(elbow_rad),
                    shoulder_deg=math.degrees(shoulder_rad),
                    base_deg=math.degrees(base_rad),
                )
                self._check_servo_limits(raw_servo_data, coordinate_data)
                servo_data = {name: clamp(pulse) for name, pulse in raw_servo_data.items()}
                solution = (
                    shoulder_rad,
                    elbow_rad,
                    wrist_rad,
                    l4_abs_rad,
                    elbow_point,
                    distance,
                    servo_data,
                    shoulder_deg,
                )
                score = self._score_ik_solution(raw_servo_data, shoulder_deg, preferred_shoulder_deg)
                if best_score is None or score > best_score:
                    best_score = score
                    best_solution = solution
            except IKNoSolution as exc:
                last_error = exc

        if best_solution is not None:
            return best_solution
        if last_error is not None:
            raise last_error
        raise IKNoSolution("IK 无解：coordinate={}".format(coordinate_data))

    def _score_ik_solution(self, raw_servo_data, shoulder_deg, preferred_shoulder_deg):
        """给可执行 IK 解打分。

        先保证所有舵机离极限尽量远，再轻微偏好原来的肩关节分档角度。
        这样不会因为第一个候选刚好可用，就选到腕关节贴边的姿态。
        """

        min_margin = min(
            min(
                pulse - self.config.joint_min_pulse,
                self.config.joint_max_pulse - pulse,
            )
            for pulse in raw_servo_data.values()
        )
        shoulder_penalty = abs(float(shoulder_deg) - float(preferred_shoulder_deg))
        return min_margin - 0.25 * shoulder_penalty

    def _solve_l3_l4_elbow_up(self, target_r, target_h, shoulder_end_r, shoulder_end_h, l3, l4, distance):
        """固定肩关节后，解 L3/L4 两连杆并选择肘部更高的分支。

        target_r/target_h 是从 L2 末端指向 TCP 的向量。
        elbow_point 返回的是相对肩关节 A 的 (r, h)，其中 h 不含 L1。
        """

        base_line = math.atan2(target_h, target_r)
        offset = self._safe_acos((l3 * l3 + distance * distance - l4 * l4) / (2.0 * l3 * distance))

        candidates = []
        for l3_abs_rad in (base_line + offset, base_line - offset):
            l3_end_r = shoulder_end_r + l3 * math.cos(l3_abs_rad)
            l3_end_h = shoulder_end_h + l3 * math.sin(l3_abs_rad)

            # L4 的绝对方向由“肘点 -> TCP”唯一确定，不能再强行设为 phi。
            l4_vec_r = target_r - l3 * math.cos(l3_abs_rad)
            l4_vec_h = target_h - l3 * math.sin(l3_abs_rad)
            l4_abs_rad = math.atan2(l4_vec_h, l4_vec_r)
            candidates.append((l3_abs_rad, l4_abs_rad, (l3_end_r, l3_end_h)))

        return max(candidates, key=lambda item: item[2][1])

    def _project_to_arm_plane(self, x, y):
        """把基座 x/y 坐标投影成机械臂竖直平面的前向/横向距离。

        forward 是 theta6=0 时机械臂面对的方向；lateral 是 yaw 正方向一侧。
        """

        x = self.config.api_x_sign * float(x)
        y = float(y)
        axis = self.config.base_forward_axis
        if axis == "x":
            return x, y
        if axis == "-x":
            return -x, -y
        if axis == "y":
            return y, x
        if axis == "-y":
            return -y, -x
        raise ValueError("不支持的 base_forward_axis={!r}，应为 x/-x/y/-y".format(axis))

    def _xy_from_arm_plane(self, radial, base_rad):
        forward = radial * math.cos(base_rad)
        lateral = radial * math.sin(base_rad)
        axis = self.config.base_forward_axis
        if axis == "x":
            x, y = forward, lateral
        elif axis == "-x":
            x, y = -forward, -lateral
        elif axis == "y":
            x, y = lateral, forward
        elif axis == "-y":
            x, y = -lateral, -forward
        else:
            raise ValueError("不支持的 base_forward_axis={!r}，应为 x/-x/y/-y".format(axis))
        return self.config.api_x_sign * x, y

    def _shoulder_mode(self, radial):
        if radial <= self.config.shoulder_near_distance:
            return "near"
        if radial >= self.config.shoulder_far_distance:
            return "far"
        return "mid"

    def _shoulder_angle_deg(self, radial):
        mode = self._shoulder_mode(radial)
        if mode == "near":
            return self.config.shoulder_near_deg
        if mode == "far":
            return self.config.shoulder_far_deg
        return self.config.shoulder_mid_deg

    def _shoulder_angle_candidates(self, radial):
        """按距离分档给肩角首选值；首选不可执行时，在附近搜索。

        这仍然保留“距离越近肩角越大”的策略，只是避免某个固定角导致腕部超限。
        """

        preferred = self._shoulder_angle_deg(radial)
        step = max(1.0, abs(self.config.shoulder_search_step_deg))
        span = max(0.0, abs(self.config.shoulder_search_span_deg))
        candidates = [preferred]
        count = int(span / step)
        for index in range(1, count + 1):
            candidates.append(preferred - index * step)
            candidates.append(preferred + index * step)
        out = []
        seen = set()
        for angle in candidates:
            angle = max(-90.0, min(120.0, angle))
            key = round(angle, 6)
            if key not in seen:
                seen.add(key)
                out.append(angle)
        return out

    def _joint_angles_to_raw_servos(self, wrist_deg, elbow_deg, shoulder_deg, base_deg):
        """按实测 ID 和正方向把几何关节角转换为未限幅 pulse。"""

        return {
            "servo3": raw_pulse_from_joint_deg(
                wrist_deg,
                center=self.config.servo_centers["servo3"],
                direction=self.config.servo_directions["servo3"],
            ),
            "servo4": raw_pulse_from_joint_deg(
                elbow_deg,
                center=self.config.servo_centers["servo4"],
                direction=self.config.servo_directions["servo4"],
            ),
            "servo5": raw_pulse_from_joint_deg(
                shoulder_deg,
                center=self.config.servo_centers["servo5"],
                direction=self.config.servo_directions["servo5"],
            ),
            "servo6": raw_pulse_from_joint_deg(
                base_deg,
                center=self.config.servo_centers["servo6"],
                direction=self.config.servo_directions["servo6"],
            ),
        }

    @staticmethod
    def _safe_acos(value):
        return math.acos(max(-1.0, min(1.0, value)))

    @staticmethod
    def _check_reachable(distance, l3, l4, coordinate_data, radial):
        min_reach = abs(l3 - l4)
        max_reach = l3 + l4
        eps = 1e-9
        if distance <= eps or distance > max_reach + eps or distance < min_reach - eps:
            raise IKNoSolution(
                "IK 无解：coordinate={}，r={:.4f}m，肩角固定后 L3/L4 目标距离={:.4f}m，"
                "可达范围=[{:.4f}, {:.4f}]m".format(
                    coordinate_data,
                    radial,
                    distance,
                    min_reach,
                    max_reach,
                )
            )

    def _check_servo_limits(self, servo_data, coordinate_data):
        bad = {
            name: pulse
            for name, pulse in servo_data.items()
            if pulse < self.config.joint_min_pulse or pulse > self.config.joint_max_pulse
        }
        if bad:
            raise IKNoSolution("IK 解超出舵机 pulse 范围：coordinate={} bad={}".format(coordinate_data, bad))

    def forward_kine(self, theta5_deg, theta4_deg, theta3_deg, theta6_deg=0.0):
        """按同一简化模型做正运动学检查。"""

        l1 = self.config.link_l1
        l2 = self.config.link_l2
        l3 = self.config.link_l3
        l4 = self.config.link_l4
        shoulder = math.radians(theta5_deg)
        elbow = math.radians(theta4_deg)
        wrist = math.radians(theta3_deg)
        base = math.radians(theta6_deg)

        l3_abs = shoulder + elbow
        l4_abs = l3_abs + wrist
        radial = l2 * math.cos(shoulder) + l3 * math.cos(l3_abs) + l4 * math.cos(l4_abs)
        z = l1 + l2 * math.sin(shoulder) + l3 * math.sin(l3_abs) + l4 * math.sin(l4_abs)

        x, y = self._xy_from_arm_plane(radial, base)
        return x, y, z


def solve_pose(arm_ik, coordinate, pitch, pitch_min, pitch_max, pitch_step, phi=None):
    """解算一个末端坐标，返回 (ik_angles, servo_data, used_pitch)。"""

    if hasattr(arm_ik, "solve"):
        result = arm_ik.solve(coordinate, phi=0.0 if phi is None else phi, used_pitch=pitch)
    else:
        result = arm_ik.setPitchRanges(coordinate, pitch, pitch_min, pitch_max, pitch_step)
    if not result:
        return None
    ik_angles, servo_data, used_pitch = result
    return ik_angles, servo_data, used_pitch


class ArmGrabPlanner(object):
    """机械臂抓取规划器。"""

    def __init__(self, config=None, arm_ik=None):
        self.config = config or ArmGrabConfig()
        self.arm_ik = arm_ik or LocalGeometricArmIK(self.config)

    def end_effector_points(self, object_position):
        """兼容旧接口：由单个抓取点生成接近点、目标点、抬升点。"""

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

    def solve_end_effector(self, coordinate, phi=0.0):
        """把一个末端坐标解算成 servo3..6 的 pulse。"""

        pose = solve_pose(
            self.arm_ik,
            coordinate,
            self.config.pitch,
            self.config.pitch_min,
            self.config.pitch_max,
            self.config.pitch_step,
            phi=phi,
        )
        if pose is None:
            raise IKNoSolution("IK 无解：coordinate={}".format(coordinate))

        ik_angles, servo_data, used_pitch = pose
        return {
            "coordinate": coordinate,
            "servo_pulses": servo_data,
            "ik_angles": ik_angles,
            "used_pitch": used_pitch,
        }

    def plan_grasp_pose(self, grasp_pose, include_home=False):
        """根据包含 50x50 端面路径字段的抓取位姿生成动作序列。"""

        if not getattr(grasp_pose, "has_approach_path", lambda: False)():
            return self.plan_grab(grasp_pose.position, rotation_deg=grasp_pose.rotation_deg, include_home=include_home)

        pre_point = tuple(grasp_pose.pre_point)
        grasp_point = tuple(grasp_pose.grasp_point)
        lift_point = tuple(grasp_pose.lift_point)
        phi = float(getattr(grasp_pose, "phi", 0.0))
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
        ]

        solved_pre = self.solve_end_effector(pre_point, phi=phi)
        steps.append(
            MotionStep(
                "pre_grasp",
                pre_point,
                1000,
                arm_servos(solved_pre["servo_pulses"]),
                solved_pre["ik_angles"],
                solved_pre["used_pitch"],
            )
        )

        for index, point in enumerate(interpolate_line(pre_point, grasp_point, self.config.approach_steps), 1):
            solved = self.solve_end_effector(point, phi=phi)
            steps.append(
                MotionStep(
                    "approach_{:02d}".format(index),
                    point,
                    self.config.approach_step_duration_ms,
                    arm_servos(solved["servo_pulses"]),
                    solved["ik_angles"],
                    solved["used_pitch"],
                )
            )

        steps.append(MotionStep("close_gripper", None, 600, ((1, self.config.close_gripper),)))
        steps.append(MotionStep("hold_after_grasp", None, 300, ()))

        solved_lift = self.solve_end_effector(lift_point, phi=phi)
        steps.append(
            MotionStep(
                "lift",
                lift_point,
                800,
                arm_servos(solved_lift["servo_pulses"]),
                solved_lift["ik_angles"],
                solved_lift["used_pitch"],
            )
        )

        if include_home:
            steps.append(
                MotionStep(
                    "home_from_sorting_py",
                    None,
                    1200,
                INITIAL_POSITION_SERVOS,
                )
            )
        return steps

    def plan_grab(self, object_position, rotation_deg=0.0, include_home=False):
        """兼容旧接口：给单个抓取点时生成普通抓取动作序列。"""

        points = self.end_effector_points(object_position)
        solve_names = ["approach", "target", "lift"]
        if self.config.include_retreat:
            solve_names.append("retreat")

        solved = {}
        for name in solve_names:
            try:
                solved[name] = self.solve_end_effector(points[name], phi=0.0)
            except IKNoSolution as exc:
                raise IKNoSolution("{}，步骤={}".format(exc, name))

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
            steps.append(
                MotionStep(
                    "home_from_sorting_py",
                    None,
                    1200,
                INITIAL_POSITION_SERVOS,
                )
            )
        return steps


def plan_grab_motion(x, y, z, rotation_deg=0.0, config=None, include_home=False, arm_ik=None):
    """一次性规划接口。"""

    planner = ArmGrabPlanner(config=config, arm_ik=arm_ik)
    return planner.plan_grab((x, y, z), rotation_deg=rotation_deg, include_home=include_home)
