"""
RTSP 前置相机拍照工具 — 按空格保存，按 Q 退出。

图片保存到 InstanceSegmentation/gauge_dataset/

用法 (Jetson 终端):
    cd ~/quadruped-robot-competition
    LD_PRELOAD=/lib/aarch64-linux-gnu/libgomp.so.1 python3 InstanceSegmentation/scripts/capture_gauge.py

按键:
    空格   — 拍照保存
    Q / Esc — 退出
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import cv2

# 脚本所在目录的绝对路径
_SCRIPT_DIR = Path(__file__).resolve().parent
_DATASET_DIR = (_SCRIPT_DIR.parent / "gauge_dataset").resolve()
_DATASET_DIR.mkdir(parents=True, exist_ok=True)

# ── 检测是否在 Jetson 上 ──
_ON_JETSON = os.path.exists("/lib/aarch64-linux-gnu/libgomp.so.1")

if _ON_JETSON:
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    import numpy as np

    Gst.init(None)
    PIPELINE = (
        "rtspsrc location=rtsp://192.168.1.120:8554/test ! "
        "rtph264depay ! h264parse ! avdec_h264 ! "
        "videoconvert ! video/x-raw,format=BGR ! "
        "appsink name=sink sync=false max-buffers=1 drop=true"
    )
    _pipeline = Gst.parse_launch(PIPELINE)
    _sink = _pipeline.get_by_name("sink")
    _pipeline.set_state(Gst.State.PLAYING)

    # probe
    _sample = _sink.emit("pull-sample")
    _caps = _sample.get_caps()
    _struct = _caps.get_structure(0)
    _W, _H = _struct.get_value("width"), _struct.get_value("height")

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
    assert cap.isOpened(), "No camera found"
    _W, _H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    def read_frame():
        ret, f = cap.read()
        if not ret:
            raise RuntimeError("Camera read failed")
        return f

    def close_camera():
        cap.release()


def main():
    print(f"相机: {_W}x{_H}")
    print(f"保存到: {_DATASET_DIR}")
    print()
    print("  [ 空格 ] = 拍照")
    print("  [ Q ]    = 退出")
    print("-" * 40)

    count = 0
    try:
        while True:
            frame = read_frame()

            # 预览 640 宽
            preview = cv2.resize(frame, (640, int(640 * _H / _W)))
            cv2.putText(preview, f"saved: {count}  |  SPACE = shoot  |  Q = quit",
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)
            cv2.imshow("Capture Gauge", preview)

            key = cv2.waitKey(30) & 0xFF

            if key == ord(" "):
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                fname = _DATASET_DIR / f"gauge_{ts}_{count:03d}.jpg"
                cv2.imwrite(str(fname), frame)
                count += 1
                print(f"  >>> [{count}] {fname.name}  ({frame.shape[1]}x{frame.shape[0]})")

            elif key in (ord("q"), ord("Q"), 27):
                break

    except KeyboardInterrupt:
        print("\nCtrl+C")
    finally:
        close_camera()
        cv2.destroyAllWindows()
        print(f"\n共 {count} 张 → {_DATASET_DIR}")


if __name__ == "__main__":
    main()
