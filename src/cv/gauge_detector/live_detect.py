"""
Live gauge + letter detection via RTSP front camera.

Usage (Jetson):
    LD_PRELOAD=/lib/aarch64-linux-gnu/libgomp.so.1 python3 live_detect.py

Keys:
    Q / Esc — quit
    Space   — save current frame to debug_captures/
"""

import os
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

# NMS workaround (Jetson torchvision)
import torch, torchvision
def _py_nms(boxes, scores, iou_threshold):
    if boxes.numel() == 0:
        return torch.empty((0,), dtype=torch.int64, device=boxes.device)
    x1, y1, x2, y2 = boxes[:,0], boxes[:,1], boxes[:,2], boxes[:,3]
    areas = (x2-x1)*(y2-y1); _, order = scores.sort(descending=True)
    keep = []
    while order.numel() > 0:
        i = order[0].item(); keep.append(i)
        if order.numel() == 1: break
        xx1 = torch.max(x1[i], x1[order[1:]]); yy1 = torch.max(y1[i], y1[order[1:]])
        xx2 = torch.min(x2[i], x2[order[1:]]); yy2 = torch.min(y2[i], y2[order[1:]])
        w = (xx2-xx1).clamp(min=0); h = (yy2-yy1).clamp(min=0)
        inter = w*h; iou = inter/(areas[i]+areas[order[1:]]-inter)
        order = order[(iou<=iou_threshold).nonzero(as_tuple=False).squeeze(1)+1]
    return torch.tensor(keep, dtype=torch.int64, device=boxes.device)

torchvision.ops.nms = _py_nms

# ── Paths ──
_PROJ_ROOT = Path(__file__).resolve().parents[3]  # quadruped-robot-competition/
_MODEL_PATH = _PROJ_ROOT / "InstanceSegmentation" / "projects" / "gauge" / "model" / "best.pt"
_CAPTURE_DIR = _PROJ_ROOT / "InstanceSegmentation" / "debug_captures"

_CLASS_COLORS = {
    "A": (0, 0, 255), "B": (0, 255, 0), "C": (255, 0, 0), "D": (255, 255, 0),
    "green": (0, 200, 0), "red": (0, 0, 200), "yellow": (0, 200, 200),
}


# ── Camera ──
def _init_rtsp():
    import gi; gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    p = Gst.parse_launch(
        "rtspsrc location=rtsp://192.168.1.120:8554/test ! "
        "rtph264depay ! h264parse ! avdec_h264 ! "
        "videoconvert ! video/x-raw,format=BGR ! "
        "appsink name=sink sync=false max-buffers=1 drop=true"
    )
    s = p.get_by_name("sink"); p.set_state(Gst.State.PLAYING)
    caps = s.emit("pull-sample").get_caps().get_structure(0)
    W, H = caps.get_value("width"), caps.get_value("height")

    def read():
        buf = s.emit("pull-sample").get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        f = np.frombuffer(info.data, dtype=np.uint8).reshape((H, W, 3)).copy()
        buf.unmap(info); return f

    def close():
        p.set_state(Gst.State.NULL)

    return read, close, W, H


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--model", type=str, default=str(_MODEL_PATH))
    p.add_argument("--imgsz", type=int, default=320)
    p.add_argument("--conf", type=float, default=0.3)
    p.add_argument("--iou", type=float, default=0.5)
    args = p.parse_args()

    _CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

    read_frame, close_cam, W, H = _init_rtsp()
    print(f"[camera] RTSP front wide-angle, {W}x{H}")

    # Model
    from ultralytics import YOLO
    model = YOLO(args.model)
    names = list(model.names.values())
    print(f"[model] {args.model}")
    print(f"[model] classes: {names}")

    # Warmup
    print("[info] warming up...")
    _ = model(read_frame(), verbose=False, imgsz=args.imgsz)
    print(f"[info] ready. SPACE=save  Q=quit")
    print(f"[info] captures -> {_CAPTURE_DIR}\n")

    count = 0
    try:
        while True:
            frame = read_frame()
            results = model(frame, verbose=False, imgsz=args.imgsz,
                            conf=args.conf, iou=args.iou)[0]

            for box in results.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cls_id = int(box.cls[0]); conf = float(box.conf[0])
                name = names[cls_id]; color = _CLASS_COLORS.get(name, (255,255,255))
                cv2.rectangle(frame, (x1,y1), (x2,y2), color, 2)
                label = f"{name} {conf:.2f}"
                (tw,th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
                cv2.rectangle(frame, (x1, y1-th-4), (x1+tw, y1), color, -1)
                cv2.putText(frame, label, (x1, y1-2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)

            preview = cv2.resize(frame, (960, 540))
            n = len(results.boxes)
            cv2.putText(preview, f"Q=quit | SPACE=save | saved:{count} | objs:{n}",
                        (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,255,0), 2)
            cv2.imshow("Gauge Detection", preview)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                break
            elif key == ord(" "):
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                fname = _CAPTURE_DIR / f"debug_{ts}_{count:03d}.jpg"
                cv2.imwrite(str(fname), frame)
                count += 1; print(f"  [SAVE {count}] {fname.name}")

    except KeyboardInterrupt:
        pass
    finally:
        close_cam(); cv2.destroyAllWindows()
        print(f"\nDone. {count} captures in {_CAPTURE_DIR}")


if __name__ == "__main__":
    main()
