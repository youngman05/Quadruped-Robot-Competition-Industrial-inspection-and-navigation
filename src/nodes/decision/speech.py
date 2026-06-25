#!/usr/bin/env python3
"""ROS2 node: Chinese TTS speech broadcast (待实现).

TODO:
    - Subscribe to /task/report_text
    - Synthesize speech (espeak / gTTS / edge-tts)
    - Output via speaker
    - Support queue of messages
"""
import rclpy
from rclpy.node import Node


class SpeechNode(Node):
    """Speech broadcast node (placeholder)."""

    def __init__(self) -> None:
        super().__init__("speech_node")
        self.get_logger().warn("speech_node is a placeholder — not implemented yet")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SpeechNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
