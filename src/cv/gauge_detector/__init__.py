"""YOLO-based cabinet gauge + letter detector.

Main entry point:
    from cv.gauge_detector import GaugeDetector

    det = GaugeDetector()
    result = det.detect(image)   # DetectionResult
    print(result.best_letter)    # LetterDetection(letter='C', confidence=0.95)

Live detection:
    python3 -m cv.gauge_detector.live_detect         # RTSP front camera
    python3 -m cv.gauge_detector.live_detect --d455  # D455 via Docker JPEG

Legacy API:
    from cv.gauge_detector import detect_gauge
    result = detect_gauge(image)
"""

from .gauge_detector import (
    DetectionResult,
    GaugeDetector,
    GaugeDetection,
    LetterDetection,
    detect_gauge,
    draw_detections,
)

__all__ = [
    "DetectionResult",
    "GaugeDetector",
    "GaugeDetection",
    "LetterDetection",
    "detect_gauge",
    "draw_detections",
]
