"""Constant-frame-rate recording that preserves capture-time spacing.

Missing live frames are filled with the preceding rendered dashboard. A new
frame is never used to fill a gap before its capture timestamp. Video time zero
is ``origin``, so a CSV event at time T corresponds to video time T - origin.
"""

from __future__ import annotations

import math

import cv2
import numpy as np


class TimedVideoWriter:
    """Resample rendered frames onto a fixed FPS timeline using previous frames.

    The newest frame remains pending until another timestamp arrives. ``close``
    appends that last frame once and releases the codec. Repeated timestamps
    replace the pending frame. The final image may be rounded up by less than
    one output-frame period. A capture gap above ten seconds raises instead of
    generating an unexpectedly long frozen recording.
    """

    MAX_GAP_SECONDS = 10.0
    _SLOT_TOLERANCE = 1e-7

    def __init__(self, path, fps, size):
        self.fps = float(fps)
        if not math.isfinite(self.fps) or self.fps <= 0:
            raise ValueError("Recording FPS must be finite and greater than zero.")
        try:
            width, height = size
        except (TypeError, ValueError) as exc:
            raise ValueError("Recording size must be a (width, height) pair.") from exc
        if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (width, height)):
            raise ValueError("Recording width and height must be positive integers.")
        self.size = (width, height)
        self.origin = None
        self.frames_written = 0
        self._last_timestamp = None
        self._pending = None
        self._closed = False
        self._writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, self.size
        )
        if not self._writer.isOpened():
            self._writer.release()
            self._closed = True
            raise RuntimeError("Cannot open MP4 output codec.")

    def write(self, display, timestamp):
        """Accept one BGR dashboard and its monotonic source timestamp."""
        if self._closed:
            raise RuntimeError("Cannot write to a closed video recording.")
        timestamp = float(timestamp)
        if not math.isfinite(timestamp):
            raise ValueError("Recording timestamp must be finite.")
        if self._last_timestamp is not None:
            if timestamp < self._last_timestamp:
                raise ValueError("Recording timestamps must not move backwards.")
            if timestamp - self._last_timestamp > self.MAX_GAP_SECONDS:
                raise ValueError(
                    "Recording capture gap exceeds 10 seconds; start a new recording."
                )
        width, height = self.size
        if (
            not isinstance(display, np.ndarray)
            or display.dtype != np.uint8
            or display.shape != (height, width, 3)
        ):
            raise ValueError("Recording frame must be a uint8 BGR image matching the output size.")
        # Own the pending pixels, because callers may reuse their frame buffer.
        next_frame = display.copy()
        if self.origin is None:
            self.origin = timestamp
        else:
            # Slot n is due at origin + n / fps. Write only slots strictly
            # before this input frame's time, using the previously seen image.
            # A small slot tolerance handles timestamps such as 3 * (1 / 30).
            relative_slot = (timestamp - self.origin) * self.fps
            due_slots = math.ceil(relative_slot - self._SLOT_TOLERANCE)
            for _ in range(max(0, due_slots - self.frames_written)):
                self._writer.write(self._pending)
                self.frames_written += 1
        self._pending = next_frame
        self._last_timestamp = timestamp

    def close(self):
        """Flush the final pending image once; repeated calls do nothing."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._pending is not None:
                self._writer.write(self._pending)
                self.frames_written += 1
        finally:
            self._pending = None
            self._writer.release()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
