"""Load the accepted map-to-odom start transform."""

import json
import math
from pathlib import Path
from typing import Tuple


def load_start_prior(path: Path) -> Tuple[float, float, float, str]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("frame_id") != "map":
        raise ValueError("start prior must use frame_id=map")

    values = tuple(float(document[key]) for key in ("x", "y", "yaw"))
    if not all(math.isfinite(value) for value in values):
        raise ValueError("start prior transform values must be finite")

    source = str(document.get("source", ""))
    return values[0], values[1], values[2], source
