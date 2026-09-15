"""Capture ordering, bounded live capture, and deterministic demo checks."""

from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from analytics import DirectionalCounter
from sources import SyntheticSource, VideoSource, _validate_source


class ControlledCapture:
    """A camera driver whose read is deliberately blocked until the test feeds it."""

    def __init__(self):
        self.frames = queue.Queue()
        self.read_entered = threading.Event()
        self.released = threading.Event()
        self.reading = False
        self.concurrent_release = False

    def isOpened(self):
        return True

    def get(self, prop):
        return 30.0

    def set(self, *args):
        return True

    def read(self):
        self.reading = True
        self.read_entered.set()
        try:
            frame = self.frames.get(timeout=3)
            return frame is not None, frame
        finally:
            self.reading = False

    def release(self):
        self.concurrent_release = self.reading
        self.released.set()


class VideoSourceTests(unittest.TestCase):
    def test_local_video_keeps_every_frame_and_deterministic_timestamp(self):
        with tempfile.TemporaryDirectory(prefix="visioneye-source-") as folder:
            path = Path(folder) / "frames.avi"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 12.5, (64, 48))
            self.assertTrue(writer.isOpened(), "MJPG test fixture codec could not open")
            try:
                for index in range(12):
                    writer.write(np.full((48, 64, 3), index * 15, np.uint8))
            finally:
                writer.release()
            with VideoSource(str(path)) as source:
                self.assertFalse(source.live)
                self.assertAlmostEqual(source.fps, 12.5)
                for index in range(12):
                    ok, frame, source_index, timestamp = source.read()
                    self.assertTrue(ok)
                    self.assertEqual(source_index, index)
                    self.assertAlmostEqual(timestamp, index / 12.5)
                    self.assertLess(abs(float(frame.mean()) - index * 15), 3)
                self.assertFalse(source.read()[0])

    def test_live_consumer_gets_latest_frame_with_source_index(self):
        capture = ControlledCapture()
        with patch("sources._open_capture", return_value=capture):
            source = VideoSource(0)
        try:
            for index in range(5):
                capture.frames.put(np.full((2, 2, 3), index, np.uint8))
                with source._condition:
                    self.assertTrue(source._condition.wait_for(lambda: source._next_index >= index + 1, 1))
            ok, frame, source_index, timestamp = source.read()
            self.assertTrue(ok)
            self.assertEqual(source_index, 4)
            self.assertEqual(int(frame[0, 0, 0]), 4)
            self.assertGreaterEqual(timestamp, 0)
            capture.frames.put(None)
            with self.assertRaisesRegex(RuntimeError, "stopped producing frames"):
                source.read()
        finally:
            capture.frames.put(None)
            source.close()
        self.assertFalse(capture.concurrent_release)

    def test_close_is_bounded_and_never_releases_during_driver_read(self):
        capture = ControlledCapture()
        with patch("sources._open_capture", return_value=capture):
            source = VideoSource(0)
        self.assertTrue(capture.read_entered.wait(1))
        try:
            started = time.monotonic()
            source.close()
            self.assertLess(time.monotonic() - started, 1.7)
            self.assertFalse(capture.released.is_set())
            self.assertFalse(source.read()[0])
        finally:
            capture.frames.put(None)
            source._worker.join(timeout=1)
        self.assertTrue(capture.released.is_set())
        self.assertFalse(capture.concurrent_release)

    def test_startup_exceptions_do_not_expose_url_credentials(self):
        with patch("sources._open_capture", side_effect=RuntimeError("rtsp://user:secret@example.test/live")):
            with self.assertRaises(RuntimeError) as caught:
                VideoSource("rtsp://user:secret@example.test/live")
        self.assertEqual(str(caught.exception), "Could not open video source.")
        self.assertIsNone(caught.exception.__cause__)

    def test_source_validation_rejects_unsupported_protocols(self):
        for value in (-1, True, "", "ftp://example.test/movie", "file:///tmp/movie", "rtsp://"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _validate_source(value)
        self.assertEqual(_validate_source("0"), (0, True))
        self.assertEqual(_validate_source(r"C:\videos\clip.mp4"), (r"C:\videos\clip.mp4", False))

    def test_demo_finishes_with_three_entries_and_one_exit(self):
        counter = DirectionalCounter(((96, 297), (864, 297)), in_side=1, hysteresis=8)
        events = []
        with SyntheticSource() as source:
            for index in range(360):
                ok, frame, source_index, timestamp = source.read()
                self.assertTrue(ok)
                self.assertEqual(frame.shape, (540, 960, 3))
                self.assertEqual(source_index, index)
                self.assertEqual(timestamp, index / 30)
                points = {
                    item["track_id"]: ((item["xyxy"][0] + item["xyxy"][2]) / 2, item["xyxy"][3])
                    for item in source.detections
                }
                events.extend(counter.update(points, source_index, timestamp))
            self.assertFalse(source.read()[0])
        self.assertEqual([event["direction"] for event in events], ["IN", "IN", "IN", "OUT"])
        self.assertEqual(counter.occupancy, 2)
        self.assertFalse(counter.underflow)


if __name__ == "__main__":
    unittest.main()
