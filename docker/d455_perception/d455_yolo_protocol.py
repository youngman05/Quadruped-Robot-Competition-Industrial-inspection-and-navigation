"""Locked producer identity for the competition YOLO packet schema."""

MODEL_ID = "gauge-ad-3ed76de7-v1"
CLASS_SCHEMA = "competition-ad-yellow-red-green-v1"
MODEL_SHA256 = "3ed76de727a87be8d64cc3b259bf2b0ec39daaaa3fac1f3f97af249824abc648"
MODEL_CLASS_MAP = {
    0: "A",
    1: "B",
    2: "C",
    3: "D",
    4: "green",
    5: "red",
    6: "yellow",
}
MODEL_CLASS_NAMES = frozenset(MODEL_CLASS_MAP.values())
