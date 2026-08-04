import importlib.util
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

try:
    import rclpy
    from geometry_msgs.msg import TransformStamped, Twist
    from nav_msgs.msg import Odometry
    from tf2_ros import TransformBroadcaster
except ImportError:
    rclpy = None


REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = REPO_ROOT / "scripts" / "nav2_waypoint_sequence_probe.py"


def load_probe_module():
    spec = importlib.util.spec_from_file_location("nav2_waypoint_probe", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipIf(rclpy is None, "ROS2 Python packages are unavailable")
class CallbackStressTests(unittest.TestCase):
    def test_tf_updates_are_not_starved_by_cmd_and_odom_callbacks(self):
        module = load_probe_module()
        steps = module.describe_route_preset("nav-only-turn-validation")["steps"]
        self.assertEqual(
            [step["kind"] for step in steps],
            ["nav2", "nav2", "nav2", "yaw_only"],
        )
        self.assertEqual(steps[1]["label"], "pos1_left_clear")
        self.assertEqual((steps[1]["x"], steps[1]["y"]), (0.60, 2.90))
        suffix = str(int(time.time() * 1e6))
        args = SimpleNamespace(
            odom_topic="/probe_stress_odom_" + suffix,
            cmd_vel_topic="/probe_stress_cmd_" + suffix,
            se2_cmd_topic="/probe_stress_precision_" + suffix,
            frame_id="map",
            base_frame="probe_stress_base_" + suffix,
            tf_timeout=0.02,
            odom_file="/tmp/nonexistent_probe_stress_odom.json",
            map_from_odom_x=0.0,
            map_from_odom_y=0.0,
            map_from_odom_yaw=0.0,
            se2_vy_sign=1.0,
        )

        rclpy.init()
        probe = None
        publisher = None
        publish_thread = None
        stop = threading.Event()
        try:
            probe = module.Nav2WaypointSequenceProbe(args)
            publisher = rclpy.create_node("probe_stress_publishers_" + suffix)
            tf_pub = TransformBroadcaster(publisher)
            odom_pub = publisher.create_publisher(Odometry, args.odom_topic, 10)
            cmd_pub = publisher.create_publisher(Twist, args.cmd_vel_topic, 50)

            def publish_loop():
                index = 0
                next_tf = time.monotonic()
                next_cmd = next_tf
                while not stop.is_set():
                    now = time.monotonic()
                    if now >= next_tf:
                        stamp = publisher.get_clock().now().to_msg()
                        transform = TransformStamped()
                        transform.header.stamp = stamp
                        transform.header.frame_id = args.frame_id
                        transform.child_frame_id = args.base_frame
                        transform.transform.translation.x = index / 1000.0
                        transform.transform.rotation.w = 1.0
                        tf_pub.sendTransform(transform)

                        odom = Odometry()
                        odom.header.stamp = stamp
                        odom.pose.pose.position.x = index / 1000.0
                        odom.pose.pose.orientation.w = 1.0
                        odom_pub.publish(odom)
                        index += 1
                        next_tf += 1.0 / 60.0
                    if now >= next_cmd:
                        command = Twist()
                        command.angular.z = 0.02
                        cmd_pub.publish(command)
                        next_cmd += 1.0 / 40.0
                    time.sleep(0.001)

            publish_thread = threading.Thread(target=publish_loop, daemon=True)
            publish_thread.start()
            probe._begin_segment_logging()

            ages = []
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                rclpy.spin_once(probe, timeout_sec=0.005)
                pose = probe.lookup_map_pose(allow_fallback=False)
                if pose.get("ok") and pose.get("tf_age_sec") is not None:
                    ages.append(pose["tf_age_sec"])
                time.sleep(0.005)

            self.assertTrue(ages)
            self.assertLess(max(ages[-100:]), 0.20)
            self.assertIsNotNone(probe.latest_odom)
            self.assertGreater(probe.segment_cmd["cmd_count"], 50)
        finally:
            stop.set()
            if publish_thread is not None:
                publish_thread.join(timeout=2.0)
            if probe is not None:
                probe._clear_segment_logging()
                probe.shutdown_background_listeners()
                probe.action_client.destroy()
                probe.destroy_node()
            if publisher is not None:
                publisher.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    unittest.main()
