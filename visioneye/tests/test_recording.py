"""Timestamp-resampling tests without a platform-dependent video codec."""

import unittest
from unittest.mock import patch

import numpy as np

from recording import TimedVideoWriter


class FakeVideoWriter:
    def __init__(self, opened=True):
        self.opened = opened
        self.frames = []
        self.release_count = 0

    def isOpened(self):
        return self.opened

    def write(self, frame):
        self.frames.append(frame.copy())

    def release(self):
        self.release_count += 1


class TimedVideoWriterTests(unittest.TestCase):
    def setUp(self):
        self.codec = FakeVideoWriter()
        patcher = patch("recording.cv2.VideoWriter", return_value=self.codec)
        self.constructor = patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def frame(label):
        return np.full((4, 6, 3), label, dtype=np.uint8)

    def labels(self):
        return [int(frame[0, 0, 0]) for frame in self.codec.frames]

    def test_missing_frame_uses_previous_image_until_new_timestamp(self):
        writer = TimedVideoWriter("test.mp4", 10, (6, 4))
        writer.write(self.frame(10), 0)
        writer.write(self.frame(20), .1)
        writer.write(self.frame(30), .3)
        self.assertEqual(self.labels(), [10, 20, 20])
        writer.close()
        self.assertEqual(self.labels(), [10, 20, 20, 30])
        self.assertEqual(writer.origin, 0)
        self.assertEqual(writer.frames_written, 4)

    def test_constant_fps_has_no_duplicate_or_dropped_frames(self):
        for fps in (10, 29.97, 30, 59.94):
            with self.subTest(fps=fps):
                self.codec.frames.clear()
                writer = TimedVideoWriter("test.mp4", fps, (6, 4))
                for index in range(120):
                    writer.write(self.frame(index), 125.5 + index / fps)
                writer.close()
                self.assertEqual(self.labels(), list(range(120)))
                self.assertEqual(writer.frames_written, 120)
                self.assertEqual(writer.origin, 125.5)

    def test_future_frame_does_not_fill_preceding_gap(self):
        writer = TimedVideoWriter("test.mp4", 10, (6, 4))
        writer.write(self.frame(10), 17)
        writer.write(self.frame(20), 17.35)
        self.assertEqual(self.labels(), [10, 10, 10, 10])
        writer.close()
        self.assertEqual(self.labels(), [10, 10, 10, 10, 20])
        self.assertEqual(writer.origin, 17)

    def test_high_input_rate_and_duplicate_timestamp_replace_pending(self):
        writer = TimedVideoWriter("test.mp4", 10, (6, 4))
        writer.write(self.frame(10), 0)
        writer.write(self.frame(11), 0)
        writer.write(self.frame(20), .02)
        writer.write(self.frame(30), .04)
        writer.write(self.frame(40), .1)
        writer.close()
        self.assertEqual(self.labels(), [11, 40])

    def test_close_empty_or_twice_is_safe(self):
        writer = TimedVideoWriter("test.mp4", 10, (6, 4))
        writer.close()
        writer.close()
        self.assertEqual(self.labels(), [])
        self.assertEqual(self.codec.release_count, 1)
        self.assertIsNone(writer.origin)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            writer.write(self.frame(10), 0)

    def test_close_flushes_exactly_one_pending_frame(self):
        writer = TimedVideoWriter("test.mp4", 10, (6, 4))
        writer.write(self.frame(10), 12.5)
        self.assertEqual(writer.frames_written, 0)
        writer.close()
        writer.close()
        self.assertEqual(self.labels(), [10])
        self.assertEqual(writer.frames_written, 1)
        self.assertEqual(self.codec.release_count, 1)

    def test_pending_frame_is_copied(self):
        writer = TimedVideoWriter("test.mp4", 10, (6, 4))
        frame = self.frame(10)
        writer.write(frame, 0)
        frame[:] = 99
        writer.close()
        self.assertEqual(self.labels(), [10])

    def test_invalid_timestamp_does_not_advance_timeline(self):
        writer = TimedVideoWriter("test.mp4", 10, (6, 4))
        writer.write(self.frame(10), 1)
        for invalid in (float("nan"), float("inf"), -float("inf"), .9):
            with self.subTest(timestamp=invalid), self.assertRaises(ValueError):
                writer.write(self.frame(99), invalid)
        writer.write(self.frame(20), 1.1)
        writer.close()
        self.assertEqual(self.labels(), [10, 20])

    def test_large_gap_is_rejected_before_output_loop(self):
        writer = TimedVideoWriter("test.mp4", 10, (6, 4))
        writer.write(self.frame(10), 0)
        with self.assertRaisesRegex(ValueError, "exceeds 10 seconds"):
            writer.write(self.frame(99), 1_000_000)
        self.assertEqual(writer.frames_written, 0)
        writer.write(self.frame(20), .1)
        writer.close()
        self.assertEqual(self.labels(), [10, 20])

    def test_ten_second_gap_is_allowed(self):
        writer = TimedVideoWriter("test.mp4", 10, (6, 4))
        writer.write(self.frame(10), 0)
        writer.write(self.frame(20), 10)
        writer.close()
        self.assertEqual(self.labels(), [10] * 100 + [20])

    def test_invalid_fps_or_size_is_rejected_before_codec_creation(self):
        for fps in (0, -1, float("nan"), float("inf")):
            with self.subTest(fps=fps), self.assertRaises(ValueError):
                TimedVideoWriter("test.mp4", fps, (6, 4))
        for size in ((0, 4), (6, -1), (6.5, 4), (True, 4), (6,), None):
            with self.subTest(size=size), self.assertRaises(ValueError):
                TimedVideoWriter("test.mp4", 10, size)
        self.constructor.assert_not_called()

    def test_invalid_frame_does_not_replace_pending(self):
        writer = TimedVideoWriter("test.mp4", 10, (6, 4))
        writer.write(self.frame(10), 0)
        with self.assertRaisesRegex(ValueError, "uint8 BGR"):
            writer.write(np.zeros((4, 6), np.uint8), .1)
        with self.assertRaisesRegex(ValueError, "uint8 BGR"):
            writer.write(np.zeros((4, 6, 3), np.float32), .1)
        writer.close()
        self.assertEqual(self.labels(), [10])

    def test_failed_codec_is_released_and_reported(self):
        self.codec.opened = False
        with self.assertRaisesRegex(RuntimeError, "MP4 output codec"):
            TimedVideoWriter("test.mp4", 10, (6, 4))
        self.assertEqual(self.codec.release_count, 1)


if __name__ == "__main__":
    unittest.main()
