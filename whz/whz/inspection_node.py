"""ROS2 service node for WHZ one-shot inspection."""

from __future__ import annotations

import json

import rclpy
from rclpy.node import Node
from std_srvs.srv import Trigger

from whz.audio_player import AudioPlayer
from whz.inspection import InspectionResult, Inspector
from whz.letter_detector import LetterDetector
from whz.paths import default_audio_dir, default_template_dir
from whz.ros_frame_buffer import RosRgbdFrameBuffer


IMAGE_TOPIC = "/camera/color/image_raw"
DEPTH_TOPIC = "/camera/aligned_depth_to_color/image_raw"
REQUIRED_FRAMES = 3
MIN_AGREE_FRAMES = 2
FRAME_TIMEOUT_SEC = 2.0
PLAYER_TIMEOUT_SEC = 10.0
LETTER_MIN_SCORE = 0.38


class WhzInspectionNode(Node):
    """Expose /whz/inspect as a fixed std_srvs/Trigger service."""

    def __init__(self) -> None:
        super().__init__("whz_inspection_node")
        self._frame_buffer = RosRgbdFrameBuffer(
            node=self,
            image_topic=IMAGE_TOPIC,
            depth_topic=DEPTH_TOPIC,
        )
        self._service = self.create_service(Trigger, "/whz/inspect", self._on_inspect)
        self.get_logger().info(
            "WHZ inspection service ready: "
            f"/whz/inspect, image_topic={IMAGE_TOPIC}, depth_topic={DEPTH_TOPIC}"
        )

    def _build_inspector(self) -> Inspector:
        return Inspector(
            letter_detector=LetterDetector(
                template_dir=default_template_dir(),
                min_score=LETTER_MIN_SCORE,
            ),
            audio_player=AudioPlayer(
                audio_dir=default_audio_dir(),
                timeout_sec=PLAYER_TIMEOUT_SEC,
            ),
            play_audio=True,
            min_agree_frames=MIN_AGREE_FRAMES,
        )

    def _on_inspect(self, request: Trigger.Request, response: Trigger.Response) -> Trigger.Response:
        del request
        try:
            frames = self._frame_buffer.wait_for_frames(
                count=REQUIRED_FRAMES,
                timeout_sec=FRAME_TIMEOUT_SEC,
            )
            result = self._build_inspector().inspect_frames(frames)
        except Exception as exc:  # noqa: BLE001
            result = InspectionResult(ok=False, error=str(exc))

        response.success = result.ok
        response.message = json.dumps(result.to_dict(), ensure_ascii=False)
        if result.ok:
            self.get_logger().info(response.message)
        else:
            self.get_logger().warn(response.message)
        return response


def main(args=None) -> None:
    rclpy.init(args=args)
    node = WhzInspectionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
