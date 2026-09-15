"""Sequential files, latest-frame live capture, and an illustrative demo source.

Live capture owns its OpenCV handle in one daemon thread. OpenCV timeouts are
best effort: some camera drivers/backends ignore them. Startup and consumer
waits still have deadlines, and ``close`` waits at most one second. A stuck
driver is never released concurrently with ``read``; its worker releases it
when the driver returns. Sources do not reconnect automatically.
"""

from __future__ import annotations

import math
import re
import threading
import time
from urllib.parse import urlsplit

import cv2
import numpy as np


_OPEN_TIMEOUT_MS = 5_000
_READ_TIMEOUT_MS = 5_000
_STARTUP_WAIT_SECONDS = 12.0
_FRAME_WAIT_SECONDS = 8.0


def _validate_source(source: str | int) -> tuple[str | int, bool]:
    """Return a normalized source and whether it is a camera/network source."""
    if isinstance(source, bool):
        raise ValueError("Video source must be a path, camera index, or supported URL.")
    if isinstance(source, int):
        if source < 0:
            raise ValueError("Camera index must be nonnegative.")
        return source, True
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Video source must be a path, camera index, or supported URL.")
    source = source.strip()
    if source.isdecimal():
        return int(source), True
    # Do not mistake an absolute Windows drive path for a URL scheme.
    if re.match(r"^[A-Za-z]:[\\/]", source):
        return source, False
    try:
        parsed = urlsplit(source)
        if parsed.scheme:
            if parsed.scheme.lower() not in {"rtsp", "rtsps", "http", "https"}:
                raise ValueError
            if not parsed.hostname:
                raise ValueError
            return source, True
    except ValueError:
        # Never interpolate a URL: it may contain a password.
        raise ValueError("Unsupported or malformed video URL; use RTSP or HTTP(S).") from None
    return source, False


def _capture_fps(capture: cv2.VideoCapture) -> float:
    value = float(capture.get(cv2.CAP_PROP_FPS))
    return value if math.isfinite(value) and value > 0 else 30.0


def _open_capture(source: str | int, network: bool) -> cv2.VideoCapture:
    """Attempt FFmpeg timeout parameters, with one backend compatibility fallback."""
    if not network:
        return cv2.VideoCapture(source)
    open_property = getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None)
    read_property = getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None)
    if open_property is not None and read_property is not None:
        capture = cv2.VideoCapture()
        try:
            opened = capture.open(
                source,
                cv2.CAP_FFMPEG,
                [open_property, _OPEN_TIMEOUT_MS, read_property, _READ_TIMEOUT_MS],
            )
        except (cv2.error, TypeError):
            opened = False
        if opened:
            return capture
        capture.release()
    # Older OpenCV bindings or backends may reject open-only timeout settings.
    # This is a startup fallback, not a reconnect loop. It remains on the
    # bounded-wait daemon worker because this overload can block in the driver.
    return cv2.VideoCapture(source, cv2.CAP_FFMPEG)


