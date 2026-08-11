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

from whz.yolo_detector import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_IMAGE_SIZE,
    DEFAULT_LETTER_CONFIDENCE_THRESHOLD,
    DEFAULT_LETTER_CROP_IMAGE_SIZE,
    GaugeDetection,
    LetterDetection,
    YOLODetector,
)


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


def fake_box(class_id, confidence, bbox):
    return SimpleNamespace(
        cls=np.array([class_id], dtype=np.float32),
        conf=np.array([confidence], dtype=np.float32),
        xyxy=np.array([bbox], dtype=np.float32),
    )


class GaugeAnchoredModel(FakeModel):
    def predict(self, **kwargs):
        self.predict_calls += 1
        self.last_kwargs = kwargs
        image = kwargs["source"]
        if image.shape == (720, 1280, 3):
            return [
                SimpleNamespace(
                    boxes=[
                        fake_box(1, 0.29, (628, 340, 652, 368)),
                        fake_box(4, 0.93, (600, 400, 680, 480)),
                    ]
                )
            ]
        if image.shape == (148, 200, 3):
            return [SimpleNamespace(boxes=[fake_box(3, 0.40, (88, 80, 112, 108))])]
        return [SimpleNamespace(boxes=[])]


class GaugeAnchoredMissModel(FakeModel):
    def predict(self, **kwargs):
        self.predict_calls += 1
        self.last_kwargs = kwargs
        image = kwargs["source"]
        if image.shape == (720, 1280, 3):
            return [
                SimpleNamespace(
                    boxes=[
                        fake_box(0, 0.55, (844, 428, 880, 472)),
                        fake_box(5, 0.86, (819, 515, 925, 650)),
                    ]
                )
            ]
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
        self.assertEqual(model.last_kwargs["imgsz"], DEFAULT_IMAGE_SIZE)
        self.assertEqual(model.last_kwargs["conf"], DEFAULT_CONFIDENCE_THRESHOLD)
        self.assertEqual(DEFAULT_IMAGE_SIZE, 960)
        self.assertEqual(DEFAULT_CONFIDENCE_THRESHOLD, 0.25)
        self.assertEqual(DEFAULT_LETTER_CROP_IMAGE_SIZE, 320)
        self.assertEqual(DEFAULT_LETTER_CONFIDENCE_THRESHOLD, 0.15)
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "letter_not_detected")

    def test_gauge_anchored_crop_corrects_full_frame_letter_confusion(self):
        model = GaugeAnchoredModel()

        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.pt"
            model_path.write_bytes(b"test")
            detector = YOLODetector(
                model_path=model_path,
                device="cpu",
                model_factory=lambda _: model,
            )
            result = detector.detect(np.zeros((720, 1280, 3), dtype=np.uint8))

        self.assertTrue(result.ok)
        self.assertEqual(result.pair.letter.letter, "D")
        self.assertEqual(result.pair.letter.bbox, (628, 340, 652, 368))
        self.assertEqual(result.pair.gauge.color, "green")
        self.assertEqual(model.predict_calls, 3)
        self.assertEqual(model.last_kwargs["imgsz"], 320)
        self.assertEqual(model.last_kwargs["conf"], 0.15)

    def test_full_frame_letter_is_fallback_when_gauge_crop_misses(self):
        model = GaugeAnchoredMissModel()

        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.pt"
            model_path.write_bytes(b"test")
            detector = YOLODetector(
                model_path=model_path,
                device="cpu",
                model_factory=lambda _: model,
            )
            result = detector.detect(np.zeros((720, 1280, 3), dtype=np.uint8))

        self.assertTrue(result.ok)
        self.assertEqual(result.pair.letter.letter, "A")
        self.assertAlmostEqual(result.pair.letter.confidence, 0.55, places=5)
        self.assertEqual(result.pair.gauge.color, "red")
        self.assertEqual(model.predict_calls, 3)

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
