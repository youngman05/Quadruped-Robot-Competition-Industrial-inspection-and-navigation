import tempfile
import unittest
import math
from pathlib import Path

from nodes.navigation.depth_contract import (
    FRAME_DATA_FILE,
    FRAME_METADATA_FILE,
    DepthContractError,
    DepthMode,
    build_frame_metadata,
    new_control_request,
    monotonic_age_sec,
    read_frame_snapshot,
    validate_control_request,
    write_atomic_bytes,
    write_atomic_json,
)


CAMERA_INFO = {
    "width": 2,
    "height": 2,
    "distortion_model": "plumb_bob",
    "d": [0.0] * 5,
    "k": [1.0, 0.0, 0.5, 0.0, 1.0, 0.5, 0.0, 0.0, 1.0],
    "r": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
    "p": [1.0, 0.0, 0.5, 0.0, 0.0, 1.0, 0.5, 0.0, 0.0, 0.0, 1.0, 0.0],
}


class DepthContractTests(unittest.TestCase):
    def test_control_request_round_trip(self):
        request = new_control_request(
            DepthMode.AVOIDANCE,
            request_id="req-1",
            created_monotonic_ns=123,
        )
        self.assertEqual(validate_control_request(request), request)

    def test_frame_snapshot_checks_crc(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            raw = b"\x01\x00\x02\x00\x03\x00\x04\x00"
            metadata = build_frame_metadata(
                raw=raw,
                stream_id="stream-a",
                sequence=4,
                source_stamp_ns=99,
                monotonic_stamp_ns=100,
                width=2,
                height=2,
                step=4,
                frame_id="camera_depth_optical_frame",
                depth_scale=0.001,
                camera_info=CAMERA_INFO,
                mode=DepthMode.AVOIDANCE,
            )
            write_atomic_bytes(directory / FRAME_DATA_FILE, raw)
            write_atomic_json(directory / FRAME_METADATA_FILE, metadata.to_dict())
            actual_metadata, actual_raw = read_frame_snapshot(directory)
            self.assertEqual(actual_metadata.sequence, 4)
            self.assertEqual(actual_metadata.stream_id, "stream-a")
            self.assertEqual(actual_raw, raw)

            write_atomic_bytes(directory / FRAME_DATA_FILE, b"\x00" * len(raw))
            with self.assertRaises(DepthContractError):
                read_frame_snapshot(directory)

    def test_disabled_mode_cannot_carry_a_frame(self):
        with self.assertRaises(DepthContractError):
            build_frame_metadata(
                raw=b"\x00\x00",
                stream_id="stream-a",
                sequence=1,
                source_stamp_ns=1,
                width=1,
                height=1,
                step=2,
                frame_id="camera_depth_optical_frame",
                depth_scale=0.001,
                camera_info=dict(CAMERA_INFO, width=1, height=1),
                mode=DepthMode.DISABLED,
            )

    def test_rejects_nonfinite_depth_scale_and_future_monotonic_stamp(self):
        with self.assertRaises(DepthContractError):
            build_frame_metadata(
                raw=b"\x01\x00",
                stream_id="stream-a",
                sequence=1,
                source_stamp_ns=1,
                monotonic_stamp_ns=1,
                width=1,
                height=1,
                step=2,
                frame_id="camera_depth_optical_frame",
                depth_scale=math.nan,
                camera_info=dict(CAMERA_INFO, width=1, height=1),
                mode=DepthMode.AVOIDANCE,
            )
        with self.assertRaises(DepthContractError):
            monotonic_age_sec(101, now_ns=100, label="test stamp")


if __name__ == "__main__":
    unittest.main()
