"""
cuVSLAM Bridge — relays cuVSLAM Docker odometry into the Nav2 frame tree.

ROS2 Node: cuvslam_bridge

Input (from cuVSLAM Docker container):
  /visual_slam/tracking/odometry  — nav_msgs/Odometry
  /visual_slam/status             — std_msgs/String

Output (to Nav2):
  /odom                            — nav_msgs/Odometry (child_frame_id=base_link)
  /slam/status                     — std_msgs/String ("ok" / "lost")
  TF: odom → base_link

定位策略: 完全信任 cuVSLAM 视觉里程计结果, 不融合腿里程计或 IMU。
"""

import math

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from std_msgs.msg import String
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster


def _normalize_quat(q):
    norm = math.sqrt(sum(v * v for v in q))
    if norm == 0.0:
        return (0.0, 0.0, 0.0, 1.0)
    return tuple(v / norm for v in q)


def _quat_conjugate(q):
    x, y, z, w = q
    return (-x, -y, -z, w)


def _quat_multiply_raw(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _quat_multiply(a, b):
    return _normalize_quat(_quat_multiply_raw(a, b))


def _rotate_vector(q, v):
    qv = (v[0], v[1], v[2], 0.0)
    rotated = _quat_multiply_raw(
        _quat_multiply_raw(q, qv),
        _quat_conjugate(q),
    )
    return (rotated[0], rotated[1], rotated[2])


def _quat_from_rpy(roll, pitch, yaw):
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)
    return _normalize_quat((
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    ))


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


