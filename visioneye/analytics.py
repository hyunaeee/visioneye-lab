"""Directional foot-traffic counting without image-processing dependencies.

The gate is an oriented, finite line segment. A point's signed distance is
``cross(gate_end - gate_start, point - gate_start) / gate_length``. Thus a
left-to-right horizontal gate has positive distance below it in image pixels.
An IN event enters ``in_side``; reversing the gate reverses the side signs.

Tracks must be observed outside the hysteresis band on both sides to count.
The observed path must cross the actual gate, not its infinite extension.
Counters measure observed crossings; they cannot recover people already in a
scene or repair tracker identity switches. Occupancy is a clamped estimate;
raw_occupancy and underflow expose any unmatched OUT events.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, List, Optional, Tuple


Point = Tuple[float, float]
_EPSILON = 1e-9


def _point(value: object) -> Point:
    try:
        x, y = value  # type: ignore[misc]
        point = (float(x), float(y))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Points must contain exactly two finite coordinates") from exc
    if not all(math.isfinite(coordinate) for coordinate in point):
        raise ValueError("Point coordinates must be finite")
    return point


def _integer(value: object, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


@dataclass
class _Track:
    last_seen: int
    stable_side: int
    raw_side: int
    raw_anchor: Point
    last_zero: Optional[Point] = None
    pending_side: int = 0
    pending_valid: bool = False


class DirectionalCounter:
    """Confirm finite-gate crossings from tracked footpoints.

    ``hysteresis`` is the minimum pixel distance from the line required to
    establish either side. An observation gap greater than ``max_gap_frames``
    seeds a new history for that ID. States unseen for more than ``ttl_frames``
    are discarded. Call once per video frame, including frames with no people.
    Frame indices must increase; an exact duplicate frame is ignored.
    """

    def __init__(
        self,
        line: Tuple[Point, Point],
        in_side: int = 1,
        hysteresis: float = 8.0,
        initial_occupancy: int = 0,
        max_gap_frames: int = 15,
        ttl_frames: int = 120,
    ) -> None:
        try:
            start, end = line
        except (TypeError, ValueError) as exc:
            raise ValueError("line must contain two distinct points") from exc
        self.line = (_point(start), _point(end))
        self._dx = self.line[1][0] - self.line[0][0]
        self._dy = self.line[1][1] - self.line[0][1]
        self._length = math.hypot(self._dx, self._dy)
        if self._length <= _EPSILON:
            raise ValueError("line endpoints must be distinct")
        if isinstance(in_side, bool) or in_side not in (-1, 1):
            raise ValueError("in_side must be -1 or 1")
        self.in_side = in_side
        self.hysteresis = float(hysteresis)
        if not math.isfinite(self.hysteresis) or self.hysteresis < 0:
            raise ValueError("hysteresis must be finite and nonnegative")
        self.initial_occupancy = _integer(initial_occupancy, "initial_occupancy")
        self.max_gap_frames = _integer(max_gap_frames, "max_gap_frames")
        self.ttl_frames = _integer(ttl_frames, "ttl_frames")
        self.total_in = 0
        self.total_out = 0
        self._tracks: Dict[int, _Track] = {}
        self._last_frame: Optional[int] = None

    @property
    def raw_occupancy(self) -> int:
        return self.initial_occupancy + self.total_in - self.total_out

    @property
    def occupancy(self) -> int:
        return max(0, self.raw_occupancy)

    @property
    def underflow(self) -> bool:
        return self.raw_occupancy < 0

    def stats(self) -> dict:
        return {
            "total_in": self.total_in,
            "total_out": self.total_out,
            "occupancy": self.occupancy,
            "raw_occupancy": self.raw_occupancy,
            "underflow": self.underflow,
            "active_tracks": len(self._tracks),
        }

    def _distance(self, point: Point) -> float:
        px = point[0] - self.line[0][0]
        py = point[1] - self.line[0][1]
        return (self._dx * py - self._dy * px) / self._length

    @staticmethod
    def _sign(distance: float) -> int:
        return 1 if distance > _EPSILON else -1 if distance < -_EPSILON else 0

    def _stable_side(self, distance: float) -> int:
        if abs(distance) <= _EPSILON or abs(distance) < self.hysteresis:
            return 0
        return self._sign(distance)

    def _on_gate(self, point: Point) -> bool:
        # Called only for a point on the infinite gate line.
        projection = (
            (point[0] - self.line[0][0]) * self._dx
            + (point[1] - self.line[0][1]) * self._dy
        ) / (self._length * self._length)
        return -_EPSILON <= projection <= 1.0 + _EPSILON

    def _crosses_gate(self, before: Point, after: Point) -> bool:
        before_distance = self._distance(before)
        after_distance = self._distance(after)
        denominator = before_distance - after_distance
        if abs(denominator) <= _EPSILON:
            return False
        fraction = before_distance / denominator
        if not -_EPSILON <= fraction <= 1.0 + _EPSILON:
            return False
        intersection = (
            before[0] + fraction * (after[0] - before[0]),
            before[1] + fraction * (after[1] - before[1]),
        )
        return self._on_gate(intersection)

    def update(
        self,
        points: Dict[int, Point],
        frame_index: int,
        timestamp: float,
    ) -> List[dict]:
        """Return newly confirmed events, timestamped at confirmation time."""
        frame_index = _integer(frame_index, "frame_index")
        if self._last_frame is not None:
            if frame_index < self._last_frame:
                raise ValueError("frame_index must not move backwards")
            if frame_index == self._last_frame:
                return []
        timestamp = float(timestamp)
        if not math.isfinite(timestamp):
            raise ValueError("timestamp must be finite")
        # Validate the complete frame before changing counter state.
        validated = {
            _integer(track_id, "track_id"): _point(point)
            for track_id, point in points.items()
        }
        self._last_frame = frame_index
        self._tracks = {
            track_id: track
            for track_id, track in self._tracks.items()
            if frame_index - track.last_seen <= self.ttl_frames
        }
        events: List[dict] = []
        for track_id, point in validated.items():
            distance = self._distance(point)
            raw_side = self._sign(distance)
            stable_side = self._stable_side(distance)
            track = self._tracks.get(track_id)
            if track is None or frame_index - track.last_seen > self.max_gap_frames:
                self._tracks[track_id] = _Track(
                    last_seen=frame_index,
                    stable_side=stable_side,
                    raw_side=raw_side,
                    raw_anchor=point,
                    last_zero=point if raw_side == 0 else None,
                )
                continue
            track.last_seen = frame_index

            if raw_side == 0:
                # If a sampled path follows the line, use its final departure
                # point to decide whether the crossing occurred on the gate.
                track.last_zero = point
            else:
                if track.raw_side and raw_side != track.raw_side:
                    valid_crossing = (
                        self._on_gate(track.last_zero)
                        if track.last_zero is not None
                        else self._crosses_gate(track.raw_anchor, point)
                    )
                    track.pending_side = raw_side
                    track.pending_valid = valid_crossing
                track.raw_side = raw_side
                track.raw_anchor = point
                track.last_zero = None

            if stable_side:
                if (
                    track.stable_side
                    and stable_side != track.stable_side
                    and track.pending_side == stable_side
                    and track.pending_valid
                ):
                    direction = "IN" if stable_side == self.in_side else "OUT"
                    if direction == "IN":
                        self.total_in += 1
                    else:
                        self.total_out += 1
                    events.append({
                        "track_id": track_id,
                        "direction": direction,
                        "frame": frame_index,
                        "timestamp": timestamp,
                    })
                # A crossing around an endpoint still changes the stable side,
                # preventing a later false count when the person moves inward.
                track.stable_side = stable_side
                track.pending_side = 0
                track.pending_valid = False
        return events
