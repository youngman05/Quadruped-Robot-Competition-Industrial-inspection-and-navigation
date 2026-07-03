#!/usr/bin/env python3
"""
ROS2 node: YOLOv8 instance segmentation using the combined model.

Classes: 0=red, 1=green, 2=obstacle
Model:  src/cv/yolo_detector/projects/combined/model/best.pt

Publishes:
    /yolo/detections      std_msgs/String   JSON detection results
    /yolo/image           sensor_msgs/Image  annotated RGB image
    /yolo/instance_count  std_msgs/Int32     total instance count

Camera support:
    - Default: Intel RealSense D455 (requires pyrealsense2 + cv.realsense_camera)
    - Fallback: USB webcam via cv2.VideoCapture

Dependencies (install on Jetson):
    pip3 install ultralytics torch torchvision
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

# ── 修复 torchvision NMS 与 NVIDIA torch 的 ABI 不兼容 ──
import torch
import torchvision.ops

def _pure_nms(boxes, scores, iou_thres):
    """纯 NumPy NMS，替代 torchvision 的 C++ 版本。"""
    if len(boxes) == 0:
        return torch.zeros(0, dtype=torch.int64)
    boxes_np = boxes.cpu().numpy()
    scores_np = scores.cpu().numpy()
    x1, y1 = boxes_np[:, 0], boxes_np[:, 1]
    x2, y2 = boxes_np[:, 2], boxes_np[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores_np.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[np.where(iou <= iou_thres)[0] + 1]
    return torch.tensor(keep, dtype=torch.int64)

torchvision.ops.nms = _pure_nms
# ─────────────────────────────────────────────────

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Int32, String

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # perception → nodes → src → root
SRC = PROJECT_ROOT / "src"
SCRIPTS = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SCRIPTS))

# Model paths
COMBINED_MODEL = (
    PROJECT_ROOT
    / "src/cv/yolo_detector/projects/combined/model/best.pt"
)


class YoloDetectNode(Node):
    """Real-time YOLOv8-seg instance segmentation on D455 / USB camera."""

    def __init__(self) -> None:
        super().__init__("yolo_detect_publisher_node")

        # ── 声明参数 ──────────────────────────────
        self.declare_parameter("model_path", str(COMBINED_MODEL))
        self.declare_parameter("conf", 0.5)
        self.declare_parameter("imgsz", 640)
        self.declare_parameter("device", "0")           # 0=GPU, cpu=CPU
        self.declare_parameter("interval_sec", 0.1)     # 推理间隔
        self.declare_parameter("frame_id", "d455_color_optical_frame")

        # 相机参数
        self.declare_parameter("use_d455", True)
        self.declare_parameter("use_relay", True)       # 比赛模式：读 Docker relay JPEG
        self.declare_parameter("camera_id", 0)          # USB 摄像头备选
        self.declare_parameter("width", 640)
        self.declare_parameter("height", 480)
        self.declare_parameter("enable_depth", True)    # D455 深度测距
        self.declare_parameter("relay_dir",
                              str(Path.home() / "workspaces/isaac_ros-dev/camera_frames"))

        # 话题参数
        self.declare_parameter("detections_topic", "/yolo/detections")
        self.declare_parameter("image_topic", "/yolo/image")
        self.declare_parameter("count_topic", "/yolo/instance_count")

        # ── 读取参数 ──────────────────────────────
        model_path = str(self.get_parameter("model_path").value)
        self._conf = float(self.get_parameter("conf").value)
        self._imgsz = int(self.get_parameter("imgsz").value)
        self._device = str(self.get_parameter("device").value)
        self._interval_sec = float(self.get_parameter("interval_sec").value)
        self._frame_id = str(self.get_parameter("frame_id").value)
        self._use_d455 = bool(self.get_parameter("use_d455").value)
        self._use_relay = bool(self.get_parameter("use_relay").value)
        self._camera_id = int(self.get_parameter("camera_id").value)
        self._width = int(self.get_parameter("width").value)
        self._height = int(self.get_parameter("height").value)
        self._enable_depth = bool(self.get_parameter("enable_depth").value)
        self._relay_dir = Path(self.get_parameter("relay_dir").value)
        detections_topic = str(self.get_parameter("detections_topic").value)
        image_topic = str(self.get_parameter("image_topic").value)
        count_topic = str(self.get_parameter("count_topic").value)

        # ── 加载模型 ──────────────────────────────
        self.get_logger().info(f"Loading model: {model_path}")
        try:
            from ultralytics import YOLO
            self._model = YOLO(model_path)
            self._class_names = self._model.names  # {0: 'red', 1: 'green', 2: 'obstacle'}
            self.get_logger().info(f"Model loaded: {self._class_names}")
        except ImportError:
            self.get_logger().fatal(
                "ultralytics not installed. Run: pip3 install ultralytics torch"
            )
            raise

        # ── 打开相机 ──────────────────────────────
        self._cam = None
        self._cap = None  # USB fallback

        if self._use_relay:
            # Competition mode: read from Docker relay JPEG (cuVSLAM owns D455)
            self._relay_jpg = self._relay_dir / "latest_color.jpg"
            self._use_d455 = False
            self.get_logger().info(f"Relay mode: reading {self._relay_jpg}")
        elif self._use_d455:
            try:
                from cv.realsense_camera import RealsenseCamera
                self._cam = RealsenseCamera(
                    width=self._width,
                    height=self._height,
                    enable_depth=self._enable_depth,
                    align_depth=True,
                )
                self._cam.start()
                self.get_logger().info(
                    f"D455 started: {self._cam.device_name} (serial={self._cam.serial})"
                )
            except Exception as exc:
                self.get_logger().warn(f"D455 failed ({exc}), falling back to USB camera")
                self._use_d455 = False

        if not self._use_d455 and not self._use_relay:
            import cv2
            self._cap = cv2.VideoCapture(self._camera_id)
            if not self._cap.isOpened():
                raise RuntimeError(f"Cannot open camera id={self._camera_id}")
            actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self._width, self._height = actual_w, actual_h
            self.get_logger().info(f"USB camera opened: {self._width}x{self._height}")

        # ── 发布者 ────────────────────────────────
        self._detections_pub = self.create_publisher(String, detections_topic, 10)
        self._image_pub = self.create_publisher(Image, image_topic, 10)
        self._count_pub = self.create_publisher(Int32, count_topic, 10)

        # ── 定时器 ────────────────────────────────
        self._timer = self.create_timer(self._interval_sec, self._process_frame)
        self._frame_count = 0

        # 每个类的固定颜色 (BGR)
        self._colors = {
            0: (0, 0, 255),      # red   → 蓝色框
            1: (0, 255, 0),      # green → 绿色框
            2: (0, 165, 255),    # obstacle → 橙色框
        }

        self.get_logger().info(f"Publishing: {detections_topic}, {image_topic}, {count_topic}")

    # ────────────────────────────────────────────────
    #  帧处理
    # ────────────────────────────────────────────────
    def _process_frame(self) -> None:
        try:
            # 1. 取帧
            depth_img = None
            if self._use_relay:
                import cv2
                if not self._relay_jpg.exists():
                    return
                try:
                    frame = cv2.imread(str(self._relay_jpg), cv2.IMREAD_COLOR)
                    # Resize to model input size if needed (cuVSLAM uses 1280x720)
                    if frame is not None and frame.shape[1] != self._width:
                        frame = cv2.resize(frame, (self._width, self._height))
                except Exception:
                    return
                if frame is None:
                    return
            elif self._use_d455 and self._cam:
                try:
                    color_img, depth_img = self._cam.get_frames()
                except RuntimeError:
                    self.get_logger().warn("D455 frame timeout, retrying...", throttle_duration_sec=5.0)
                    return
                if color_img is None:
                    return
                frame = color_img
            elif self._cap:
                import cv2
                ret, frame = self._cap.read()
                if not ret or frame is None:
                    return
            else:
                return

            self._frame_count += 1

            # 2. 推理
            results = self._model(
                frame,
                conf=self._conf,
                imgsz=self._imgsz,
                device=self._device,
                verbose=False,
            )

            # 3. 绘制 + 构建检测数据
            annotated = self._draw_results(frame, results, depth_img)

            # 4. 发布
            self._publish_detections(results, depth_img)
            self._publish_image(annotated)

        except Exception as exc:
            self.get_logger().error(f"Frame processing error: {exc}", throttle_duration_sec=5.0)

    # ────────────────────────────────────────────────
    #  绘制分割结果
    # ────────────────────────────────────────────────
    def _draw_results(self, frame, results, depth_img=None) -> np.ndarray:
        import cv2

        annotated = frame.copy()
        r = results[0]

        if r.masks is None or r.boxes is None:
            return annotated

        masks = r.masks.data.cpu().numpy().astype(bool)
        boxes = r.boxes

        overlay = annotated.copy()

        for i, mask in enumerate(masks):
            cls_id = int(boxes.cls[i])
            color = self._colors.get(cls_id, (255, 255, 255))
            overlay[mask] = color
            contours, _ = cv2.findContours(
                mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            cv2.drawContours(annotated, contours, -1, color, 2)

        cv2.addWeighted(overlay, 0.4, annotated, 0.6, 0, annotated)

        for i, mask in enumerate(masks):
            cls_id = int(boxes.cls[i])
            conf = float(boxes.conf[i])
            label = self._class_names.get(cls_id, f"cls{cls_id}")
            color = self._colors.get(cls_id, (255, 255, 255))
            xyxy = boxes.xyxy[i].cpu().numpy()
            x1, y1, x2, y2 = map(int, xyxy)

            # 中心点
            ys, xs = np.where(mask)
            cx, cy = (int(xs.mean()), int(ys.mean())) if len(xs) > 0 else ((x1 + x2) // 2, (y1 + y2) // 2)
            cv2.circle(annotated, (cx, cy), 4, (255, 255, 255), -1)
            cv2.circle(annotated, (cx, cy), 6, color, 2)

            # 标签
            text_parts = [f"{label} {conf:.2f}"]
            if depth_img is not None and 0 <= cy < depth_img.shape[0] and 0 <= cx < depth_img.shape[1]:
                d_mm = depth_img[cy, cx]
                if d_mm > 0:
                    text_parts.append(f"| {d_mm / 1000:.2f}m")
            text = " ".join(text_parts)

            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
            cv2.rectangle(annotated, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
            cv2.putText(
                annotated, text, (x1 + 2, y1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2,
            )

        # FPS + 总数
        total = len(boxes)
        cv2.putText(
            annotated, f"Instances: {total}",
            (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2,
        )

        return annotated

    # ────────────────────────────────────────────────
    #  发布检测结果 JSON
    # ────────────────────────────────────────────────
    def _publish_detections(self, results, depth_img=None) -> None:
        r = results[0]
        stamp = self.get_clock().now().to_msg()

        detections = []
        if r.boxes is not None:
            boxes = r.boxes
            masks = r.masks

            for i in range(len(boxes)):
                cls_id = int(boxes.cls[i])
                conf = float(boxes.conf[i])
                xyxy = boxes.xyxy[i].cpu().numpy()
                x1, y1, x2, y2 = map(int, xyxy)

                # mask 中心
                if masks is not None:
                    m = masks.data[i].cpu().numpy().astype(bool)
                    ys, xs = np.where(m)
                    cx, cy = (int(xs.mean()), int(ys.mean())) if len(xs) > 0 else ((x1 + x2) // 2, (y1 + y2) // 2)
                    area_px = int(m.sum())
                else:
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    area_px = 0

                det = {
                    "class_id": cls_id,
                    "class_name": self._class_names.get(cls_id, f"cls{cls_id}"),
                    "confidence": round(conf, 4),
                    "bbox": [x1, y1, x2, y2],
                    "center": {"x": cx, "y": cy},
                    "mask_area_px": area_px,
                }

                if depth_img is not None and 0 <= cy < depth_img.shape[0] and 0 <= cx < depth_img.shape[1]:
                    d_mm = int(depth_img[cy, cx])
                    if d_mm > 0:
                        det["distance_m"] = round(d_mm / 1000, 3)

                detections.append(det)

        payload = {
            "header": {
                "stamp_sec": stamp.sec,
                "stamp_nanosec": stamp.nanosec,
                "frame_id": self._frame_id,
            },
            "num_detections": len(detections),
            "detections": detections,
        }

        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self._detections_pub.publish(msg)

        # 计数
        count_msg = Int32()
        count_msg.data = len(detections)
        self._count_pub.publish(count_msg)

    # ────────────────────────────────────────────────
    #  发布标注图像
    # ────────────────────────────────────────────────
    def _publish_image(self, bgr_image: np.ndarray) -> None:
        import cv2
        rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)

        msg = Image()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self._frame_id
        msg.height = rgb.shape[0]
        msg.width = rgb.shape[1]
        msg.encoding = "rgb8"
        msg.is_bigendian = False
        msg.step = rgb.shape[1] * 3
        msg.data = rgb.tobytes()
        self._image_pub.publish(msg)

    # ────────────────────────────────────────────────
    #  清理
    # ────────────────────────────────────────────────
    def destroy_node(self) -> bool:
        self.get_logger().info("Shutting down...")
        if self._cam:
            try:
                self._cam.stop()
            except Exception:
                pass
        if self._cap:
            self._cap.release()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = YoloDetectNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