class CuvslamBridge(Node):
    """Bridge cuVSLAM odometry to Nav2-compatible /odom + TF."""

    def __init__(self):
        super().__init__("cuvslam_bridge")

        self.declare_parameter("slam_odom_topic", "/visual_slam/tracking/odometry")
        self.declare_parameter("slam_status_topic", "/visual_slam/status")
        self.declare_parameter("camera_frame", "camera_link")
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("odom_frame", "odom")
        self.declare_parameter("transform_camera_pose_to_base", True)
        self.declare_parameter("base_to_camera_x", 0.080)
        self.declare_parameter("base_to_camera_y", 0.000)
        self.declare_parameter("base_to_camera_z", 0.493)
        self.declare_parameter("base_to_camera_roll", 0.0)
        self.declare_parameter("base_to_camera_pitch", 0.523599)
        self.declare_parameter("base_to_camera_yaw", 0.0)

        slam_odom = self.get_parameter("slam_odom_topic").value
        slam_status = self.get_parameter("slam_status_topic").value
        self._camera_frame = self.get_parameter("camera_frame").value
        self._base_frame = self.get_parameter("base_frame").value
        self._odom_frame = self.get_parameter("odom_frame").value
        self._transform_camera_pose_to_base = bool(
            self.get_parameter("transform_camera_pose_to_base").value
        )
        self._t_base_camera = (
            float(self.get_parameter("base_to_camera_x").value),
            float(self.get_parameter("base_to_camera_y").value),
            float(self.get_parameter("base_to_camera_z").value),
        )
        self._q_base_camera = _quat_from_rpy(
            float(self.get_parameter("base_to_camera_roll").value),
            float(self.get_parameter("base_to_camera_pitch").value),
            float(self.get_parameter("base_to_camera_yaw").value),
        )

        # T_odom_base = T_odom_camera * inverse(T_base_camera).
        self._q_camera_base = _quat_conjugate(self._q_base_camera)
        self._t_camera_base = _rotate_vector(
            self._q_camera_base,
            tuple(-v for v in self._t_base_camera),
        )
        self._warned_unexpected_child = False

        # cuVSLAM composable node uses BEST_EFFORT — must match
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        best_effort = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)

        self._odom_sub = self.create_subscription(
            Odometry, slam_odom, self._odom_callback, best_effort,
        )
        self._status_sub = self.create_subscription(
            String, slam_status, self._status_callback, best_effort,
        )

        self._odom_pub = self.create_publisher(Odometry, "/odom", 10)
        self._status_pub = self.create_publisher(String, "/slam/status", 10)
        self._tf_broadcaster = TransformBroadcaster(self)

        self.get_logger().info(
            f"cuVSLAM bridge: {slam_odom} → /odom + TF"
        )
        self.get_logger().info(
            "base_link->camera_link extrinsic: "
            f"t={self._t_base_camera}, q={self._q_base_camera}, "
            f"transform_camera_pose_to_base={self._transform_camera_pose_to_base}"
        )

    def _odom_callback(self, msg: Odometry):
        """Publish real odom->base_link, not just a renamed camera pose."""
        child_frame = (msg.child_frame_id or "").strip()
        input_is_base = child_frame == self._base_frame
        should_transform = self._transform_camera_pose_to_base and not input_is_base

        if should_transform and child_frame and child_frame != self._camera_frame:
            if not self._warned_unexpected_child:
                self.get_logger().warn(
                    "Input odometry child_frame_id is "
                    f"'{child_frame}', expected '{self._camera_frame}'. "
                    "Applying camera->base transform anyway; update camera_frame "
                    "parameter if this frame is intentional."
                )
                self._warned_unexpected_child = True

        if should_transform:
            pos, rot = self._camera_pose_to_base_pose(msg)
            twist_linear, twist_angular = self._camera_twist_to_base_twist(msg)
        else:
            p = msg.pose.pose.position
            q = msg.pose.pose.orientation
            pos = (p.x, p.y, p.z)
            rot = _normalize_quat((q.x, q.y, q.z, q.w))
            lin = msg.twist.twist.linear
            ang = msg.twist.twist.angular
            twist_linear = (lin.x, lin.y, lin.z)
            twist_angular = (ang.x, ang.y, ang.z)

        out = Odometry()
        out.header = msg.header
        out.header.frame_id = self._odom_frame
        out.child_frame_id = self._base_frame
        out.pose.covariance = list(msg.pose.covariance)
        out.pose.pose.position.x = pos[0]
        out.pose.pose.position.y = pos[1]
        out.pose.pose.position.z = pos[2]
        out.pose.pose.orientation.x = rot[0]
        out.pose.pose.orientation.y = rot[1]
        out.pose.pose.orientation.z = rot[2]
        out.pose.pose.orientation.w = rot[3]
        out.twist.covariance = list(msg.twist.covariance)
        out.twist.twist.linear.x = twist_linear[0]
        out.twist.twist.linear.y = twist_linear[1]
        out.twist.twist.linear.z = twist_linear[2]
        out.twist.twist.angular.x = twist_angular[0]
        out.twist.twist.angular.y = twist_angular[1]
        out.twist.twist.angular.z = twist_angular[2]
        self._odom_pub.publish(out)

        # TF: odom → base_link
        t = TransformStamped()
        t.header.stamp = msg.header.stamp
        t.header.frame_id = self._odom_frame
        t.child_frame_id = self._base_frame
        t.transform.translation.x = pos[0]
        t.transform.translation.y = pos[1]
        t.transform.translation.z = pos[2]
        t.transform.rotation.x = rot[0]
        t.transform.rotation.y = rot[1]
        t.transform.rotation.z = rot[2]
        t.transform.rotation.w = rot[3]
        self._tf_broadcaster.sendTransform(t)

    def _camera_pose_to_base_pose(self, msg: Odometry):
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        t_odom_camera = (p.x, p.y, p.z)
        q_odom_camera = _normalize_quat((q.x, q.y, q.z, q.w))

        t_offset_odom = _rotate_vector(q_odom_camera, self._t_camera_base)
        t_odom_base = tuple(t_odom_camera[i] + t_offset_odom[i] for i in range(3))
        q_odom_base = _quat_multiply(q_odom_camera, self._q_camera_base)
        return t_odom_base, q_odom_base

    def _camera_twist_to_base_twist(self, msg: Odometry):
        linear = msg.twist.twist.linear
        angular = msg.twist.twist.angular
        v_camera_in_camera = (linear.x, linear.y, linear.z)
        w_camera_in_camera = (angular.x, angular.y, angular.z)

        w_base = _rotate_vector(self._q_base_camera, w_camera_in_camera)
        v_camera_origin_base = _rotate_vector(
            self._q_base_camera,
            v_camera_in_camera,
        )
        correction = _cross(w_base, self._t_base_camera)
        v_base = tuple(v_camera_origin_base[i] - correction[i] for i in range(3))
        return v_base, w_base

    def _status_callback(self, msg: String):
        """Translate cuVSLAM status to /slam/status for task_manager."""
        data = msg.data.strip().lower()
        if data in ("tracking", "ok", "initialized", "running", "nominal"):
            status = "ok"
        elif data in ("lost", "relocalizing", "error", "degraded", "unknown"):
            status = "lost"
        else:
            status = data
        out = String()
        out.data = status
        self._status_pub.publish(out)


def main(args=None):
    import time
    rclpy.init(args=args)
    node = CuvslamBridge()
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
