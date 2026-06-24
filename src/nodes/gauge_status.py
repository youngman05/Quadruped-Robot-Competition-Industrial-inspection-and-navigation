#!/usr/bin/env python3
"""ROS2 node: D455 OpenCV gauge recognition → /gauge/status, /gauge/detected.

Thin wrapper — delegates to scripts/gauge_status_node.py.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

if __name__ == "__main__":
    from gauge_status_node import main
    main()
