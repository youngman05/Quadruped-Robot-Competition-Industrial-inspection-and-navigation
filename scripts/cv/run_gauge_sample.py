#!/usr/bin/env python3
"""Run the OpenCV gauge detector on the bundled sample image."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
GAUGE_DIR = ROOT / "src" / "cv" / "gauge_detector"
sys.path.insert(0, str(GAUGE_DIR))

from gauge_detector import detect_gauge, print_result  # noqa: E402


def main() -> None:
    image_path = GAUGE_DIR / "sample_gauge.jpg"
    debug_path = GAUGE_DIR / "sample_gauge_debug.jpg"
    result = detect_gauge(str(image_path), debug=True, debug_out=str(debug_path))
    if result is None:
        raise RuntimeError(f"Gauge detection failed: {image_path}")

    print_result("sample_gauge", result)
    print(f"debug image: {debug_path}")


if __name__ == "__main__":
    main()