class VideoSource:
    """Read files sequentially or the newest available live frame.

    ``read()`` returns ``(ok, frame, source_frame_index, timestamp_seconds)``.
    File timestamps are deterministic ``index / fps``. For live sources they
    are monotonic elapsed capture time; indices include frames dropped while
    the consumer was busy. Webcam indices and supported URLs select live mode
    automatically. Supplying ``live=True`` can also play a file through the
    latest-frame worker, without pacing it to its nominal FPS.

    End of a file returns ``ok=False``. A live camera/stream failure raises a
    generic RuntimeError so the caller can distinguish it from normal EOF.
    Source strings are never included in application exceptions.
    """

    def __init__(self, source: str | int, live: bool = False) -> None:
        normalized, automatic_live = _validate_source(source)
        self.live = bool(live or automatic_live)
        self.fps = 30.0
        self._source = normalized
        self._automatic_live = automatic_live
        self._network = automatic_live and isinstance(normalized, str)
        self._capture: cv2.VideoCapture | None = None
        self._closed = False
        self._next_index = 0
        self._started_at = time.monotonic()
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._latest: tuple[np.ndarray, int, float] | None = None
        self._error: str | None = None
        self._eof = False
        self._worker: threading.Thread | None = None

        if self.live:
            self._worker = threading.Thread(
                target=self._capture_live, name="visioneye-capture", daemon=True
            )
            self._worker.start()
            if not self._ready.wait(_STARTUP_WAIT_SECONDS):
                self.close()
                raise RuntimeError("Video source did not open before the startup deadline.")
            if self._error is not None:
                message = self._error
                self.close()
                raise RuntimeError(message) from None
        else:
            try:
                capture = _open_capture(normalized, network=False)
                if not capture.isOpened():
                    capture.release()
                    raise RuntimeError("Could not open video source.")
                self._capture = capture
                self.fps = _capture_fps(capture)
            except Exception:
                if self._capture is not None:
                    self._capture.release()
                    self._capture = None
                raise RuntimeError("Could not open video source.") from None

    def __enter__(self) -> VideoSource:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _capture_live(self) -> None:
        capture = None
        try:
            capture = _open_capture(self._source, self._network)
            if not capture.isOpened():
                raise RuntimeError("Could not open video source.")
            self.fps = _capture_fps(capture)
            self._started_at = time.monotonic()
            # The latest-frame slot already bounds application memory. This
            # backend hint may also reduce driver buffering where supported.
            try:
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except cv2.error:
                pass  # Optional driver hint; the application slot stays bounded.
            self._ready.set()
            while not self._stop.is_set():
                ok, frame = capture.read()
                timestamp = time.monotonic() - self._started_at
                if not ok or frame is None:
                    with self._condition:
                        if self._automatic_live and not self._stop.is_set():
                            self._error = "Live video source stopped producing frames."
                        self._eof = True
                        self._condition.notify_all()
                    break
                with self._condition:
                    if self._stop.is_set():
                        break
                    self._latest = (frame, self._next_index, timestamp)
                    self._next_index += 1
                    self._condition.notify_all()
        except Exception:
            with self._condition:
                self._error = (
                    "Live video source failed while reading frames."
                    if self._ready.is_set()
                    else "Could not open video source."
                )
                self._eof = True
                self._condition.notify_all()
        finally:
            self._ready.set()
            # The worker is the only thread that ever accesses this handle.
            if capture is not None:
                capture.release()
            with self._condition:
                self._eof = True
                self._condition.notify_all()

    def read(self) -> tuple[bool, np.ndarray | None, int, float]:
        if self._closed:
            return False, None, self._next_index, self._next_index / self.fps
        if not self.live:
            assert self._capture is not None
            index = self._next_index
            try:
                ok, frame = self._capture.read()
            except Exception:
                raise RuntimeError("Could not read video frame.") from None
            if not ok or frame is None:
                return False, None, index, index / self.fps
            self._next_index += 1
            return True, frame, index, index / self.fps

        deadline = time.monotonic() + _FRAME_WAIT_SECONDS
        with self._condition:
            while self._latest is None:
                if self._closed or self._stop.is_set():
                    return False, None, self._next_index, time.monotonic() - self._started_at
                if self._error is not None:
                    raise RuntimeError(self._error) from None
                if self._eof:
                    return False, None, self._next_index, time.monotonic() - self._started_at
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._stop.set()
                    raise RuntimeError("Live video source did not deliver a frame before the deadline.")
                self._condition.wait(remaining)
            frame, index, timestamp = self._latest
            self._latest = None
            return True, frame, index, timestamp

    def close(self) -> None:
        """Stop consumption; a live worker releases its own handle safely."""
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        with self._condition:
            self._latest = None
            self._condition.notify_all()
        if self._worker is not None:
            self._worker.join(timeout=1.0)
        elif self._capture is not None:
            self._capture.release()
            self._capture = None


