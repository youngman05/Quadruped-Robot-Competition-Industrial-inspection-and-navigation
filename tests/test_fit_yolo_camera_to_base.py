from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fit_yolo_camera_to_base", ROOT / "scripts" / "fit_yolo_camera_to_base.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FitCameraToBaseTest(unittest.TestCase):
    def test_recovers_rigid_transform(self) -> None:
        angle = np.deg2rad(30.0)
        rotation = np.array([[np.cos(angle), 0.0, np.sin(angle)], [0.0, 1.0, 0.0],
                             [-np.sin(angle), 0.0, np.cos(angle)]])
        translation = np.array([0.08, -0.02, 0.493])
        camera = np.array([[0.2, -0.3, 0.8], [0.5, 0.4, 1.1], [0.9, -0.2, 0.7], [0.6, 0.1, 1.4]])
        fitted_rotation, fitted_translation = MODULE.fit(camera, camera @ rotation.T + translation)
        np.testing.assert_allclose(fitted_rotation, rotation, atol=1e-12)
        np.testing.assert_allclose(fitted_translation, translation, atol=1e-12)


if __name__ == "__main__":
    unittest.main()
