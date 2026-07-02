#!/usr/bin/env python3
"""
YOLO 图像中继 — 订阅 /yolo/image，低分辨率 JPEG + HTTP 服务。

发布:
  HTTP GET http://<jetson>:8899/  → 自动刷新的 HTML 页面
  HTTP GET http://<jetson>:8899/yolo_latest.jpg → 最新帧

参数:
  ros2 run quadruped_robot_competition yolo_image_server --ros-args -p resolution:=320
"""

import io
import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Image
from cv_bridge import CvBridge

# 默认值（可在 competition_params.yaml 覆盖）
DEFAULT_RESOLUTION = 320        # 输出宽度 (保持比例)
DEFAULT_JPEG_QUALITY = 50       # JPEG 质量 1-100
DEFAULT_FPS = 3                 # 最大存储帧率
DEFAULT_OUTPUT_PATH = "/tmp/yolo_latest.jpg"
DEFAULT_HTTP_PORT = 8899

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>YOLO 实时检测</title>
<style>
  body { margin:0; background:#111; display:flex; justify-content:center; align-items:center; height:100vh; }
  img { max-width:100%; max-height:100vh; border:2px solid #333; }
  .info { position:fixed; top:10px; left:10px; color:#888; font:12px monospace; }
</style>
</head><body>
<img id="frame" src="/yolo_latest.jpg" alt="YOLO">
<div class="info" id="info"></div>
<script>
  const img = document.getElementById('frame');
  const info = document.getElementById('info');
  let count = 0;
  const INTERVAL = 350;  // ms
  function reload() {
    img.src = '/yolo_latest.jpg?' + Date.now();
    count++;
    info.textContent = '刷新 #' + count + ' | ' + new Date().toLocaleTimeString();
  }
  img.onload = () => setTimeout(reload, INTERVAL);
  img.onerror = () => setTimeout(reload, 2000);
  setTimeout(reload, INTERVAL);
</script>
</body></html>
"""


class YoloImageServer(Node):
    def __init__(self):
        super().__init__("yolo_image_server")

        self.declare_parameter("resolution", DEFAULT_RESOLUTION)
        self.declare_parameter("jpeg_quality", DEFAULT_JPEG_QUALITY)
        self.declare_parameter("max_fps", DEFAULT_FPS)
        self.declare_parameter("output_path", DEFAULT_OUTPUT_PATH)
        self.declare_parameter("http_port", DEFAULT_HTTP_PORT)

        self._resolution = self.get_parameter("resolution").value
        self._jpeg_quality = self.get_parameter("jpeg_quality").value
        self._max_fps = self.get_parameter("max_fps").value
        self._output_path = self.get_parameter("output_path").value
        self._http_port = self.get_parameter("http_port").value

        self._min_interval = 1.0 / self._max_fps
        self._last_save_time = 0.0
        self._bridge = CvBridge()

        self._sub = self.create_subscription(
            Image, "/yolo/image", self._on_image,
            QoSProfile(
                reliability=ReliabilityPolicy.BEST_EFFORT,
                history=HistoryPolicy.KEEP_LAST,
                depth=1,
            ),
        )

        self.get_logger().info(
            f"YOLO image server ready: resolution={self._resolution}px "
            f"quality={self._jpeg_quality} fps={self._max_fps} "
            f"http://0.0.0.0:{self._http_port}/"
        )

    def _on_image(self, msg: Image):
        now = time.time()
        if now - self._last_save_time < self._min_interval:
            return

        try:
            # ROS2 Image → OpenCV BGR
            frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")

            # 缩放
            h, w = frame.shape[:2]
            if w > self._resolution:
                scale = self._resolution / w
                new_w = self._resolution
                new_h = int(h * scale)
                frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

            # 编码 JPEG 到内存
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality])
            if not ok:
                return

            # 原子写入（避免 HTTP 读到半截文件）
            tmp = self._output_path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(buf.tobytes())
            os.replace(tmp, self._output_path)

            self._last_save_time = now

        except Exception as e:
            self.get_logger().warn(f"frame save error: {e}", throttle_duration_sec=5)


class ImageHandler(BaseHTTPRequestHandler):
    """极简 HTTP — 根路径返回 HTML，/yolo_latest.jpg 返回文件。"""

    output_path = DEFAULT_OUTPUT_PATH
    html = HTML_TEMPLATE

    def log_message(self, format, *args):
        pass  # 静默 HTTP 日志

    def do_GET(self):
        if self.path.startswith("/yolo_latest.jpg"):
            try:
                with open(self.output_path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", len(data))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(data)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"no frame yet")
        else:
            html = self.html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(html))
            self.end_headers()
            self.wfile.write(html)


def _http_thread(http_port, output_path):
    ImageHandler.output_path = output_path
    server = HTTPServer(("0.0.0.0", http_port), ImageHandler)
    server.serve_forever()


def main():
    rclpy.init()

    node = YoloImageServer()
    http_port = node.get_parameter("http_port").value
    output_path = node.get_parameter("output_path").value

    # HTTP server 在后台线程运行
    t = threading.Thread(target=_http_thread, args=(http_port, output_path), daemon=True)
    t.start()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