class SyntheticSource:
    """360 deterministic illustrated frames, with scripted identity/box metadata.

    This is an analytics/visualization demonstration, not detector output or
    evidence of detector performance. Three illustrated people enter toward
    the bottom of the scene; the first later returns across the default line.
    Their foot positions cross y=0.55 in the order IN, IN, IN, OUT.
    """

    fps = 30.0
    live = False

    def __init__(self) -> None:
        self.width = 960
        self.height = 540
        self.detections: list[dict] = []
        self._next_index = 0
        self._closed = False
        self._background = self._make_background()

    def __enter__(self) -> SyntheticSource:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _make_background(self) -> np.ndarray:
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = (33, 27, 23)
        floor = np.array([[250, 65], [710, 65], [935, 540], [25, 540]], np.int32)
        cv2.fillConvexPoly(frame, floor, (68, 60, 49), lineType=cv2.LINE_AA)
        vanishing_point = (480, -420)
        for bottom_x in range(-700, 1800, 105):
            cv2.line(frame, vanishing_point, (bottom_x, 540), (81, 72, 60), 1, cv2.LINE_AA)
        for row in range(8):
            y = int(70 + 465 * (row / 7) ** 1.55)
            cv2.line(frame, (0, y), (960, y), (83, 74, 61), 1, cv2.LINE_AA)
        # Side boundaries keep the perspective scene legible under overlays.
        cv2.line(frame, (250, 65), (25, 540), (139, 127, 101), 3, cv2.LINE_AA)
        cv2.line(frame, (710, 65), (935, 540), (139, 127, 101), 3, cv2.LINE_AA)
        cv2.rectangle(frame, (340, 15), (620, 64), (54, 45, 36), -1)
        cv2.putText(frame, "WALKWAY", (402, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (187, 192, 181), 1, cv2.LINE_AA)
        return frame

    @staticmethod
    def _interpolate(index: int, start: int, end: int, first: float, last: float) -> float:
        fraction = max(0.0, min(1.0, (index - start) / (end - start)))
        return first + fraction * (last - first)

    def read(self) -> tuple[bool, np.ndarray | None, int, float]:
        index = self._next_index
        if self._closed or index >= 360:
            self.detections = []
            return False, None, index, index / self.fps
        frame = self._background.copy()
        first_y = (
            self._interpolate(index, 0, 180, 0.22, 0.83)
            if index <= 225
            else self._interpolate(index, 225, 359, 0.83, 0.22)
        )
        positions = [
            (1, 0.28, first_y, (193, 160, 69)),
            (2, 0.51, self._interpolate(index, 50, 225, 0.18, 0.84), (111, 168, 216)),
            (3, 0.73, self._interpolate(index, 110, 265, 0.17, 0.83), (167, 103, 192)),
        ]
        self.detections = []
        for track_id, x, y, shirt in positions:
            center_x = int((x + 0.008 * math.sin(index / 40 + track_id)) * self.width)
            foot_y = int(y * self.height)
            person_height = int(48 + y * 90)
            person_width = int(person_height * 0.38)
            left = center_x - person_width // 2
            right = center_x + person_width // 2
            top = foot_y - person_height
            head_radius = max(6, person_width // 5)
            stride = int(3 * math.sin(index * 0.15 + track_id))
            cv2.ellipse(frame, (center_x, foot_y + 2), (person_width // 2 + 8, 5),
                        0, 0, 360, (38, 34, 29), -1, cv2.LINE_AA)
            hip_y = top + int(person_height * 0.68)
            for offset, direction in [(-person_width // 5, 1), (person_width // 5, -1)]:
                cv2.line(frame, (center_x + offset, hip_y),
                         (center_x + offset + stride * direction, foot_y - 3),
                         (38, 42, 52), max(5, person_width // 6), cv2.LINE_AA)
            shoulder_y = top + head_radius * 2 + 4
            cv2.rectangle(frame, (left + 5, shoulder_y), (right - 5, hip_y), shirt, -1)
            cv2.line(frame, (left + 5, shoulder_y + 5), (left + 2, hip_y - 4),
                     shirt, max(5, person_width // 7), cv2.LINE_AA)
            cv2.line(frame, (right - 5, shoulder_y + 5), (right - 2, hip_y - 4),
                     shirt, max(5, person_width // 7), cv2.LINE_AA)
            cv2.circle(frame, (center_x, top + head_radius), head_radius,
                       (143, 185, 218), -1, cv2.LINE_AA)
            self.detections.append({
                "xyxy": [left, top, right, foot_y],
                "track_id": track_id,
                "confidence": 1.0,
            })
        self._next_index += 1
        return True, frame, index, index / self.fps

    def close(self) -> None:
        self._closed = True
        self.detections = []
