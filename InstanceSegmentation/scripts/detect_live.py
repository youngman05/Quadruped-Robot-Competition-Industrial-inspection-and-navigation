"""
RTSP 前置相机 + YOLO 实时检测.

用法 (Jetson):
    cd ~/quadruped-robot-competition
    LD_PRELOAD=/lib/aarch64-linux-gnu/libgomp.so.1 \
      python3 InstanceSegmentation/scripts/detect_live.py

按键: Q 退出
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import cv2

# ── Jetson torchvision NMS bug workaround ──
import torch
import torchvision

def _py_nms(boxes, scores, iou_threshold):
    """Pure-Python NMS for Jetson (torchvision C++ ops broken)."""
    if boxes.numel() == 0:
        return torch.empty((0,), dtype=torch.int64, device=boxes.device)
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    _, order = scores.sort(descending=True)
    keep = []
    while order.numel() > 0:
        i = order[0].item()
        keep.append(i)
        if order.numel() == 1:
            break
        xx1 = torch.max(x1[i], x1[order[1:]])
        yy1 = torch.max(y1[i], y1[order[1:]])
        xx2 = torch.min(x2[i], x2[order[1:]])
        yy2 = torch.min(y2[i], y2[order[1:]])
        w = (xx2 - xx1).clamp(min=0)
        h = (yy2 - yy1).clamp(min=0)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[(iou <= iou_threshold).nonzero(as_tuple=False).squeeze(1) + 1]
    return torch.tensor(keep, dtype=torch.int64, device=boxes.device)

torchvision.ops.nms = _py_nms

# ── 路径 ──
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJ_ROOT = _SCRIPT_DIR.parent
_MODEL_PATH = _PROJ_ROOT / "projects" / "gauge" / "model" / "best.pt"
_CAPTURE_DIR = _PROJ_ROOT / "debug_captures"
_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

CLASS_COLORS = {
    "A": (0, 0, 255), "B": (0, 255, 0), "C": (255, 0, 0), "D": (255, 255, 0),
    "green": (0, 200, 0), "red": (0, 0, 200), "yellow": (0, 200, 200),
}

# ── 相机 ──
_ON_JETSON = os.path.exists("/lib/aarch64-linux-gnu/libgomp.so.1")

if _ON_JETSON:
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    import numpy as np

    Gst.init(None)
    _pipeline = Gst.parse_launch(
        "rtspsrc location=rtsp://192.168.1.120:8554/test ! "
        "rtph264depay ! h264parse ! avdec_h264 ! "
        "videoconvert ! video/x-raw,format=BGR ! "
        "appsink name=sink sync=false max-buffers=1 drop=true"
    )
    _sink = _pipeline.get_by_name("sink")
    _pipeline.set_state(Gst.State.PLAYING)
    s = _sink.emit("pull-sample")
    _caps = s.get_caps().get_structure(0)
    _W, _H = _caps.get_value("width"), _caps.get_value("height")

    def read_frame():
        s = _sink.emit("pull-sample")
        b = s.get_buffer()
        ok, info = b.map(Gst.MapFlags.READ)
        f = np.frombuffer(info.data, dtype=np.uint8).reshape((_H, _W, 3)).copy()
        b.unmap(info)
        return f

    def close_camera():
        _pipeline.set_state(Gst.State.NULL)

else:
    cap = cv2.VideoCapture(0)
    _W, _H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    def read_frame():
        ret, f = cap.read()
        if not ret: raise RuntimeError("Camera failed")
        return f

    def close_camera():
        cap.release()

# ── 模型 ──
from ultralytics import YOLO

model = YOLO(str(_MODEL_PATH))
CLASS_NAMES = list(model.names.values())


def main():
    print(f"[INFO] model: {_MODEL_PATH}")
    print(f"[INFO] camera: {_W}x{_H}")
    print(f"[INFO] classes: {CLASS_NAMES}")
    print("[INFO] warming up...")

    _ = model(read_frame(), verbose=False, imgsz=320)
    print(f"[INFO] ready. SPACE=capture  Q=quit")
    print(f"[INFO] captures -> {_CAPTURE_DIR}\n")

    capture_count = 0
    try:
        while True:
            frame = read_frame()
            results = model(frame, verbose=False, imgsz=320, iou=0.5, conf=0.3)[0]

            for box in results.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                name = CLASS_NAMES[cls_id]
                color = CLASS_COLORS.get(name, (255, 255, 255))

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                label = f"{name} {conf:.2f}"
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
                cv2.rectangle(frame, (x1, y1 - th - 4), (x1 + tw, y1), color, -1)
                cv2.putText(frame, label, (x1, y1 - 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            preview = cv2.resize(frame, (960, 540))
            n_obj = len(results.boxes)
            cv2.putText(preview, f"Q=quit | SPACE=save | saved:{capture_count} | objs:{n_obj}",
                        (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
            cv2.imshow("Gauge Detection", preview)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord(" "):  # spacebar
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                fname = _CAPTURE_DIR / f"debug_{ts}_{capture_count:03d}.jpg"
                cv2.imwrite(str(fname), frame)
                capture_count += 1
                print(f"  [CAPTURE {capture_count}] {fname.name}")

    except KeyboardInterrupt:
        pass
    finally:
        close_camera()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
