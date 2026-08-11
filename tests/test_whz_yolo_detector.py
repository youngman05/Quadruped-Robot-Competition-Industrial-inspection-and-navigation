import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
WHZ_ROOT = REPO_ROOT / "whz"
if str(WHZ_ROOT) not in sys.path:
    sys.path.insert(0, str(WHZ_ROOT))

from whz.yolo_detector import GaugeDetection, LetterDetection, YOLODetector


def pairing_detector():
    detector = object.__new__(YOLODetector)
    detector.max_horizontal_offset_ratio = 0.75
    detector.max_vertical_gap_ratio = 2.5
    detector.min_pair_score_margin = 0.12
    return detector


class FakeModel:
    names = {0: "A", 1: "B", 2: "C", 3: "D", 4: "green", 5: "red", 6: "yellow"}

    def __init__(self):
        self.predict_calls = 0

    def predict(self, **kwargs):
        self.predict_calls += 1
        self.last_kwargs = kwargs
        return [SimpleNamespace(boxes=[])]


class YOLODetectorTests(unittest.TestCase):
    def test_model_is_constructed_and_warmed_once(self):
        factory_calls = []
        model = FakeModel()

        def factory(path):
            factory_calls.append(path)
            return model

        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.pt"
            model_path.write_bytes(b"test")
            detector = YOLODetector(
                model_path=model_path,
                device="cpu",
                model_factory=factory,
            )
            detector._warmup()
            result = detector.detect(np.zeros((8, 8, 3), dtype=np.uint8))

        self.assertEqual(len(factory_calls), 1)
        self.assertTrue(detector.warmup_done)
        self.assertEqual(model.predict_calls, 2)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "letter_not_detected")

    def test_pairing_uses_geometry_instead_of_global_gauge_confidence(self):
        detector = pairing_detector()
        letter = LetterDetection("A", 0.95, (80, 10, 120, 50))
        aligned_gauge = GaugeDetection("yellow", 0.70, (50, 100, 150, 200))
        wrong_gauge = GaugeDetection("red", 0.99, (450, 100, 550, 200))

        pair, error = detector._select_pair([letter], [wrong_gauge, aligned_gauge])

        self.assertIsNone(error)
        self.assertEqual(pair.letter.letter, "A")
        self.assertEqual(pair.gauge.color, "yellow")
        self.assertEqual(pair.letter.confidence, 0.95)
        self.assertFalse(hasattr(pair.letter, "label"))
        self.assertFalse(hasattr(pair.letter, "conf"))

    def test_two_equally_good_panels_are_rejected_as_ambiguous(self):
        detector = pairing_detector()
        letters = [
            LetterDetection("A", 0.90, (80, 10, 120, 50)),
            LetterDetection("B", 0.90, (480, 10, 520, 50)),
        ]
        gauges = [
            GaugeDetection("green", 0.90, (50, 100, 150, 200)),
            GaugeDetection("red", 0.90, (450, 100, 550, 200)),
        ]

        pair, error = detector._select_pair(letters, gauges)

        self.assertIsNone(pair)
        self.assertEqual(error, "ambiguous_spatial_pair")

    def test_letter_below_gauge_is_rejected(self):
        detector = pairing_detector()
        letter = LetterDetection("C", 0.90, (80, 180, 120, 220))
        gauge = GaugeDetection("green", 0.90, (50, 50, 150, 150))

        pair, error = detector._select_pair([letter], [gauge])

        self.assertIsNone(pair)
        self.assertEqual(error, "no_spatial_pair")


if __name__ == "__main__":
    unittest.main()
