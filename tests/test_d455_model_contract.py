"""Verify that the unchanged competition model has the expected contract."""

from __future__ import annotations

import unittest
from pathlib import Path


class ModelContractTest(unittest.TestCase):
    def test_model_is_three_class_segmentation_model(self) -> None:
        from ultralytics import YOLO

        root = Path(__file__).resolve().parents[1]
        model_path = (
            root
            / "src"
            / "cv"
            / "depth_detector"
            / "projects"
            / "combined"
            / "model"
            / "best.pt"
        )
        self.assertTrue(model_path.is_file())

        model = YOLO(str(model_path))
        names = {int(key): value for key, value in model.names.items()}
        self.assertEqual(names, {0: "red", 1: "green", 2: "obstacle"})
        self.assertEqual(model.task, "segment")


if __name__ == "__main__":
    unittest.main()

